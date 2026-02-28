import os, imaplib, email, json, re, html
from google import genai
from email.utils import parsedate_to_datetime
from email.header import decode_header

# 1. CONNEXION GEMINI
try:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
except Exception as e:
    print(f"❌ Erreur Clé API : {e}")

def get_newsletter():
    print("Step 1: Connexion Gmail...")
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        mail.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASSWORD"])
    except Exception as e:
        print(f"❌ Erreur Login Gmail : {e}")
        return []
    
    mail.select("inbox")
    AUTORISES = ["hugodecrypte@kessel.media", "hugo@hugodecrypte.com", "qcm.newsletter@gmail.com"]
    status, messages = mail.search(None, 'ALL')
    ids = messages[0].split()
    results = []

    print(f"Step 2: Analyse des {len(ids[-10:])} derniers mails...")
    for m_id in ids[-10:]:
        res, data = mail.fetch(m_id, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])
        sender = str(msg.get("From")).lower()

        if any(addr.lower() in sender for addr in AUTORISES):
            subject_parts = decode_header(msg["Subject"])
            subject = "".join([part.decode(enc or 'utf-8') if isinstance(part, bytes) else part for part, enc in subject_parts])
            print(f"📩 Mail trouvé : {subject}")
            
            body_html = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        body_html = part.get_payload(decode=True).decode(errors='ignore')
            else:
                body_html = msg.get_payload(decode=True).decode(errors='ignore')
            
            if body_html:
                # On nettoie le texte pour l'IA (on enlève les balises pour ne pas saturer l'IA)
                text_clean = re.sub(r'<(style|script|head).*?>.*?</\1>', '', body_html, flags=re.DOTALL | re.IGNORECASE)
                text_clean = re.sub(r'<.*?>', ' ', text_clean)
                text_clean = html.unescape(text_clean)
                
                results.append({
                    "subject": subject,
                    "full_html": body_html,
                    "text_for_ia": text_clean,
                    "date": parsedate_to_datetime(msg.get("Date")).strftime("%d %b %Y"),
                    "id": f"{parsedate_to_datetime(msg.get('Date')).strftime('%Y%m%d')}-{re.sub(r'[^a-z]', '', subject.lower())[:10]}"
                })
    mail.logout()
    return results

# --- LOGIQUE DE GENERATION ---
newsletters = get_newsletter()

if newsletters:
    try:
        with open('manifest.json', 'r', encoding='utf-8') as f: manifest = json.load(f)
    except: manifest = []
    
    deja_vus = [m.get("titre_original") for m in manifest]

    for nl in newsletters:
        if nl["subject"] in deja_vus:
            print(f"⏩ Déjà fait : {nl['subject']}")
            continue

        print(f"🤖 Appel à Gemini pour : {nl['subject']}...")
        prompt = "Génère un JSON STRICT avec : theme (un mot), titre (court), questions (10 QCM avec q, options, correct (0-3), explication)."
        
        try:
            # On limite le texte envoyé à l'IA à 10 000 caractères pour éviter les crashs
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=f"{prompt}\n\nTEXTE :\n{nl['text_for_ia'][:10000]}"
            )
            
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                
                # ON INJECTE LE HTML BRUT ICI
                data['contenu_html'] = nl['full_html']
                
                # Image de preview
                img_url = ""
                img_match = re.search(r'<img.*?src="(.*?)"', nl['full_html'])
                if img_match: img_url = img_match.group(1)

                quiz_path = f"data/quiz-{nl['id']}.json"
                os.makedirs('data', exist_ok=True)
                with open(quiz_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False)
                
                manifest.append({
                    "date": nl["date"],
                    "file": quiz_path,
                    "titre": data.get("titre", nl["subject"]),
                    "titre_original": nl["subject"],
                    "image": img_url or "https://images.unsplash.com/photo-1504711434969-e33886168f5c",
                    "theme": data.get("theme", "Actu")
                })
                print(f"✅ Quiz crée : {quiz_path}")
        except Exception as e:
            print(f"❌ Erreur IA sur ce mail : {e}")

    with open('manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("🏁 Fin du script.")
else:
    print("ℹ️ Aucun mail HugoDécrypte trouvé.")
