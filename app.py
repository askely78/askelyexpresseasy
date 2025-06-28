import os
import psycopg2
import psycopg2.extras
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL, sslmode="require")

def get_or_create_user(phone):
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        # Vérifie si l'utilisateur existe
        cur.execute("SELECT * FROM users WHERE phone_number = %s", (phone,))
        user = cur.fetchone()
        if user:
            return user
        # Sinon, crée l'utilisateur avec rôle 'client'
        cur.execute("""
            INSERT INTO users (phone_number, role)
            VALUES (%s, %s)
            RETURNING *
        """, (phone, "client"))
        conn.commit()
        return cur.fetchone()

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.form.get("Body", "").strip().lower()
    from_number = request.form.get("From", "")
    phone = from_number.split(":")[-1]

    user = get_or_create_user(phone)

    resp = MessagingResponse()
    msg = resp.message()

    if incoming_msg in ["bonjour", "salut", "hello"]:
        msg.body(
            "👋 *Bienvenue chez Askely Express !*\n\n"
            "Merci de nous avoir contactés.\n"
            "Tapez *1* pour envoyer un colis 📦\n"
            "Tapez *2* pour devenir transporteur 🚚\n"
            "Tapez *3* pour déclarer un départ 🛫"
        )
        return str(resp)

    if incoming_msg == "1":
        msg.body(
            "✉️ *Envoi de colis*\n\n"
            "Veuillez saisir la description de votre colis."
        )
        return str(resp)

    if incoming_msg == "2":
        msg.body(
            "🚚 *Devenir transporteur*\n\n"
            "Merci de votre intérêt. Veuillez saisir votre nom complet."
        )
        return str(resp)

    if incoming_msg == "3":
        msg.body(
            "🛫 *Déclarer un départ*\n\n"
            "Veuillez indiquer la date de votre départ (format AAAA-MM-JJ)."
        )
        return str(resp)

    # Réponse par défaut
    msg.body(
        "🤖 Je n'ai pas compris votre message.\n"
        "Veuillez taper *bonjour* pour voir les options."
    )
    return str(resp)

if __name__ == "__main__":
    app.run(debug=True, port=10000)
