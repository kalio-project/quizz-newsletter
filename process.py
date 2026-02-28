import os, imaplib, email, json, re, time
import google.generativeai as genai  # On revient à l'ancienne bibliothèque stable
from bs4 import BeautifulSoup
from datetime import datetime
from email.header import decode_header

# --- CONFIGURATION ---
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash') # Ce nom fonctionne avec cette lib

SOURCE_FOLDER = "newsletters_html"
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")

def clean_html_for_ia(raw_html):
    soup = BeautifulSoup(raw_html, 'html.parser')
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return ' '.join(soup.get_text(separator=' ').split())[:10000]

def fetch_emails():
    if not EMAIL_USER or not EMAIL_PASSWORD:
        return []
    newsletters = []
    try:
        print(f"📧 Connexion à Gmail...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(EMAIL_USER, EMAIL_PASSWORD)
        mail.select("HUGO")
        status, messages = mail.search(None, 'UNSEEN')
        if status == "OK" and messages[0]:
            for m_id in messages[0].split():
                res, data = mail.fetch(m_id, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])
                subject = decode_header(msg["Subject"])[0][0]
                if isinstance(subject, bytes): subject = subject.decode(errors='ignore')
                
                html_content = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/html":
                            html_content = part.get_payload(decode=True).decode(errors='ignore')
                else:
                    html_content = msg.get_payload(decode=True).decode(errors='ignore')
                
                if html_content:
                    newsletters.append({"id": f"mail-{m_id.decode()}", "html": html_content, "title": subject})
        mail.logout()
    except Exception as e:
        print(f"❌ Gmail : {e}")
    return newsletters

def run():
    if not os.path.exists('data'): os.makedirs('data')
    try:
        with open('manifest.json', 'r', encoding='utf-8') as f: manifest = json.load(f)
    except: manifest = []
    
    deja_vus = [m.get("titre_original") for m in manifest]
    sources = fetch_emails()
    
    if os.path.exists(SOURCE_FOLDER):
        for f in os.listdir(SOURCE_FOLDER):
            if f.lower().endswith(('.htm', '.html')) and f not in deja_vus:
                with open(os.path.join(SOURCE_FOLDER, f), 'r', encoding='utf-8') as file:
                    sources.append({"id": f, "html": file.read(), "title": f})

    if not sources:
        print("✅ Tout est à jour.")
        return

    item = sources[0]
    print(f"🤖 Analyse de : {item['title']}")
    texte_ia = clean_html_for_ia(item["html"])
    
    prompt = """Tu es un expert en quiz. Génère un quiz JSON de 10 questions sur le texte fourni.
    Réponds UNIQUEMENT avec le JSON, pas de texte avant ou après.
    Structure : {"theme_global": "", "titre": "", "questions": [{"q": "", "options": ["", "", "", ""], "correct": 0, "explication": ""}]}"""

    try:
        # La syntaxe de l'ancienne lib est différente
        response = model.generate_content(f"{prompt}\n\nTexte :\n{texte_ia}")
        
        json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if json_match:
            quiz_data = json.loads(json_match.group())
            # ON GARDE BIEN LE HTML COMPLET ICI
            quiz_data['html_affichage'] = item["html"] 
            
            quiz_id = datetime.now().strftime("%Y%m%d-%H%M")
            file_name = f"quiz-{quiz_id}.json"
            with open(f"data/{file_name}", 'w', encoding='utf-8') as f:
                json.dump(quiz_data, f, ensure_ascii=False, indent=2)

            manifest.append({
                "date": datetime.now().strftime("%d %b %Y"),
                "file": f"data/{file_name}",
                "titre": quiz_data.get('titre', item['title']),
                "titre_original": item["id"],
                "theme": quiz_data.get('theme_global', 'ACTU')
            })
            with open('manifest.json', 'w', encoding='utf-8') as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            
            print(f"🚀 Succès ! Fichier data/{file_name} créé.")
    except Exception as e:
        print(f"💥 Erreur IA : {e}")

if __name__ == "__main__":
    run()
