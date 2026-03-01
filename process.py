import os, imaplib, email, json, re, requests
from google import genai
from datetime import datetime

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
THEMES = ["POLITIQUE EN FRANCE", "POLITIQUE INTERNATIONALE ET CONFLITS", "SOCIÉTÉ / FAITS DE SOCIÉTÉ", "ÉCONOMIE ET EMPLOI", "ENVIRONNEMENT ET CLIMAT", "SCIENCE, SANTÉ ET TECHNOLOGIE", "CULTURE ET MÉDIAS", "SPORT"]

def clean_hugo(html):
    if "Ouvrir dans le navigateur" in html: html = html.split("Ouvrir dans le navigateur")[-1]
    for p in ["Vous avez aimé cette newsletter ?", "Cette édition vous a plu ?"]:
        if p in html: html = html.split(p)[0]
    html = re.sub(r'<style[^>]*>.*?</style>|<svg[^>]*>.*?</svg>', '', html, flags=re.DOTALL|re.IGNORECASE)
    return html.strip()

def process():
    user, pw = os.environ.get("EMAIL_USER"), os.environ.get("EMAIL_PASS")
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(user, pw)
    if mail.select("HUGO")[0] != 'OK': mail.select("INBOX")
    
    _, data = mail.search(None, '(FROM "hugodecrypte@kessel.media")')
    ids = data[0].split()
    manifest = json.load(open('manifest.json')) if os.path.exists('manifest.json') else []

    for e_id in ids[-3:]:
        _, msg_data = mail.fetch(e_id, '(RFC822)')
        msg = email.message_from_bytes(msg_data[0][1])
        if any(m['titre'] == msg['subject'] for m in manifest): continue

        body = ""
        for part in msg.walk():
            if part.get_content_type() == "text/html": body = part.get_payload(decode=True).decode(errors='ignore')

        prompt = f"Newsletter: {body[:8000]}. Génère 10 questions (4 choix). Pour chaque question, attribue un thème parmi {THEMES}. Réponds UNIQUEMENT en JSON: {{'questions': [{{'q':'','options':[],'correct':0,'explication':'','theme':''}}]}}"
        
        try:
            res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            quiz = json.loads(re.search(r'\{.*\}', res.text, re.DOTALL).group())
            quiz['html_article'] = clean_hugo(body)
            quiz['titre'] = msg['subject']
            
            img = next((u for u in re.findall(r'src="([^"]+)"', body) if "kessel" in u and "logo" not in u.lower()), "")
            
            path = f"data/q-{e_id.decode()}.json"
            os.makedirs('data', exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f: json.dump(quiz, f, ensure_ascii=False)
            manifest.append({"date": datetime.now().strftime("%d/%m/%Y"), "file": path, "titre": msg['subject'], "img": img})
        except: pass

    with open('manifest.json', 'w', encoding='utf-8') as f: json.dump(manifest, f, indent=2, ensure_ascii=False)
    mail.logout()

if __name__ == "__main__": process()
