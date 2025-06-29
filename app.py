from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL, sslmode="require")

def get_or_create_user(phone):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM users WHERE phone_number = %s", (phone,))
        user = cur.fetchone()
        if user:
            return user
        cur.execute(
            "INSERT INTO users (phone_number, role) VALUES (%s, %s) RETURNING *",
            (phone, 'client')
        )
        conn.commit()
        return cur.fetchone()

def set_state(user_id, state, last_message=None):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO user_states (user_id, state, last_message, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE
            SET state = EXCLUDED.state,
                last_message = EXCLUDED.last_message,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, state, last_message))
        conn.commit()

def get_state(user_id):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM user_states WHERE user_id = %s", (user_id,))
        return cur.fetchone()

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    phone = request.values.get("From", "").split(":")[-1]
    resp = MessagingResponse()
    msg = resp.message()

    user = get_or_create_user(phone)
    state = get_state(user["id"])

    if not state:
        set_state(user["id"], "menu")
        msg.body(
            "👋 Bonjour et bienvenue chez *Askely Express* !\n\n"
            "🚀 *Qui suis-je ?*\n"
            "Je suis votre assistant intelligent.\n\n"
            "✅ Chercher un transporteur\n"
            "✅ Publier un départ\n"
            "✅ Voir les évaluations et notes\n"
            "✅ Recevoir des rappels automatiques\n\n"
            "✨ Tapez le numéro correspondant :\n"
            "1️⃣ Je suis *Client* (chercher un transporteur)\n"
            "2️⃣ Je suis *Transporteur* (publier un départ)"
        )
        return str(resp)

    if incoming_msg.lower() == "menu":
        set_state(user["id"], "menu")
        msg.body(
            "👋 *Menu principal* :\n\n"
            "1️⃣ Je suis *Client* (chercher un transporteur)\n"
            "2️⃣ Je suis *Transporteur* (publier un départ)"
        )
        return str(resp)

    # Menu principal
    if state["state"] == "menu":
        if incoming_msg == "1":
            set_state(user["id"], "search_date")
            msg.body("📅 *Entrez la date souhaitée de départ* (AAAA-MM-JJ) :")
        elif incoming_msg == "2":
            if user["role"] != "transporteur":
                set_state(user["id"], "register_transporteur")
                msg.body("🚚 *Inscription transporteur*\n\nVeuillez saisir votre *nom complet* :")
            else:
                set_state(user["id"], "publish_date")
                msg.body("📅 *Entrez la date de votre départ* (AAAA-MM-JJ) :")
        else:
            msg.body("❗ Choix invalide. Tapez 1 ou 2.")
        return str(resp)

    # Inscription transporteur
    if state["state"] == "register_transporteur":
        nom = incoming_msg
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET nom = %s, role = %s WHERE id = %s", (nom, "transporteur", user["id"]))
            conn.commit()
        set_state(user["id"], "publish_date")
        msg.body("✅ Inscription enregistrée.\n\n📅 *Entrez la date de votre départ* (AAAA-MM-JJ) :")
        return str(resp)

    if state["state"] == "publish_date":
        try:
            datetime.strptime(incoming_msg, "%Y-%m-%d")
            set_state(user["id"], "publish_ville_depart", incoming_msg)
            msg.body("📍 *Entrez la ville de départ* :")
        except ValueError:
            msg.body("❗ Format invalide. Utilisez AAAA-MM-JJ.")
        return str(resp)

    if state["state"] == "publish_ville_depart":
        date_depart = state["last_message"]
        set_state(user["id"], "publish_ville_dest", f"{date_depart}|{incoming_msg}")
        msg.body("🏁 *Entrez la ville de destination* :")
        return str(resp)

    if state["state"] == "publish_ville_dest":
        date_ville = state["last_message"].split("|")
        date_depart, ville_depart = date_ville
        set_state(user["id"], "publish_desc", f"{date_depart}|{ville_depart}|{incoming_msg}")
        msg.body("✏️ *Entrez une description de votre départ* :")
        return str(resp)

    if state["state"] == "publish_desc":
        parts = state["last_message"].split("|")
        date_depart, ville_depart, ville_dest = parts
        description = incoming_msg
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO departs (transporteur_id, date_depart, ville_depart, ville_destination, description)
                VALUES (%s, %s, %s, %s, %s)
            """, (user["id"], date_depart, ville_depart, ville_dest, description))
            conn.commit()
        set_state(user["id"], "menu")
        msg.body(
            "✅ *Votre départ a été publié avec succès.*\n\n"
            "🗓️ Date : " + date_depart +
            "\n🏁 " + ville_depart + " -> " + ville_dest +
            "\n💬 " + description +
            "\n\nTapez *menu* pour revenir au menu principal."
        )
        return str(resp)

    # Recherche transporteur
    if state["state"] == "search_date":
        try:
            datetime.strptime(incoming_msg, "%Y-%m-%d")
            set_state(user["id"], "search_ville_depart", incoming_msg)
            msg.body("📍 *Entrez la ville de départ* :")
        except ValueError:
            msg.body("❗ Format invalide. Utilisez AAAA-MM-JJ.")
        return str(resp)

    if state["state"] == "search_ville_depart":
        set_state(user["id"], "search_ville_dest", f"{state['last_message']}|{incoming_msg}")
        msg.body("🏁 *Entrez la ville de destination* :")
        return str(resp)

    if state["state"] == "search_ville_dest":
        parts = state["last_message"].split("|")
        date_depart, ville_depart = parts
        ville_dest = incoming_msg

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT d.*, u.nom, u.phone_number,
                       COALESCE(ROUND(AVG(a.note),1), 'Aucune note') AS moyenne,
                       (SELECT avis FROM avis WHERE transporteur_id = u.id ORDER BY created_at DESC LIMIT 1) AS dernier_avis
                FROM departs d
                JOIN users u ON d.transporteur_id = u.id
                LEFT JOIN avis a ON a.transporteur_id = u.id
                WHERE d.date_depart = %s AND d.ville_depart ILIKE %s AND d.ville_destination ILIKE %s
                GROUP BY d.id, u.id
            """, (date_depart, ville_depart, ville_dest))
            results = cur.fetchall()

        if results:
            response = "🚚 *Transporteurs trouvés* :\n\n"
            for r in results:
                response += (
                    f"• *{r['nom']}*\n"
                    f"📅 {r['date_depart']} – {r['ville_depart']} -> {r['ville_destination']}\n"
                    f"💬 {r['description']}\n"
                    f"⭐ Note : {r['moyenne']}\n"
                    f"📝 Dernier avis : {r['dernier_avis'] or 'Aucun avis'}\n"
                    f"📲 WhatsApp : {r['phone_number']}\n\n"
                )
        else:
            response = "❗ Aucun transporteur trouvé pour ces critères."

        set_state(user["id"], "menu")
        msg.body(response + "\nTapez *menu* pour revenir au menu principal.")
        return str(resp)

    msg.body("🤖 Je n'ai pas compris. Tapez *menu* pour recommencer.")
    return str(resp)
