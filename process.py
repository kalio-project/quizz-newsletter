import os, imaplib, email, json, re, html, requests
from google import genai
from email.utils import parsedate_to_datetime
from email.header import decode_header
from datetime import datetime

# Configuration Client Gemini
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def download_image(url, file_id):
    """Télécharge l'image physiquement dans le dossier images/ pour Github."""
    if not os.path.exists('images'): 
        os.makedirs('images')
    
    path = f"images/vignette-{file_id}.jpg"
    if os.path.exists(path): return path # Évite les doublons

    try:
        clean_url = url.replace('&amp;', '&')
        res = requests.get(clean_url, timeout=10)
        if res.status_code == 200:
            with open(path, 'wb') as f:
                f.write(res.content)
            return path
    except Exception as e:
        print(f"Erreur téléchargement image: {e}")
    
    # Image de secours si échec
    return "https://images.unsplash.com/photo-1504711432869-efd5971ee142?w=800"

def get_newsletter():
    """Se connecte à Gmail et récupère les 10 dernières newsletters autorisées."""
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        mail.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASSWORD"])
    except Exception as e:
        print(f"Erreur Login: {e}")
        return []
        
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
            else:
                body_html = msg.get_payload(decode=True).decode(errors='ignore')
            
            if body_html:
                # Texte pur pour l'IA
                text_only = re.sub(r'<(style|script).*?>.*?</\1>', '', body_html, flags=re.DOTALL | re.IGNORECASE)
                text_only = re.sub(r'<.*?>', ' ', text_only)
                
                results.append({
                    "subject": subject, 
                    "full_html": body_html, 
                    "text_only": html.unescape(text_only),
                    "date": dt.strftime("%d %b %Y"),
                    "id": f"{dt.strftime('%Y%m%d')}-{re.sub(r'[^a-z]', '', subject.lower())[:10]}"
                })
    mail.logout()
    return results

# --- DÉBUT DU TRAITEMENT ---
newsletters = get_newsletter()

if newsletters:
    try:
        with open('manifest.json', 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except:
        manifest = []
    
    deja_vus = [m.get("titre_original") for m in manifest]

    for nl in newsletters:
        if nl["subject"] in deja_vus:
            continue

        print(f"Traitement de : {nl['subject']}")

        # Prompt avec Thèmes Fixes
        prompt = """
        Analyse cette newsletter. Génère un JSON strictement structuré :
        1. "titre": (Emoji + titre percutant)
        2. "theme_global": (Choisis parmi : GÉOPOLITIQUE, SOCIÉTÉ, ÉCONOMIE, PLANÈTE, TECH, CULTURE, SPORT)
        3. "questions": Liste de 10 objets QCM contenant:
           - q, options (4 choix), correct (index 0-3), explication
           - categorie: (Le thème de la question spécifique)
        """
        
        try:
            response = client.models.generate_content(
                model='gemini-2.0-flash', 
                contents=prompt + "\n\nTEXTE:\n" + nl['text_only'][:10000]
            )
            
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if match:
                data = json.loads(match.group())
                
                # --- NETTOYAGE DU HTML (Anti-Cœur et Anti-Header) ---
                html_clean = nl['full_html']
                if "Ouvrir dans le navigateur" in html_clean:
                    html_clean = html_clean.split("Ouvrir dans le navigateur")[-1]
                if "Vous avez aimé cette newsletter ?" in html_clean:
                    html_clean = html_clean.split("Vous avez aimé cette newsletter ?")[0]
                
                # Supprime les SVG (le cœur géant)
                html_clean = re.sub(r'<svg.*?</svg>', '', html_clean, flags=re.DOTALL)
                data['html_affichage'] = html_clean.strip()
                
                # --- EXTRACTION ET TÉLÉCHARGEMENT IMAGE ---
                img_urls = re.findall(r'<img.*?src="(.*?)"', nl['full_html'])
                img_url_source = ""
                for url in img_urls:
                    # Filtre pour éviter les logos, avatars et icônes
                    if all(x not in url.lower() for x in ["/o/", "googleusercontent", "logo", "avatar", "heart", "icon", "open"]):
                        img_url_source = url
                        break
                
                # On télécharge l'image pour Github
                image_locale = download_image(img_url_source, nl['id'])
                
                # Sauvegarde du fichier JSON individuel
                path = f"data/quiz-{nl['id']}.json"
                os.makedirs('data', exist_ok=True)
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                
                # Mise à jour du Manifest
                manifest.append({
                    "date": nl['date'], 
                    "file": path, 
                    "titre": data['titre'],
                    "titre_original": nl['subject'], 
                    "image": image_locale, 
                    "theme": data.get('theme_global', 'SOCIÉTÉ')
                })
                
        except Exception as e:
            print(f"Erreur lors de la génération IA pour {nl['subject']}: {e}")

    # Sauvegarde finale du Manifest
    with open('manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

print("Traitement terminé.")
