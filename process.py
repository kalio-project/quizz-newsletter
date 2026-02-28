import os, imaplib, email, json, re, html
from google import genai
from email.utils import parsedate_to_datetime
from email.header import decode_header

# --- CONFIGURATION ---
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# Liste stricte pour l'IA et le filtrage du site
THEMES_LIST = "POLITIQUE, GÉOPOLITIQUE, ÉCONOMIE, SOCIÉTÉ, SANTÉ, ENVIRONNEMENT, TECHNOLOGIE, CULTURE, SPORT, INTERNATIONAL"

def clean_newsletter_html(raw_html):
    """
    Découpe le HTML pour ne garder que le contenu utile entre 
    'Ouvrir dans le navigateur' et 'Vous avez aimé cette newsletter'.
    """
    start_marker = r"Ouvrir\s+dans\s+le\s+navigateur"
    end_marker = r"Vous\s+avez\s+aim\u00e9\s+cette\s+newsletter"
    
    content = raw_html
    # Coupe le haut
    split_start = re.split(start_marker, content, flags=re.IGNORECASE)
    if len(split_start) > 1:
        content = split_start[-1]
    
    # Coupe le bas
    split_end = re.split(end_marker, content, flags=re.IGNORECASE)
    if len(split_end) > 1:
        content = split_end[0]
        
    # Nettoyage des balises structurelles résiduelles
    content = re.sub(r'^.*?<body.*?>', '', content, flags=re.DOTALL | re.IGNORECASE)
    return content.strip()

def get_newsletters():
    """Récupère les 10 derniers mails d'HugoDécrypte."""
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        mail.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASSWORD"])
    except Exception as e:
        print(f"Erreur connexion Gmail : {e}")
        return []

    mail.select("inbox")
    # Liste des expéditeurs autorisés
    AUTORISES = ["hugodecrypte@kessel.media", "hugo@hugodecrypte.com", "qcm.newsletter@gmail.com"]
    
    status, messages = mail.search(None, 'ALL')
    ids = messages[0].split()
    results = []

    # On analyse les 10 derniers messages
    for m_id in ids[-10:]:
        res, data = mail.fetch(m_id, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])
        sender = str(msg.get("From")).lower()

        if any(addr.lower() in sender for addr in AUTORISES):
            # Décodage du sujet
            subject_parts = decode_header(msg["Subject"])
            subject = "".join([part.decode(enc or 'utf-8') if isinstance(part, bytes) else part for part, enc in subject_parts])
            dt = parsedate_to_datetime(msg.get("Date"))
            
            # Extraction du HTML
            body_html = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        body_html = part.get_payload(decode=True).decode(errors='ignore')
            else:
                body_html = msg.get_payload(decode=True).decode(errors='ignore')
            
            if body_html:
                # Texte brut pour l'IA (sans balises)
                text_clean = re.sub(r'<(style|script|head).*?>.*?</\1>', '', body_html, flags=re.DOTALL | re.IGNORECASE)
                text_clean = re.sub(r'<.*?>', ' ', text_clean)
                
                results.append({
                    "subject": subject,
                    "full_html": clean_newsletter_html(body_html),
                    "text_only": html.unescape(text_clean),
                    "date": dt.strftime("%d %b %Y"),
                    "id": f"{dt.strftime('%Y%m%d')}-{re.sub(r'[^a-z]', '', subject.lower())[:10]}"
                })
    mail.logout()
    return results

# --- EXÉCUTION PRINCIPALE ---
newsletters = get_newsletters()

if newsletters:
    # Chargement du manifest existant
    try:
        with open('manifest.json', 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except:
        manifest = []
    
    deja_vus = [m.get("titre_original") for m in manifest]

    for nl in newsletters:
        if nl["subject"] in deja_vus:
            print(f"⏩ Déjà traité : {nl['subject']}")
            continue

        print(f"🤖 Analyse IA en cours : {nl['subject']}...")

        prompt = f"""Tu es un expert en analyse de presse. 
        Transforme ce texte en un quiz de 10 questions.
        
        THÈMES AUTORISÉS (choisir 1 par question) :
        {THEMES_LIST}

        FORMAT JSON STRICT :
        {{
          "theme_global": "Un thème de la liste",
          "titre": "Titre court",
          "questions": [
            {{
              "q": "Question ?",
              "options": ["A", "B", "C", "D"],
              "correct": 0,
              "explication": "Détail pédagogique",
              "theme": "Un thème de la liste"
            }}
          ]
        }}"""

        try:
            # Appel à Gemini (limité à 8000 caractères pour l'efficacité)
            response = client.models.generate_content(
                model='gemini-2.0-flash', 
                contents=f"{prompt}\n\nTEXTE :\n{nl['text_only'][:8000]}"
            )
            
            # Extraction du JSON dans la réponse de l'IA
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if json_match:
                quiz_data = json.loads(json_match.group())
                
                # Ajout du HTML nettoyé dans le fichier JSON final
                quiz_data['contenu_html'] = nl['full_html']
                
                # Recherche de l'image principale (serveur Kessel ou Google)
                img_url = "https://images.unsplash.com/photo-1504711434969-e33886168f5c" # Fallback
                img_candidates = re.findall(r'src="(https://.*?)"', nl['full_html'])
                for url in img_candidates:
                    if "kessel" in url or "usercontent" in url:
                        img_url = url
                        break
                
                # Sauvegarde du fichier quiz individuel
                quiz_filename = f"data/quiz-{nl['id']}.json"
                os.makedirs('data', exist_ok=True)
                with open(quiz_filename, 'w', encoding='utf-8') as f:
                    json.dump(quiz_data, f, ensure_ascii=False)
                
                # Mise à jour du manifest
                manifest.append({
                    "date": nl['date'],
                    "file": quiz_filename,
                    "titre": quiz_data.get('titre', nl['subject']),
                    "titre_original": nl['subject'],
                    "image": img_url,
                    "theme": quiz_data.get('theme_global', 'INTERNATIONAL')
                })
                print(f"✅ Succès : {nl['id']}")
                
        except Exception as e:
            print(f"❌ Erreur sur ce mail : {e}")

    # Sauvegarde finale du manifest
    with open('manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
else:
    print("Nouveaux mails HugoDécrypte introuvables.")
