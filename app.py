from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import psycopg2
import os

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_conn():
    return psycopg2.connect(DATABASE_URL)

@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.form.get("Body", "").strip().lower()
    resp = MessagingResponse()
    msg = resp.message()

    if incoming_msg == "bonjour":
        msg.body(
            "👋 Bienvenue chez Askely Express !\n\n"
            "1️⃣ Envoyer un colis\n"
            "2️⃣ Devenir transporteur\n"
            "3️⃣ Déclarer un départ\n"
            "4️⃣ Suivre un colis\n\n"
            "Répondez avec le numéro correspondant."
        )
    elif incoming_msg == "1":
        msg.body("📦 Pour envoyer un colis, merci d'indiquer la destination :")
    elif incoming_msg == "2":
        msg.body("🚚 Pour devenir transporteur, indiquez votre nom et votre numéro WhatsApp.")
    elif incoming_msg == "3":
        msg.body("📝 Pour déclarer un départ, indiquez la date souhaitée (format AAAA-MM-JJ).")
    elif incoming_msg == "4":
        msg.body("🔍 Veuillez entrer le numéro du colis à suivre.")
    else:
        msg.body("🤖 Je n'ai pas compris. Tapez *bonjour* pour voir les options.")

    return str(resp)

if __name__ == "__main__":
    app.run(debug=True)
