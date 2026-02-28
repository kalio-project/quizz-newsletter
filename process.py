import os, imaplib, email, json, re, requests
from google import genai
from datetime import datetime

# Config
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
THEMES = ["POLITIQUE EN FRANCE", "POLITIQUE INTERNATIONALE ET CONFLITS", "SOCIÉTÉ / FAITS DE SOCIÉTÉ", "ÉCONOMIE ET EMPLOI", "ENVIRONNEMENT ET CLIMAT", "SCIENCE, SANTÉ ET TECHNOLOGIE", "CULTURE ET MÉDIAS", "SPORT"]

def clean_hugo_html(raw_html):
    if "Ouvrir dans le navigateur" in raw_html:
        raw_html = raw_html.split("Ouvrir dans le navigateur")[-1]
    for p in ["Vous avez aimé cette newsletter ?", "Cette édition vous a plu ?"]:
        if p in raw_html: raw_html = raw_html.split(p)[0]
    # Nettoyage radical
    raw_html = re.sub(r'<style[^>]*>.*?</style>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
    raw_html = re.sub(r'<svg[^>]*>.*?</svg>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
    raw_html = re.sub(r'class="[^"]*preheader[^"]*"', 'style="display:none"', raw_html, flags=re.IGNORECASE)
    return raw_html.strip()

def process():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(os.environ.get("EMAIL_USER"), os.environ.get("EMAIL_PASS"))
    mail.select("HUGO") if mail.select("HUGO")[0] == 'OK' else mail.select("INBOX")
    
    _, data = mail.search(None, '(FROM "hugodecrypte@kessel.media")')
    ids = data[0].split()
    manifest = json.load(open('manifest.json', 'r')) if os.path.exists('manifest.json') else []

    for e_id in ids[-5:]: # On traite les 5 derniers
        _, msg_data = mail.fetch(e_id, '(RFC822)')
        msg = email.message_from_bytes(msg_data[0][1])
        if any(m['titre'] == msg['subject'] for m in manifest): continue

        body = ""
        for part in msg.walk():
            if part.get_content_type() == "text/html": body = part.get_payload(decode=True).decode(errors='ignore')

        prompt = f"Analyse cette newsletter. Crée 10 questions (4 choix). Pour CHAQUE question, choisis un thème parmi {THEMES}. Retourne UNIQUEMENT un JSON: {{'questions': [{{'q':'','options':[],'correct':0,'explication':'','theme':''}}]}}"
        
        try:
            res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            quiz_data = json.loads(re.search(r'\{.*\}', res.text, re.DOTALL).group())
            quiz_data['html_article'] = clean_hugo_html(body)
            quiz_data['titre'] = msg['subject']
            
            # Image
            imgs = re.findall(r'src="([^"]+)"', body)
            img_url = next((u for u in imgs if "kessel" in u and "logo" not in u.lower()), "")
            
            filename = f"data/q-{e_id.decode()}.json"
            os.makedirs('data', exist_ok=True)
            json.dump(quiz_data, open(filename, 'w', encoding='utf-8'), ensure_ascii=False)
            manifest.append({"date": datetime.now().strftime("%d/%m/%Y"), "file": filename, "titre": msg['subject'], "img": img_url})
        except: pass

    json.dump(manifest, open('manifest.json', 'w', encoding='utf-8'), indent=2)
    mail.logout()

if __name__ == "__main__": process()#!/usr/bin/env python3
import os
import json
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import google.genai as genai

# Configuration Gemini
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-2.0-flash-exp')

THEMES = [
    "POLITIQUE EN FRANCE", "POLITIQUE INTERNATIONALE ET CONFLITS", "SOCIÉTÉ / FAITS DE SOCIÉTÉ",
    "ÉCONOMIE ET EMPLOI", "ENVIRONNEMENT ET CLIMAT", "SCIENCE, SANTÉ ET TECHNOLOGIE",
    "CULTURE ET MÉDIAS", "SPORT"
]

def scrape_hugo_newsletters():
    """Scrape les 3 dernières newsletters Kessel"""
    url = "https://hugodecrypte.kessel.media/posts"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        posts = []
        articles = soup.find_all('article')[:3]
        for article in articles:
            link = article.find('a', href=True)
            title_elem = article.find(['h1', 'h2', 'h3'])
            date_elem = article.find('time') or article.find(class_=re.compile(r'date|time', re.I))
            
            if link and title_elem:
                href = link['href']
                full_url = href if href.startswith('http') else f"https://hugodecrypte.kessel.media{href}"
                posts.append({
                    'title': title_elem.get_text().strip()[:100],
                    'url': full_url,
                    'date': date_elem.get_text().strip() if date_elem else datetime.now().strftime('%Y-%m-%d')
                })
        return posts
    except Exception as e:
        print(f"Erreur scraping: {e}")
        return []

def clean_content(url):
    """Extrait contenu article"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Contenu principal
        content_selectors = ['article', '.content', '.post-content', '.article-body', 'main', '[role="main"]']
        content = None
        for selector in content_selectors:
            content = soup.select_one(selector)
            if content:
                break
        
        if not content:
            content = soup.body
        
        # Nettoie parasites
        for unwanted in content.find_all(['nav', 'aside', 'footer', 'header', '.comments', '[class*="ad"]']):
            unwanted.decompose()
        
        # Image
        img_selectors = ['.featured-image img', 'article img', 'img[src*="og:image"]', 'img']
        img = None
        for selector in img_selectors:
            img = content.select_one(selector)
            if img and img.get('src'):
                break
        
        image_url = 'https://via.placeholder.com/300x200/667eea/ffffff?text=ActuQuiz'
        if img and img.get('src'):
            src = img['src']
            if not src.startswith('http'):
                base_url = '/'.join(url.split('/')[:3])
                src = base_url + '/' + src.lstrip('/')
            image_url = src
        
        text = re.sub(r'\s+', ' ', content.get_text()).strip()[:5000]
        return text, image_url
    except Exception as e:
        print(f"Erreur clean_content: {e}")
        return "Contenu temporaire pour test", image_url

def generate_questions(content, title):
    """10 questions avec thèmes exacts"""
    prompt = f"""Article HugoDécrypte : "{title}"

Génère 10 questions QCM (collège/lycée) :

📋 FORMAT JSON STRICT (copie-colle) :
[
  {{"question":"Quelle est la bonne réponse?", "options":["A. Faux","B. Vrai","C. Option3","D. Option4"], "correct":1, "theme":"THÈME_EXACT", "explanation":"Explication détaillée"}}
]

✅ RÈGLES :
• 10 questions exactement
• Thèmes OBLIGATOIRES (1 seul par question) : {', '.join(THEMES)}
• 4 options A B C D
• correct : 0,1,2 ou 3
• Explications pédagogiques complètes

Contenu :
{content}"""

    try:
        response = model.generate_content(prompt)
        # Nettoie réponse
        text = response.text.strip()
        json_match = re.search(r'```json?\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            text = json_match.group(1)
        else:
            json_match = re.search(r'\[.*\]', text, re.DOTALL)
            if json_match:
                text = json_match.group(0)
        
        questions = json.loads(text)
        # Valide format
        if isinstance(questions, list) and len(questions) >= 5:
            return questions[:10]
        return questions
    except Exception as e:
        print(f"❌ Gemini error: {e}")
        return [{"question": f"Test {i}", "options": ["A", "B", "C", "D"], "correct": 0, "theme": THEMES[i%len(THEMES)], "explanation": "Fallback"} for i in range(10)]

def update_manifest(new_quiz):
    """Manifest.json"""
    manifest = []
    if os.path.exists('manifest.json'):
        try:
            with open('manifest.json', 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except:
            pass
    
    today = datetime.now().strftime('%Y%m%d')
    new_entry = {
        'file': f"quiz_{today}.json",
        'title': new_quiz['title'][:80],
        'date': today,
        'image': new_quiz['image']
    }
    
    # Unique par jour
    manifest = [e for e in manifest if not e['file'].endswith(today)] + [new_entry]
    manifest = manifest[-30:]  # 30 max
    
    with open('manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

def main():
    print("🚀 ActuQuiz - Auto Update")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    posts = scrape_hugo_newsletters()
    if not posts:
        print("❌ Pas de nouvelles newsletters")
        return
    
    print(f"📄 {len(posts)} trouvées")
    
    # Prend la plus récente
    post = posts[0]
    print(f"🔄 {post['title'][:60]}...")
    
    content, image = clean_content(post['url'])
    questions = generate_questions(content, post['title'])
    
    today = datetime.now().strftime('%Y%m%d')
    filename = f"quiz_{today}.json"
    
    data = {
        'title': post['title'],
        'date': today,
        'content': content,
        'image': image,
        'questions': questions
    }
    
    # Sauvegarde
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    update_manifest(data)
    
    print(f"✅ {filename} OK ({len(questions)} questions)")
    print(f"🌐 {post['url']}")
    print("🎉 Deploy GitHub Pages prêt !")

if __name__ == '__main__':
    main()
