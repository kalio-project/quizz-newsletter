import os, imaplib, email, json, re
from google import genai
from email.utils import parsedate_to_datetime
from email.header import decode_header

# 1. CONFIGURATION DU CLIENT GEMINI
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def clean_html_to_text(raw_html):
    """Nettoie le HTML lourd pour l'IA."""
    clean = re.sub(r'<(style|script|head|meta|link).*?>.*?</\1>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r'<.*?>', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean[:15000]

def get_newsletter():
    """Récupère les mails d'HugoDécrypte."""
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        mail.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASSWORD"])
    except Exception as e:
        print(f"❌ Erreur Gmail : {e}")
        return []

    mail.select("inbox")
    AUTORISES = ["hugodecrypte@kessel.media", "hugo@hugodecrypte.com", "qcm.newsletter@gmail.com"]
    
    status, messages = mail.search(None, 'ALL')
    results = []
    ids = messages[0].split()
    
    print(f"🔎 {len(ids)} mails trouvés. Analyse des 15 derniers...")

    for m_id in ids[-15:]:
        res, msg_data = mail.fetch(m_id, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        
        sender_raw = str(msg.get("From")).lower()
        sender_match = re.findall(r'[\w\.-]+@[\w\.-]+', sender_raw)
        sender = sender_match[0] if sender_match else sender_raw

        subject_parts = decode_header(msg["Subject"])
        subject = "".join([part.decode(enc or 'utf-8') if isinstance(part, bytes) else part for part, enc in subject_parts])

        if any(addr.lower() in sender for addr in AUTORISES):
            dt = parsedate_to_datetime(msg.get("Date"))
            
            html_content = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        html_content = part.get_payload(decode=True).decode(errors='ignore')
            else:
                html_content = msg.get_payload(decode=True).decode(errors='ignore')
                
            if html_content:
                text_for_ia = clean_html_to_text(html_content)
                safe_title = re.sub(r'[^a-z0-9]', '', subject.lower())[:10]
                results.append({
                    "subject": subject, 
                    "clean_text": text_for_ia,
                    "date": dt.strftime("%d %b %Y"),
                    "id_unique": f"{dt.strftime('%Y%m%d')}-{safe_title}"
                })
    mail.logout()
    return results

# --- LOGIQUE PRINCIPALE ---
newsletters = get_newsletter()

if newsletters:
    try:
        with open('manifest.json', 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except:
        manifest = []

    deja_traites = [item.get("titre_original", "") for item in manifest]
    
    for nl in newsletters:
        if nl["subject"] in deja_traites:
            print(f"⏩ Déjà traité : {nl['subject']}")
            continue

        print(f"🤖 IA en cours (Gemini 2.5 Flash) sur : {nl['subject'][:30]}...")
        
        prompt = """Tu es un expert. Analyse la newsletter et génère en JSON STRICT :
        - titre: un titre accrocheur.
        - image: URL src trouvée ou chaîne vide.
        - theme: un seul mot (Politique, Économie, Technologie, Écologie, Société, Culture, Sport, Géopolitique, Science ou Insolite).
        - contenu_html: résumé avec balises <p>, <b>, <ul>, <li>.
        - questions: 10 QCM avec q, options, correct (0-3), explication.
        JSON UNIQUEMENT."""
        
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt + "\n\nCONTENU :\n" + nl['clean_text']
            )
            
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                
                # SÉCURITÉ : On gère les majuscules/minuscules des clés JSON
                final_titre = data.get('titre') or data.get('Titre') or "Sans titre"
                final_theme = data.get('theme') or data.get('Theme') or data.get('Thème') or "Actu"
                
                file_name = f"quiz-{nl['id_unique']}.json"
                os.makedirs('data', exist_ok=True)
                with open(f"data/{file_name}", 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False)
                
                manifest.append({
                    "date": nl['date'],
                    "file": f"data/{file_name}",
                    "titre": final_titre,
                    "titre_original": nl['subject'],
                    "image": data.get('image') or data.get('Image') or 'https://images.unsplash.com/photo-1504711434969-e33886168f5c',
                    "theme": final_theme
                })
                print(f"   💾 Fichier créé : {file_name}")
        except Exception as e:
            print(f"❌ Erreur IA détaillée : {e}")

    with open('manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("✅ Terminé !")
else:
    print("📢 Rien de nouveau à traiter.")
