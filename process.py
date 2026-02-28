import os, imaplib, email, json, re, html, requests
from google import genai
from email.utils import parsedate_to_datetime
from datetime import datetime

# --- CONFIGURATION ---
# On utilise os.environ pour la sécurité sur GitHub
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS") 

client = genai.Client(api_key=GEMINI_KEY)

def download_image(url, file_id):
    """Télécharge l'image physiquement pour Github Pages."""
    if not url: return "https://images.unsplash.com/photo-1504711432869-efd5971ee142?w=800"
    if not os.path.exists('images'): os.makedirs('images')
    
    path = f"images/vignette-{file_id}.jpg"
    if os.path.exists(path): return path

    try:
        clean_url = url.replace('&amp;', '&')
        res = requests.get(clean_url, timeout=10)
        if res.status_code == 200:
            with open(path, 'wb') as f:
                f.write(res.content)
            return path
    except: pass
    return "https://images.unsplash.com/photo-1504711432869-efd5971ee142?w=800"

def clean_html_content(raw_html):
    """Nettoyage radical du HTML d'Hugo pour un affichage propre."""
    # 1. On garde le coeur de l'article
    if "Ouvrir dans le navigateur" in raw_html:
        raw_html = raw_html.split("Ouvrir dans le navigateur")[-1]
    
    fin_nl = ["Vous avez aimé cette newsletter ?", "Cette édition vous a plu ?", "Partager cette édition"]
    for phrase in fin_nl:
        if phrase in raw_html:
            raw_html = raw_html.split(phrase)[0]
            break

    # 2. Suppression des styles et éléments invisibles (anti-blanc)
    raw_html = re.sub(r'<style[^>]*>.*?</style>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
    raw_html = re.sub(r'<svg[^>]*>.*?</svg>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
    raw_html = re.sub(r'<div[^>]*class="preheader"[^>]*>.*?</div>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
    
    return raw_html.strip()

def process_emails():
    print(f"Connexion IMAP pour {EMAIL_USER}...")
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_USER, EMAIL_PASS)
    
    # Sélection du dossier HUGO
    status, _ = mail.select("HUGO")
    if status != 'OK':
        print("Dossier HUGO introuvable, utilisation de INBOX")
        mail.select("INBOX")

    # Recherche de l'expéditeur précis
    status, messages = mail.search(None, '(FROM "hugodecrypte@kessel.media")')
    email_ids = messages[0].split()

    # Chargement du Manifest
    manifest = []
    if os.path.exists('manifest.json'):
        with open('manifest.json', 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    
    deja_vus = [m.get('titre_original') for m in manifest]

    # On traite les 10 plus récents
    for e_id in email_ids[-10:]:
        e_id_str = e_id.decode()
        _, msg_data = mail.fetch(e_id, '(RFC822)')
        
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                subject = msg['subject']
                
                if subject in deja_vus: continue
                print(f"Nouveau contenu détecté : {subject}")

                # Extraction du HTML
                html_body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/html":
                            html_body = part.get_payload(decode=True).decode()
                else:
                    html_body = msg.get_payload(decode=True).decode()

                display_html = clean_html_content(html_body)

                # --- IA GEMINI (10 Questions + Thème) ---
                prompt = f"""
                Génère un quiz de EXACTEMENT 10 questions sur cette newsletter.
                Choisis le theme_global selon le sujet principal du quiz.
                
                Retourne UNIQUEMENT ce JSON :
                {{
                  "titre": "Titre du Quiz",
                  "theme_global": "GÉOPOLITIQUE, SOCIÉTÉ, ÉCONOMIE, PLANÈTE, TECH, CULTURE ou SPORT",
                  "questions": [
                    {{ "q": "Question", "options": ["A", "B", "C"], "correct": 0, "explication": "..." }}
                  ]
                }}
                Texte : {html_body[:7000]}
                """
                
                try:
                    response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                    data = json.loads(re.search(r'\{.*\}', response.text, re.DOTALL).group())
                    
                    data['html_affichage'] = display_html
                    
                    # Recherche d'image (on évite les icônes)
                    img_urls = re.findall(r'src="([^"]+\.(?:jpg|png|jpeg)[^"]*)"', html_body)
                    img_src = ""
                    for url in img_urls:
                        if all(x not in url.lower() for x in ["logo", "avatar", "icon", "heart", "open"]):
                            img_src = url
                            break
                    
                    local_img = download_image(img_src, e_id_str)
                    data['image'] = local_img

                    # Sauvegarde JSON
                    file_path = f"data/quiz-{e_id_str}.json"
                    os.makedirs('data', exist_ok=True)
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)

                    # Manifest
                    manifest.append({
                        "date": datetime.now().strftime("%d/%m/%Y"),
                        "file": file_path,
                        "titre": data['titre'],
                        "titre_original": subject,
                        "image": local_img,
                        "theme": data['theme_global']
                    })
                except Exception as e:
                    print(f"Erreur IA : {e}")

    # Sauvegarde Manifest
    with open('manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    
    mail.logout()
    print("Mise à jour terminée.")

if __name__ == "__main__":
    process_emails()
