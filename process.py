#!/usr/bin/env python3
import os
import json
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import google.genai as genai  # Nouvelle API officielle Gemini

# Configuration Gemini (NOUVEAU PACKAGE)
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-2.0-flash-exp')

THEMES = [
    "POLITIQUE EN FRANCE", "POLITIQUE INTERNATIONALE ET CONFLITS", "SOCIÉTÉ / FAITS DE SOCIÉTÉ",
    "ÉCONOMIE ET EMPLOI", "ENVIRONNEMENT ET CLIMAT", "SCIENCE, SANTÉ ET TECHNOLOGIE",
    "CULTURE ET MÉDIAS", "SPORT"
]

def scrape_hugo_newsletters():
    """Scrape les 3 dernières newsletters depuis Kessel (public)"""
    url = "https://hugodecrypte.kessel.media/posts"
    response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(response.text, 'html.parser')
    
    posts = []
    for article in soup.find_all('article')[:3]:  # 3 dernières
        link = article.find('a', href=True)
        title_elem = article.find(['h2', 'h3', 'h1'])
        date_elem = article.find('time') or article.find(class_=re.compile('date'))
        
        if link and title_elem:
            full_url = link['href']
            if not full_url.startswith('http'):
                full_url = 'https://hugodecrypte.kessel.media' + full_url
            posts.append({
                'title': title_elem.get_text().strip(),
                'url': full_url,
                'date': date_elem.get_text().strip() if date_elem else datetime.now().strftime('%Y-%m-%d')
            })
    return posts

def clean_content(url):
    """Nettoie l'article complet"""
    response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Extraction contenu principal
    content = soup.find(['article', '.content', '.post-content', 'main'])
    if not content:
        content = soup.body
    
    # Supprime parasites
    for unwanted in soup.find_all(['nav', 'aside', 'footer', 'header', '[class*="ad"]', '[class*="comment"]']):
        unwanted.decompose()
    
    # Images (première valide)
    img = soup.find('img', src=re.compile(r'\.(jpg|png|webp)$'))
    image_url = img['src'] if img else 'https://via.placeholder.com/300x200/667eea/ffffff?text=ActuQuiz'
    
    text = content.get_text(separator=' ', strip=True)[:5000]
    return text, image_url

def generate_questions(content, title):
    """Génère 10 questions avec les 8 thèmes exacts"""
    prompt = f"""Analyse cet article HugoDécrypte "{title}" (newsletter quotidienne).

TA MISSION : 10 questions QCM pédagogiques (niveau collège/lycée)
✅ Format JSON array STRICT :
[
  {{"question": "Question?", "options": ["A. Réponse1", "B. Réponse2", "C. Réponse3", "D. Réponse4"], "correct": 1, "theme": "THÈME_EXACT", "explanation": "Explication détaillée"}}
]

📋 RÈGLES OBLIGATOIRES :
- EXACTEMENT 10 questions
- 1 seul thème par question parmi CES 8 UNIQUEMENT : {', '.join(THEMES)}
- 4 options A B C D, indice correct 0-3
- Questions courtes (1 phrase)
- Explications complètes, éducatives
- Couvre tout l'article

Article :
{ content }
"""
    try:
        response = model.generate_content(prompt)
        # Nettoie JSON des markdown
        text = re.sub(r'```(?:json)?\s*', '', response.text, flags=re.DOTALL)
        text = re.sub(r'```\s*$', '', text, flags=re.MULTILINE)
        questions = json.loads(text.strip())
        return questions[:10]  # Sécurité
    except Exception as e:
        print(f"❌ Erreur Gemini: {e}")
        return [{"question": "Fallback", "options": ["A", "B", "C", "D"], "correct": 0, "theme": "SOCIÉTÉ / FAITS DE SOCIÉTÉ", "explanation": "Article temporaire"}] * 10

def update_manifest(new_quiz):
    """Met à jour manifest.json"""
    manifest = []
    if os.path.exists('manifest.json'):
        try:
            with open('manifest.json', 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except:
            pass
    
    # Ajoute le nouveau (unique par date)
    today = datetime.now().strftime('%Y%m%d')
    new_entry = {
        'file': f"quiz_{today}.json",
        'title': new_quiz['title'],
        'date': today,
        'image': new_quiz['image']
    }
    
    # Remplace si existe déjà
    manifest = [e for e in manifest if not e['file'].endswith(today)] + [new_entry]
    manifest = manifest[-50:]  # Garde 50 max
    
    with open('manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

def main():
    print("🚀 ActuQuiz - Scraping HugoDécrypte Kessel...")
    
    # 1. Scrape dernières newsletters
    posts = scrape_hugo_newsletters()
    if not posts:
        print("❌ Aucune newsletter trouvée")
        return
    
    print(f"📄 {len(posts)} newsletters détectées")
    
    for post in posts[:1]:  # 1 seule par jour pour éviter spam
        print(f"🔄 Traitement: {post['title'][:60]}...")
        
        content, image = clean_content(post['url'])
        questions = generate_questions(content, post['title'])
        
        # Sauvegarde
        today = datetime.now().strftime('%Y%m%d')
        filename = f"quiz_{today}.json"
        data = {
            'title': post['title'],
            'date': today,
            'content': content,
            'image': image,
            'questions': questions
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        update_manifest(data)
        print(f"✅ {filename} créé ({len(questions)} questions)")
        break  # 1 seul par run
    
    print("🎉 Process terminé ! Site mis à jour.")

if __name__ **==** '__main__':
    main()
