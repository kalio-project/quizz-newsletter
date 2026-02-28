import os, imaplib, email, json, re, time
from google import genai
from bs4 import BeautifulSoup
from datetime import datetime
from email.header import decode_header

# --- CONFIGURATION ---
# La bibliothèque google-genai récupère GEMINI_API_KEY automatiquement via l'environnement
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

SOURCE_FOLDER = "newsletters_html"
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")

def clean_html_for_ia(raw_html):
    """Nettoie le HTML pour n'envoyer que le texte utile à l'IA"""
    soup = BeautifulSoup(raw_html, 'html.parser')
    # Supprime les scripts et les balises de style
    for tag in soup(["script", "style"]):
        tag.decompose()
    # Récupère le texte propre
    text = ' '.join(soup.get_text(separator=' ').split())
    return text

def fetch_emails():
    """Se connecte à Gmail et récupère les mails non lus du libellé HUGO"""
    if not EMAIL_USER or not EMAIL_PASSWORD:
        print("⚠️ Variables EMAIL_USER ou EMAIL_PASSWORD manquantes.")
        return []
    
    newsletters = []
    try:
        print(f"📧 Connexion à Gmail ({EMAIL_USER})...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(EMAIL_USER, EMAIL_PASSWORD)
        mail.select("HUGO") # Assure-toi que ce libellé existe exactement ainsi
        
        status, messages = mail.search(None, 'UNSEEN')
        if status != "OK" or not messages[0]:
            print("✅ Aucun nouveau mail non lu dans HUGO.")
            mail.logout()
            return []

        for m_id in messages[0].split():
            res, data = mail.fetch(m_id, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])
            
            # Décoder le sujet du mail
            subject_parts = decode_header(msg["Subject"])
            subject = "".join([
                part.decode(enc or 'utf-8') if isinstance(part, bytes) else part 
                for part, enc in subject_parts
            ])
            
            body_html = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        body_html = part.get_payload(decode=True).decode(errors='ignore')
            else:
                body_html = msg.get_payload(decode=True).decode(errors='ignore')
            
            if body_html:
                newsletters.append({
                    "id": f"mail-{m_id.decode()}", 
                    "html": body_html, 
                    "title": subject
                })
        
        mail.logout()
    except Exception as e:
        print(f"❌ Erreur lors de la récupération Gmail : {e}")
    return newsletters

def run():
    # Création du dossier data s'il n'existe pas
    if not os.path.exists('data'):
        os.makedirs('data')
        
    # Chargement du manifest
    try:
        with open('manifest.json', 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except:
        manifest = []
    
    deja_vus = [m.get("titre_original") for m in manifest]

    # 1. RÉCUPÉRATION DES SOURCES (Priorité Email)
    sources = fetch_emails()
    
    # 2. AJOUT DES FICHIERS LOCAUX (Dossier newsletters_html)
    if os.path.exists(SOURCE_FOLDER):
        for f in os.listdir(SOURCE_FOLDER):
            if f.lower().endswith(('.htm', '.html')) and f not in deja_vus:
                with open(os.path.join(SOURCE_FOLDER, f), 'r', encoding='utf-8') as file:
                    sources.append({"id": f, "html": file.read(), "title": f})

    if not sources:
        print("🏁 Fin : Rien à traiter.")
        return

    # On traite uniquement le premier élément non vu
    item = sources[0]
    if item["id"] in deja_vus:
        print(f"⏩ Déjà traité : {item['title']}")
        return

    print(f"🤖 Analyse IA en cours pour : {item['title']}")
    texte_ia = clean_html_for_ia(item["html"])
    
    prompt = (
        "Génère un quiz JSON de 10 questions basé sur le texte fourni. "
        "Réponds uniquement au format JSON suivant : "
        "{\"theme_global\": \"\", \"titre\": \"\", \"questions\": "
        "[{\"q\": \"\", \"options\": [\"\", \"\", \"\", \"\"], \"correct\": 0, \"explication\": \"\"}]}"
    )

    # --- GÉNÉRATION IA AVEC RETRY ---
    # On teste le modèle 2.0 Flash (stable)
    model_name = 'gemini-2.0-flash'
    
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=model_name, 
                contents=f"{prompt}\n\nTexte source :\n{texte_ia}"
            )
            
            # Extraction du JSON dans la réponse
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if json_match:
                quiz_data = json.loads(json_match.group())
                
                # On injecte le HTML d'origine pour l'affichage sur ton site
                quiz_data['html_affichage'] = item["html"]
                
                # Sauvegarde du fichier JSON
                quiz_id = datetime.now().strftime("%Y%m%d-%H%M")
                file_name = f"quiz-{quiz_id}.json"
                dest_path = f"data/{file_name}"
                
                with open(dest_path, 'w', encoding='utf-8') as f:
                    json.dump(quiz_data, f, ensure_ascii=False, indent=2)

                # Mise à jour du manifest
                manifest.append({
                    "date": datetime.now().strftime("%d %b %Y"),
                    "file": dest_path,
                    "titre": quiz_data.get('titre', item['title']),
                    "titre_original": item["id"],
                    "theme": quiz_data.get('theme_global', 'ACTU')
                })
                
                with open('manifest.json', 'w', encoding='utf-8') as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=2)
                
                print(f"✨ Succès ! Quiz généré : {file_name}")
                return # On sort après avoir réussi

        except Exception as e:
            print(f"⚠️ Essai {attempt+1} échoué : {e}")
            if attempt == 0:
                print("Nouvelle tentative dans 10 secondes avec gemini-1.5-flash-latest...")
                model_name = 'gemini-1.5-flash-latest' # Repli sur le 1.5 si le 2.0 bloque
                time.sleep(10)

if __name__ == "__main__":
    run()
