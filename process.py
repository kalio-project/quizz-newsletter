import os, imaplib, email, json, re, requests
from datetime import datetime
from email.utils import parsedate_to_datetime
from google import genai

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
THEMES = ["POLITIQUE FR", "INTERNATIONAL", "ÉCONOMIE", "SOCIÉTÉ", "ENVIRONNEMENT", "TECH / SCIENCE", "SANTÉ", "CULTURE", "SPORT", "JUSTICE"]

def clean_html(html):
    if "Ouvrir dans le navigateur" in html: html = html.split("Ouvrir dans le navigateur")[-1]
    for r in ["Vous avez aimé cette newsletter", "Cette édition vous a plu", "Suivez-nous"]:
        if r in html: html = html.split(r)[0]
    html = re.sub(r'<style[^>]*>.*?</style>|<script[^>]*>.*?</script>', '', html, flags=re.DOTALL|re.IGNORECASE)
    return html.strip()

def download_img(url, folder, name):
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            with open(os.path.join(folder, name), 'wb') as f: f.write(r.content)
            return True
    except: return False
    return False

def process():
    print("🚀 Démarrage du script...")
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(os.environ.get("EMAIL_USER"), os.environ.get("EMAIL_PASS"))
    mail.select("HUGO")

    _, data = mail.search(None, '(FROM "hugodecrypte@kessel.media")')
    ids = data[0].split()
    
    # Charger ou créer le manifest
    manifest_path = 'manifest.json'
    if os.path.exists(manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as f: manifest = json.load(f)
    else: manifest = []

    for e_id in ids[-3:]:
        _, msg_data = mail.fetch(e_id, '(RFC822)')
        msg = email.message_from_bytes(msg_data[0][1])
        titre = msg['subject']
        date_obj = parsedate_to_datetime(msg['Date'])
        folder_name = date_obj.strftime("%Y-%m-%d")
        path = f"archives/{folder_name}"

        # On vérifie si cette édition est DÉJÀ dans le manifest
        if any(m['folder'] == path for m in manifest):
            print(f"⏩ Déjà traité : {titre}")
            continue 

        print(f"📂 Traitement de : {titre}...")
        os.makedirs(f"{path}/images", exist_ok=True)

        body = ""
        for part in msg.walk():
            if part.get_content_type() == "text/html": body = part.get_payload(decode=True).decode(errors='ignore')
        
        body = clean_html(body)
        urls = re.findall(r'src="([^"]+)"', body)
        img_couv = ""
        for i, url in enumerate(urls):
            img_name = f"img_{i}.jpg"
            if download_img(url, f"{path}/images", img_name):
                local_url = f"{path}/images/{img_name}"
                body = body.replace(url, local_url)
                if not img_couv and ("kessel" in url or "googleusercontent" in url): 
                    img_couv = local_url

        with open(f"{path}/contenu.html", "w", encoding="utf-8") as f: f.write(body)

        # IA - GÉNÉRATION DU QUIZ
        print(f"🤖 Appel à Gemini pour {titre}...")
        text_only = re.sub('<[^<]+?>', '', body)[:8000]
        prompt = f"Contenu: {text_only}. Génère 10 questions (4 choix). Thèmes: {THEMES}. Réponds UNIQUEMENT en JSON: {{'questions': [{{'q':'','options':[],'correct':0,'explication':'','theme':''}}]}}"
        
        try:
            res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
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
                
                # AJOUT AU MANIFEST (C'est ça qui remplit l'index !)
                manifest.append({
                    "folder": path,
                    "titre": titre,
                    "date": metadata['date'],
                    "img": img_couv
                })
                print(f"✨ Quiz et Metadata créés !")
            else:
                print("❌ Gemini n'a pas renvoyé un JSON valide.")
        except Exception as e:
            print(f"❌ Erreur lors de l'appel IA : {e}")

    # Sauvegarde finale du manifest
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    
    print("✅ Fin du script.")
    mail.logout()

if __name__ == "__main__": process()
