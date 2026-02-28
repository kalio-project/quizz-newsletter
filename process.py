import os, imaplib, email, json, re, html
from google import genai
from email.utils import parsedate_to_datetime
from email.header import decode_header

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def get_newsletter():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        mail.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASSWORD"])
    except: return []
    mail.select("inbox")
    AUTORISES = ["hugodecrypte@kessel.media", "hugo@hugodecrypte.com", "qcm.newsletter@gmail.com"]
    status, messages = mail.search(None, 'ALL')
    results = []
    ids = messages[0].split()

    for m_id in ids[-10:]:
        res, data = mail.fetch(m_id, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])
        sender = str(msg.get("From")).lower()

        if any(addr.lower() in sender for addr in AUTORISES):
            subject_parts = decode_header(msg["Subject"])
            subject = "".join([part.decode(enc or 'utf-8') if isinstance(part, bytes) else part for part, enc in subject_parts])
            dt = parsedate_to_datetime(msg.get("Date"))
            
            body_html = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        body_html = part.get_payload(decode=True).decode(errors='ignore')
            else: body_html = msg.get_payload(decode=True).decode(errors='ignore')
            
            if body_html:
                text_only = re.sub(r'<(style|script).*?>.*?</\1>', '', body_html, flags=re.DOTALL | re.IGNORECASE)
                text_only = re.sub(r'<.*?>', ' ', text_only)
                results.append({
                    "subject": subject, "full_html": body_html, "text_only": html.unescape(text_only),
                    "date": dt.strftime("%d %b %Y"),
                    "id": f"{dt.strftime('%Y%m%d')}-{re.sub(r'[^a-z]', '', subject.lower())[:10]}"
                })
    mail.logout()
    return results

newsletters = get_newsletter()
if newsletters:
    try:
        with open('manifest.json', 'r', encoding='utf-8') as f: manifest = json.load(f)
    except: manifest = []
    
    deja_vus = [m.get("titre_original") for m in manifest]

    for nl in newsletters:
        if nl["subject"] in deja_vus: continue

        prompt = "Génère un JSON : 1. theme (Politique, Sport, etc.), 2. titre (court), 3. questions (10 QCM avec q, options, correct 0-3, explication)."
        try:
            response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt + "\n\nTEXTE:\n" + nl['text_only'][:10000])
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if match:
                data = json.loads(match.group())
                data['contenu_html'] = nl['full_html'] # On garde le HTML original
                img_match = re.search(r'<img.*?src="(.*?)"', nl['full_html'])
                img_url = img_match.group(1) if img_match else ""
                
                path = f"data/quiz-{nl['id']}.json"
                os.makedirs('data', exist_ok=True)
                with open(path, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False)
                
                manifest.append({
                    "date": nl['date'], "file": path, "titre": data['titre'],
                    "titre_original": nl['subject'], "image": img_url, "theme": data['theme']
                })
        except Exception as e: print(f"Erreur: {e}")

    with open('manifest.json', 'w', encoding='utf-8') as f: json.dump(manifest, f, ensure_ascii=False, indent=2)
