from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import os
import psycopg2
import openai

app = Flask(__name__)

# Connexion PostgreSQL
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cursor = conn.cursor()

# Clé API OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# GPT
def ask_gpt(message):
    try:
        completion = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": message}]
        )
        return completion.choices[0].message["content"]
    except Exception:
        return "Désolé, une erreur est survenue."

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    resp = MessagingResponse()
    msg = resp.message()

    if incoming_msg in ["bonjour", "salut", "hello"]:
        msg.body("👋 Bienvenue chez Askely Express !

"
                 "1️⃣ Envoyer un colis
"
                 "2️⃣ Devenir transporteur
"
                 "3️⃣ Suivre un colis
"
                 "4️⃣ Déclarer un départ
"
                 "5️⃣ Aide ou question libre

"
                 "Répondez par le numéro correspondant.")
        return str(resp)

    if incoming_msg == "1":
        msg.body("📦 Veuillez envoyer le nom, la ville de départ, la ville d’arrivée et la date d’envoi souhaitée.")
        return str(resp)

    if incoming_msg == "2":
        msg.body("🚚 Pour devenir transporteur, envoyez :
Nom, numéro WhatsApp, ville de départ et date du départ.")
        return str(resp)

    if incoming_msg == "3":
        msg.body("🔍 Entrez le nom ou le numéro de suivi du colis.")
        return str(resp)

    if incoming_msg == "4":
        msg.body("📅 Entrez votre nom, numéro WhatsApp et la date de départ.")
        return str(resp)

    if incoming_msg == "5":
        gpt_reply = ask_gpt(incoming_msg)
        msg.body(gpt_reply)
        return str(resp)

    # Par défaut
    msg.body("🤖 Je n’ai pas compris. Tapez *bonjour* pour voir les options.")
    return str(resp)

if __name__ == "__main__":
    app.run(port=10000, debug=True)
