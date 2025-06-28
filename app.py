from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def get_or_create_user(phone):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE phone = %s", (phone,))
        user = cur.fetchone()
        if not user:
            cur.execute(
                "INSERT INTO users (phone, created_at) VALUES (%s, NOW()) RETURNING *",
                (phone,)
            )
            conn.commit()
            user = cur.fetchone()
        return user

def update_state(user_id, state):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO user_states (user_id, state, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT (user_id) DO UPDATE SET state = EXCLUDED.state, updated_at = EXCLUDED.updated_at",
            (user_id, state)
        )
        conn.commit()

def get_state(user_id):
    with conn.cursor() as cur:
        cur.execute("SELECT state FROM user_states WHERE user_id = %s", (user_id,))
        res = cur.fetchone()
        return res["state"] if res else None

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.form.get("Body", "").strip()
    from_number = request.form.get("From", "")
    phone = from_number.split(":")[-1]

    user = get_or_create_user(phone)
    current_state = get_state(user["id"])

    resp = MessagingResponse()
    msg = resp.message()

    if incoming_msg.lower() == "bonjour":
        update_state(user["id"], "awaiting_choice")
        msg.body("👋 *Bienvenue chez Askely Express !*\n\n📦 Pour *envoyer un colis*, tapez *1*\n🚚 Pour *devenir transporteur*, tapez *2*\n📅 Pour *voir les départs*, tapez *3*")
    elif current_state == "awaiting_choice":
        if incoming_msg == "1":
            update_state(user["id"], "sending_parcel")
            msg.body("✏️ Entrez la *description du colis* :")
        elif incoming_msg == "2":
            update_state(user["id"], "becoming_transporter")
            msg.body("🚚 Entrez votre *nom complet* :")
        elif incoming_msg == "3":
            with conn.cursor() as cur:
                cur.execute("SELECT nom, date_depart FROM transporteurs ORDER BY date_depart")
                rows = cur.fetchall()
                if rows:
                    txt = "🚚 *Départs disponibles* :\n\n"
                    for r in rows:
                        txt += f"- {r['nom']} le {r['date_depart']}\n"
                    msg.body(txt)
                else:
                    msg.body("Aucun départ enregistré.")
        else:
            msg.body("Réponse invalide. Tapez *1*, *2* ou *3*.")
    elif current_state == "sending_parcel":
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO colis (user_id, description, date_envoi, created_at) VALUES (%s, %s, %s, NOW())",
                (user["id"], incoming_msg, datetime.now().date())
            )
            conn.commit()
        update_state(user["id"], None)
        msg.body("✅ Votre colis a été enregistré.")
    elif current_state == "becoming_transporter":
        update_state(user["id"], "awaiting_date")
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO transporteurs (user_id, nom, date_depart, created_at) VALUES (%s, %s, %s, NOW())",
                (user["id"], incoming_msg, datetime.now().date())
            )
            conn.commit()
        msg.body("📅 Entrez la *date de départ* (YYYY-MM-DD) :")
    elif current_state == "awaiting_date":
        try:
            date = datetime.strptime(incoming_msg, "%Y-%m-%d").date()
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE transporteurs SET date_depart = %s WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
                    (date, user["id"])
                )
                conn.commit()
            update_state(user["id"], None)
            msg.body("✅ Départ enregistré.")
        except ValueError:
            msg.body("Format de date invalide. Utilisez YYYY-MM-DD.")
    else:
        msg.body("Je n'ai pas compris. Tapez *bonjour* pour voir les options.")
    return str(resp)

if __name__ == "__main__":
    app.run(debug=True)
