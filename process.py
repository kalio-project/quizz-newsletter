import os, imaplib, email, json, re
from google import genai
from google.genai import errors

# 1. INITIALISATION DU CLIENT
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

print("🚀 --- DÉBUT DU DIAGNOSTIC ---")

# 2. TEST DE LA CLÉ API (SANS PASSER PAR LES MAILS)
print("🔍 Étape 1 : Test de la clé API...")
try:
    # On liste les modèles disponibles pour voir si la clé ouvre la porte
    models = client.models.list()
    available_models = [m.name for m in models]
    print(f"✅ Clé API valide ! Modèles accessibles : {available_models[:5]}...")
except Exception as e:
    print(f"❌ ERREUR CLÉ API : {e}")
    print("👉 Vérifie si tu as bien copié la clé dans GitHub Secrets (GEMINI_API_KEY).")
    exit(1)

# 3. TEST DE GÉNÉRATION SIMPLE
print("\n🔍 Étape 2 : Test de réponse IA...")
test_prompt = "Dis 'OK' si tu m'entends."
test_model = 'gemini-1.5-flash' # On teste le modèle standard

try:
    response = client.models.generate_content(model=test_model, contents=test_prompt)
    print(f"✅ L'IA répond : {response.text}")
except Exception as e:
    print(f"❌ ERREUR MODÈLE ({test_model}) : {e}")
    if "404" in str(e):
        print("👉 Le modèle n'est pas trouvé. C'est souvent un problème de région (Europe/France).")
    elif "403" in str(e):
        print("👉 Accès refusé. Vérifie que l'API Gemini est activée dans Google AI Studio.")
    elif "429" in str(e):
        print("👉 Quota dépassé. Trop de requêtes en peu de temps.")
    
# 4. CONNEXION GMAIL (Si l'IA fonctionne)
print("\n🔍 Étape 3 : Connexion Gmail...")
try:
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASSWORD"])
    print("✅ Connexion Gmail réussie !")
    mail.logout()
except Exception as e:
    print(f"❌ ERREUR GMAIL : {e}")

print("\n--- FIN DU DIAGNOSTIC ---")
