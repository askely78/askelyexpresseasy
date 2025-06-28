import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    return conn

def get_or_create_user(phone):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE phone = %s", (phone,))
    user = cur.fetchone()
    if user:
        cur.close()
        conn.close()
        return user
    # ✅ Création avec valeurs par défaut pour éviter l'erreur
    cur.execute("""
        INSERT INTO users (name, phone_number, phone)
        VALUES (%s, %s, %s)
        RETURNING *
    """, ("Inconnu", phone, phone))
    user = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return user

def get_user_state(user_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM user_states WHERE user_id = %s", (user_id,))
    state = cur.fetchone()
    cur.close()
    conn.close()
    return state

def set_user_state(user_id, state):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM user_states WHERE user_id = %s", (user_id,))
    cur.execute(
        "INSERT INTO user_states (user_id, state, updated_at) VALUES (%s, %s, %s)",
        (user_id, state, datetime.utcnow())
    )
    conn.commit()
    cur.close()
    conn.close()

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    from_number = request.values.get("From", "")
    phone = from_number.replace("whatsapp:", "")
    resp = MessagingResponse()
    msg = resp.message()

    user = get_or_create_user(phone)
    state_row = get_user_state(user["id"])
    state = state_row["state"] if state_row else None

    if incoming_msg in ["bonjour", "menu", "hello"]:
        set_user_state(user["id"], "menu")
        msg.body(
            "👋 *Bienvenue chez Askely Express !*\n\n"
            "Veuillez choisir une option :\n"
            "1️⃣ *Envoyer un colis*\n"
            "2️⃣ *Devenir transporteur*\n"
            "3️⃣ *Consulter mes envois*\n\n"
            "Envoyez le numéro correspondant."
        )
        return str(resp)

    if state == "menu":
        if incoming_msg == "1":
            set_user_state(user["id"], "send_parcel")
            msg.body("✏️ Veuillez décrire le colis que vous souhaitez envoyer.")
            return str(resp)
        elif incoming_msg == "2":
            set_user_state(user["id"], "become_transporter")
            msg.body("🚚 Entrez votre *nom* pour vous enregistrer comme transporteur.")
            return str(resp)
        elif incoming_msg == "3":
            msg.body("📦 Vous n'avez pas encore d'envois enregistrés.")
            return str(resp)
        else:
            msg.body("❗ Choix invalide. Envoyez *1*, *2* ou *3*.")
            return str(resp)

    if state == "send_parcel":
        description = incoming_msg
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO colis (user_id, description, date_envoi)
            VALUES (%s, %s, %s)
        """, (user["id"], description, datetime.utcnow()))
        conn.commit()
        cur.close()
        conn.close()
        set_user_state(user["id"], None)
        msg.body("✅ Votre colis a été enregistré avec succès.")
        return str(resp)

    if state == "become_transporter":
        name = incoming_msg
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO transporteurs (user_id, nom, date_depart)
            VALUES (%s, %s, %s)
        """, (user["id"], name, datetime.utcnow()))
        conn.commit()
        cur.close()
        conn.close()
        set_user_state(user["id"], None)
        msg.body("🚚 Vous êtes maintenant enregistré comme transporteur.")
        return str(resp)

    msg.body("🤖 Je n'ai pas compris votre réponse.\nEnvoyez *Bonjour* pour voir les options.")
    return str(resp)

if __name__ == "__main__":
    app.run(debug=True, port=10000)
