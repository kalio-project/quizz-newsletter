import os, imaplib, email, json, re
from google import genai
from email.utils import parsedate_to_datetime
from email.header import decode_header

# 1. INITIALISATION DU CLIENT GEMINI
# On force la version 'v1' pour éviter les erreurs 404 de l'API Beta
client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"],
    http_options={'api_version': 'v1'}
)

def get_newsletter():
    """Se connecte à Gmail, filtre les expéditeurs et extrait le contenu."""
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        mail.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASSWORD"])
    except Exception as e:
        print(f"❌ Erreur Connexion Gmail : {e}")
        return []

    mail.select("inbox")
    
    # Liste blanche des expéditeurs (Ajoute ici les adresses de tes newsletters)
    AUTORISES = [
        "hugodecrypte@kessel.media", 
        "hugo@hugodecrypte.com", 
        "qcm.newsletter@gmail.com"
    ]
    
    # On cherche tous les messages
    status, messages = mail.search(None, 'ALL')
    results = []
    ids = messages[0].split()
    
    print(f"🔎 {len(ids)} mails trouvés. Analyse des 15 derniers pour trouver des newsletters...")

    for m_id in ids[-15:]:
        res, msg_data = mail.fetch(m_id, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        
        # Nettoyage de l'expéditeur pour comparaison
        sender_raw = str(msg.get("From")).lower()
        sender_email = re.findall(r'[\w\.-]+@[\w\.-]+', sender_raw)
        sender = sender_email[0] if sender_email else sender_raw

        # Décodage propre du sujet (gère les accents et émojis)
        subject_parts = decode_header(msg["Subject"])
        subject = ""
        for part, encoding in subject_parts:
            if isinstance(part, bytes):
                subject += part.decode(encoding or "utf-8", errors="ignore")
            else:
                subject += part

        print(f"--- Analyse : {subject[:40]}... | De : {sender}")

        # Vérification de l'autorisation
        if any(addr.lower() in sender for addr in AUTORISES):
            print(f"   ✅ MATCH ! Newsletter détectée.")
            
            # Date réelle du mail pour l'affichage sur le site
            dt = parsedate_to_datetime(msg.get("Date"))
            date_formattee = dt.strftime("%d %b")
            
            # Extraction du corps HTML (on cherche la version riche du mail)
            html_body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        html_body = part.get_payload(decode=True).decode(errors='ignore')
            else:
                html_body = msg.get_payload(decode=True).decode(errors='ignore')
                
            if html_body:
                # On crée un ID unique basé sur la date et le sujet pour le nom du fichier
                id_propre = re.sub(r'[^a-zA-Z0-9]', '', subject[:10])
                results.append({
                    "subject": subject, 
                    "html": html_body, 
                    "date": date_formattee,
                    "id_unique": f"{dt.strftime('%Y%m%d')}-{id_propre}"
                })
        else:
            print(f"   ❌ Ignoré (Expéditeur non autorisé)")

    mail.logout()
    return results

# --- LOGIQUE PRINCIPALE ---
newslettersFound = get_newsletter()

if newslettersFound:
    # 2. CHARGEMENT DU MANIFEST (La base de données du site)
    try:
        with open('manifest.json', 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except:
        manifest = []

    # On liste les titres déjà présents pour ne pas créer de doublons
    deja_presents = [item.get("titre_original", "") for item in manifest]
    themes_officiels = ["Politique", "Économie", "Technologie", "Écologie", "Société", "Culture", "Sport", "Géopolitique", "Science", "Insolite"]

    for nl in newslettersFound:
        # Anti-doublon : Si le sujet exact est déjà dans le manifest, on passe
        if nl["subject"] in deja_presents:
            print(f"⏩ Déjà traité (Skip) : {nl['subject']}")
            continue

        print(f"🤖 IA Gemini 1.5 Flash en cours d'analyse pour : {nl['subject']}")
        
        prompt = f"""Tu es un analyste média. Analyse cette newsletter et transforme-la en quiz :
        1. IMAGE : Trouve l'URL de l'image de couverture principale (balise <img>).
        2. CONTENU : Garde le texte HTML propre (uniquement <b>, <i>, <ul>, <li>, <p>). Retire les pubs.
        3. THÈME : Choisis UNIQUEMENT parmi : {", ".join(themes_officiels)}.
        4. QUIZ : Génère 10 questions QCM pertinentes. Chaque question a 4 options, un index correct (0-3) et une explication courte.
        
        FORMAT DE SORTIE : JSON STRICT UNIQUEMENT.
        {{
            "titre": "Titre accrocheur",
            "image": "URL_IMAGE",
            "theme": "Thème choisi",
            "contenu_html": "Contenu nettoyé",
            "questions": [
                {{"q": "Ma question ?", "options": ["A", "B", "C", "D"], "correct": 0, "explication": "Car..."}}
            ]
        }}"""
        
        try:
            # Appel à l'API Gemini 1.5 Flash
            response = client.models.generate_content(
                model='gemini-1.5-flash',
                contents=prompt + "\n\nTEXTE DE LA NEWSLETTER :\n" + nl['html']
            )
            
            # Extraction du bloc JSON dans la réponse de l'IA
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if match:
                data = json.loads(match.group())
                
                # Sauvegarde du fichier Quiz individuel
                filename = f"quiz-{nl['id_unique']}.json"
                os.makedirs('data', exist_ok=True)
                with open(f"data/{filename}", 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False)
                
                # Ajout au manifest pour affichage sur l'index
                manifest.append({
                    "date": nl['date'], 
                    "file": filename, 
                    "titre": data['titre'], 
                    "titre_original": nl['subject'],
                    "image": data.get('image', 'https://images.unsplash.com/photo-1504711434969-e33886168f5c'),
                    "theme": data['theme']
                })
                print(f"   💾 Fichier créé : {filename}")
        except Exception as e:
            print(f"❌ Erreur IA sur ce mail : {e}")

    # 3. SAUVEGARDE FINALE DU MANIFEST
    # On trie pour avoir les plus récents en premier si besoin, mais le JS s'en occupe
    with open('manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False)
    print("✅ Manifest.json mis à jour avec succès.")

else:
    print("📢 Fin du scan : Pas de nouvelles newsletters à traiter aujourd'hui.")
