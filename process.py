import os, imaplib, email, json, re
import google.generativeai as genai 
from email.utils import parsedate_to_datetime
from email.header import decode_header

# 1. Configuration de l'IA (Utilisation de la bibliothèque stable)
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

def get_newsletter():
    """Récupère les mails, filtre les expéditeurs et extrait le contenu HTML."""
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        mail.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASSWORD"])
    except Exception as e:
        print(f"❌ Erreur Connexion Gmail : {e}")
        return []

    mail.select("inbox")
    
    # Liste des expéditeurs autorisés (dont la tienne et celle d'Hugo)
    AUTORISES = [
        "hugodecrypte@kessel.media", 
        "hugo@hugodecrypte.com", 
        "qcm.newsletter@gmail.com"
    ]
    
    status, messages = mail.search(None, 'ALL')
    results = []
    ids = messages[0].split()
    
    print(f"🔎 {len(ids)} mails trouvés dans la boîte. Analyse des 15 derniers...")

    for m_id in ids[-15:]:
        res, msg_data = mail.fetch(m_id, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        
        # Extraction propre de l'adresse email de l'expéditeur
        sender_raw = str(msg.get("From")).lower()
        sender_email = re.findall(r'[\w\.-]+@[\w\.-]+', sender_raw)
        sender = sender_email[0] if sender_email else sender_raw

        # Décodage du sujet du mail
        subject_parts = decode_header(msg["Subject"])
        subject = ""
        for part, encoding in subject_parts:
            if isinstance(part, bytes):
                subject += part.decode(encoding or "utf-8")
            else:
                subject += part

        print(f"--- Analyse : {subject[:40]}... | De : {sender}")

        # Vérification si l'expéditeur est dans notre liste blanche
        if any(addr.lower() in sender for addr in AUTORISES):
            print(f"   ✅ MATCH ! Cet expéditeur est autorisé.")
            
            # Récupération de la date réelle du mail
            dt = parsedate_to_datetime(msg.get("Date"))
            date_formattee = dt.strftime("%d %b")
            
            # Extraction du corps HTML
            html_body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        html_body = part.get_payload(decode=True).decode(errors='ignore')
            else:
                html_body = msg.get_payload(decode=True).decode(errors='ignore')
                
            if html_body:
                results.append({
                    "subject": subject, 
                    "html": html_body, 
                    "date": date_formattee,
                    # ID unique basé sur la date et le sujet pour éviter les doublons de fichiers
                    "id_unique": f"{dt.strftime('%Y%m%d')}-{re.sub(r'[^a-zA-Z0-9]', '', subject[:10])}"
                })
        else:
            print(f"   ❌ Ignoré (Expéditeur non listé)")

    mail.logout()
    return results

# --- LANCEMENT DU TRAITEMENT ---
newslettersFound = get_newsletter()

if newslettersFound:
    # Chargement du manifest existant pour éviter les doublons de quiz
    try:
        with open('manifest.json', 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except:
        manifest = []

    deja_presents = [item.get("titre_original", "") for item in manifest]
    
    # Initialisation du modèle Gemini 1.5 Flash (Stable)
    model = genai.GenerativeModel('gemini-1.5-flash')

    for nl in newslettersFound:
        if nl["subject"] in deja_presents:
            print(f"⏩ Déjà traité (Ignoré) : {nl['subject']}")
            continue

        print(f"🤖 IA en cours pour : {nl['subject']}")
        
        prompt = f"""Analyse cette newsletter. 
        1. Trouve l'URL de l'image de couverture principale (src de la balise <img>). 
        2. Garde le HTML propre (gras, listes), retire les pubs. 
        3. Choisis le thème le plus proche parmi : Politique, Économie, Technologie, Écologie, Société, Culture, Sport, Géopolitique, Science, Insolite.
        4. Génère 10 questions QCM (4 options, 1 correct index 0-3, 1 explication).
        Sortie JSON strict uniquement: {{"titre":"", "image":"", "theme":"", "contenu_html":"", "questions":[]}}"""
        
        try:
            # Appel à l'API Gemini
            response = model.generate_content(prompt + "\n\nTEXTE:\n" + nl['html'])
            
            # Extraction du JSON dans la réponse de l'IA
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if match:
                data = json.loads(match.group())
                
                # Sauvegarde du fichier JSON individuel
                filename = f"quiz-{nl['id_unique']}.json"
                os.makedirs('data', exist_ok=True)
                with open(f"data/{filename}", 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False)
                
                # Mise à jour de la liste principale (manifest)
                manifest.append({
                    "date": nl['date'], 
                    "file": filename, 
                    "titre": data['titre'], 
                    "titre_original": nl['subject'],
                    "image": data.get('image', 'https://images.unsplash.com/photo-1504711434969-e33886168f5c'),
                    "theme": data['theme']
                })
                print(f"   💾 Sauvegardé avec succès : {filename}")
        except Exception as e:
            print(f"❌ Erreur Gemini sur ce mail : {e}")

    # Sauvegarde finale du manifest mis à jour
    with open('manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False)
else:
    print("📢 Fin du scan : Aucune nouvelle newsletter correspondante trouvée.")
