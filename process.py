#!/usr/bin/env python3
import os
import json
import re
import base64
import datetime
from bs4 import BeautifulSoup
import imghdr
import google.generativeai as genai  # UNIQUEMENT ça pour Gemini
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError

# Configuration Gemini
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-2.0-flash-exp')

THEMES = [
    "POLITIQUE EN FRANCE", "POLITIQUE INTERNATIONALE ET CONFLITS", "SOCIÉTÉ / FAITS DE SOCIÉTÉ",
    "ÉCONOMIE ET EMPLOI", "ENVIRONNEMENT ET CLIMAT", "SCIENCE, SANTÉ ET TECHNOLOGIE",
    "CULTURE ET MÉDIAS", "SPORT"
]

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def authenticate_gmail():
    """Auth Gmail OAuth2"""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

def clean_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    # Supprime Gmail artifacts
    for tag in soup(['header', 'footer', '[class*="gmail"]', '[id*="gmail"]', 'div[role="presentation"]']):
        tag.decompose()
    # Nettoie styles parasites
    for tag in soup.find_all(attrs={"style": re.compile(r'(background|display:none|position|margin-top:\s*-|visibility:hidden)')}):
        tag.decompose()
    # Simplifie images
    for img in soup.find_all('img'):
        if img.get('src') and 'cid:' in img['src']:
            img.decompose()
    return str(soup.get_text()[:5000])  # Texte brut pour Gemini + limite

def extract_title(html):
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.find('h1') or soup.find('h2') or soup.title
    return title.get_text().strip()[:100] if title else 'Newsletter HugoDécrypte'

def generate_questions(content, title):
    prompt = f"""Analyse cet article de la newsletter HugoDécrypte "{title}".

Génère EXACTEMENT 10 questions QCM éducatives pour collégiens/lycéens :
- 4 options (A B C D), 1 seule bonne réponse (indice 0-3)
- Attribue À CHAQUE question UN des thèmes EXACTS suivants : {', '.join(THEMES)}
- Questions courtes, précises, niveau collège/lycée
- Explications détaillées et pédagogiques

Format JSON valide (array d'objets) :
[
  {{
    "question": "Question ?",
    "options": ["A. Faux", "B. Vrai", "C. Option 3", "D. Option 4"],
    "correct": 1,
    "theme": "POLITIQUE INTERNATIONALE ET CONFLITS",
    "explanation": "Explication complète..."
  }}
]

Contenu article :
{ content }
"""
    try:
        response = model.generate_content(prompt)
        questions = json.loads(response.text.strip('```json\n').strip('```'))
        return questions
    except Exception as e:
        print(f"Erreur Gemini: {e}")
        return []  # Fallback

def process_message(service, msg_id):
    try:
        msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        payload = msg['payload']
        
        # Extraire HTML
        html_content = ''
        if 'parts' in payload:
            for part in payload['parts']:
                if part.get('mimeType') == 'text/html':
                    data = part['body'].get('data')
                    if data:
                        html_content = base64.urlsafe_b64decode(data).decode('utf-8')
                        break
        else:
            data = payload['body'].get('data')
            if data:
                html_content = base64.urlsafe_b64decode(data).decode('utf-8')
        
        if not html_content:
            print("Pas de HTML trouvé")
            return
            
        # Traitement
        title = extract_title(html_content)
        clean_content = clean_html(html_content)
        questions = generate_questions(clean_content, title)
        
        if not questions:
            print("Aucune question générée")
            return
            
        # Sauvegarde JSON
        today = datetime.datetime.now().strftime('%Y%m%d_%H%M')
        filename = f"quiz_{today}.json"
        data = {
            'title': title,
            'date': today,
            'content': clean_content,  # Texte nettoyé
            'questions': questions
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Update manifest
        manifest = []
        if os.path.exists('manifest.json'):
            with open('manifest.json', 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        
        # Image par défaut (pas d'URL extraction pour simplicité statique)
        manifest.append({
            'file': filename,
            'title': title,
            'date': today,
            'image': 'https://via.placeholder.com/300x200/667eea/ffffff?text=ActuQuiz'
        })
        
        # Garde les 50 derniers
        manifest = manifest[-50:]
        with open('manifest.json', 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        
        print(f"✅ Quiz généré : {filename} ({len(questions)} questions)")
        
    except HttpError as error:
        print(f"Erreur Gmail {error}")

def main():
    print("🚀 Lancement ActuQuiz process...")
    service = authenticate_gmail()
    
    # Recherche newsletters Hugo (label HUGO ou from hugodecrypte)
    query = 'from:hugodecrypte@kessel.media is:unread'  # Seulement non traitées
    results = service.users().messages().list(userId='me', q=query).execute()
    
    messages = results.get('messages', [])
    if not messages:
        print("✅ Aucune nouvelle newsletter")
        return
    
    for msg in messages[:3]:  # Max 3 par run
        process_message(service, msg['id'])
        # Marque comme lu
        service.users().messages().modify(userId='me', id=msg['id'], body={'removeLabelIds': ['UNREAD']}).execute()
    
    print("🎉 Process terminé !")

if __name__ == '__main__':
    main()
