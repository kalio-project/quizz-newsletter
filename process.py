import os, imaplib, email, json, re, requests, time
from datetime import datetime
from email.utils import parsedate_to_datetime
from email.header import decode_header
from google import genai

# CONFIGURATION EXACTE SELON TON TABLEAU
MODEL_NAME = "gemini-2.5-flash" 
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

THEMES = ["POLITIQUE FR", "INTERNATIONAL", "ÉCONOMIE", "SOCIÉTÉ", "ENVIRONNEMENT", "TECH / SCIENCE", "SANTÉ", "CULTURE", "SPORT", "JUSTICE"]

def clean_subject(subject):
    try:
        dh = decode_header(subject)
        return ''.join([str(t[0].decode(t[1] or 'utf-8') if isinstance(t[0], bytes) else t[0]) for t in dh])
    except: return str(subject)

def clean_html(html):
    # Ton nettoyage HTML qui fonctionnait parfaitement
    if "Ouvrir dans le navigateur" in html: html = html.split("Ouvrir dans le navigateur")[-1]
    for r in ["Vous avez aimé cette newsletter", "Cette édition vous a plu", "Suivez-nous"]:
        if r in html: html = html.split(r)[0]
    html = re.sub(r'<style[^>]*>.*?</style>|<script[^>]*>.*?</script>', '', html, flags=re.DOTALL|re.IGNORECASE)
    return html.strip()

def process():
    print(f"🚀 Connexion avec le modèle {MODEL_NAME}...")
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(os.environ.get("EMAIL_USER"), os.environ.get("EMAIL_PASS"))
    mail.select("HUGO")

    _, data = mail.search(None, '(FROM "hugodecrypte@kessel.media")')
    ids = data[0].split()
    
    manifest_path = 'manifest.json'
    if os.path.exists(manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as f: manifest = json.load(f)
    else: manifest = []

    for e_id in ids[-3:]: # On traite les 3 derniers
        _, msg_data = mail.fetch(e_id, '(RFC822)')
        msg = email.message_from_bytes(msg_data[0][1])
        titre = clean_subject(msg['subject'])
        date_obj = parsedate_to_datetime(msg['Date'])
        folder_name = date_obj.strftime("%Y-%m-%d")
        path = f"archives/{folder_name}"

        if any(m['folder'] == path for m in manifest):
            print(f"⏩ Déjà dans l'index : {titre}")
            continue 

        print(f"📂 Traitement : {titre}")
        os.makedirs(f"{path}/images", exist_ok=True)

        body = ""
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                body = part.get_payload(decode=True).decode(errors='ignore')
        
        body = clean_html(body)
        urls = re.findall(r'src="([^"]+)"', body)
        img_couv = ""
        
        print(f"📸 Récupération des images...")
        for i, url in enumerate(urls[:15]):
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    img_name = f"img_{i}.jpg"
                    with open(f"{path}/images/{img_name}", 'wb') as f: f.write(r.content)
                    local_url = f"{path}/images/{img_name}"
                    body = body.replace(url, local_url)
                    if not img_couv and ("kessel" in url or "googleusercontent" in url): 
                        img_couv = local_url
            except: continue

        with open(f"{path}/contenu.html", "w", encoding="utf-8") as f: f.write(body)

        # IA - GÉNÉRATION DU QUIZ
        print(f"🤖 Appel à {MODEL_NAME}...")
        # PAUSE DE SÉCURITÉ (RPM)
        time.sleep(15) 
        
        text_only = re.sub('<[^<]+?>', '', body)[:8000]
        prompt = f"Contenu: {text_only}. Génère 10 questions (4 choix). Thèmes: {THEMES}. Réponds UNIQUEMENT en JSON: {{'questions': [{{'q':'','options':[],'correct':0,'explication':'','theme':''}}]}}"
        
        try:
            res = client.models.generate_content(model=MODEL_NAME, contents=prompt)
            json_match = re.search(r'\{.*\}', res.text, re.DOTALL)
            if json_match:
                quiz = json.loads(json_match.group())
                metadata = {
                    "titre": titre,
                    "date": date_obj.strftime("%d/%m/%Y"),
                    "img": img_couv,
                    "questions": quiz['questions']
                }
                with open(f"{path}/metadata.json", "w", encoding="utf-8") as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
                
                manifest.append({
                    "folder": path, 
                    "titre": titre, 
                    "date": metadata['date'], 
                    "img": img_couv
                })
                print(f"✨ Succès pour : {titre}")
        except Exception as e:
            print(f"❌ Erreur IA : {e}")

    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    
    print("🏁 Script terminé.")
    mail.logout()

if __name__ == "__main__": process()
