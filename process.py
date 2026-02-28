import os, imaplib, email, json, re, time
from google import genai
from bs4 import BeautifulSoup
from datetime import datetime
from email.header import decode_header

# --- CONFIGURATION ---
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
SOURCE_FOLDER = "newsletters_html"
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")

def clean_html_for_ia(raw_html):
    """Extrait le texte pur pour que l'IA ne soit pas perturbée par les balises"""
    soup = BeautifulSoup(raw_html, 'html.parser')
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    # On garde tout le texte, mais on enlève les espaces inutiles
    return ' '.join(soup.get_text(separator=' ').split())

def fetch_emails():
    """Récupère les mails non lus dans le dossier HUGO"""
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
    
    # On ajoute aussi les fichiers locaux si présents
    if os.path.exists(SOURCE_FOLDER):
        for f in os.listdir(SOURCE_FOLDER):
            if f.lower().endswith(('.htm', '.html')) and f not in deja_vus:
                with open(os.path.join(SOURCE_FOLDER, f), 'r', encoding='utf-8') as file:
                    sources.append({"id": f, "html": file.read(), "title": f})

    if not sources:
        print("✅ Tout est à jour.")
        return

    item = sources[0]
    print(f"🤖 Traitement de : {item['title']}")
    
    # 1. Préparation des données
    texte_ia = clean_html_for_ia(item["html"])
    
    # 2. Demande à l'IA
    prompt = """Génère un quiz de 10 questions sur ce texte. 
    Tu DOIS répondre UNIQUEMENT avec un objet JSON structuré comme ceci:
    {
      "theme_global": "Thème court",
      "titre": "Titre du Quiz",
      "questions": [
        {
          "q": "La question ?",
          "options": ["A", "B", "C", "D"],
          "correct": 0,
          "explication": "Détails de la réponse"
        }
      ]
    }"""

    try:
        # On utilise gemini-1.5-flash-latest pour la stabilité quota gratuit
        response = client.models.generate_content(
            model='gemini-1.5-flash-latest', 
            contents=f"{prompt}\n\nTexte source :\n{texte_ia[:10000]}" # Limite à 10k pour le quota gratuit
        )
        
        json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if json_match:
            quiz_data = json.loads(json_match.group())
            
            # --- C'EST ICI QUE LA MAGIE OPÈRE ---
            # On stocke le HTML COMPLET d'Hugo pour l'affichage site
            quiz_data['html_affichage'] = item["html"] 
            
            # Sauvegarde
            quiz_id = datetime.now().strftime("%Y%m%d-%H%M")
            file_name = f"quiz-{quiz_id}.json"
            with open(f"data/{file_name}", 'w', encoding='utf-8') as f:
                json.dump(quiz_data, f, ensure_ascii=False, indent=2)

            # Manifest pour ta page d'accueil (index)
            manifest.append({
                "date": datetime.now().strftime("%d %b %Y"),
                "file": f"data/{file_name}",
                "titre": quiz_data.get('titre', item['title']),
                "titre_original": item["id"],
                "theme": quiz_data.get('theme_global', 'ACTU')
            })
            with open('manifest.json', 'w', encoding='utf-8') as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            
            print(f"🚀 Terminé ! Quiz créé et HTML sauvegardé.")
    except Exception as e:
        print(f"💥 Erreur : {e}")

if __name__ == "__main__":
    run()
