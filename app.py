from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL, sslmode='require')

# Récupérer ou créer l'utilisateur
def get_or_create_user(phone):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM users WHERE phone_number = %s", (phone,))
        user = cur.fetchone()
        if user:
            return user
        cur.execute("""
            INSERT INTO users (phone_number, role)
            VALUES (%s, %s)
            RETURNING *
        """, (phone, 'client'))
        conn.commit()
        return cur.fetchone()

# Gérer l'état
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

    # Message d'accueil personnalisé
    if not state or incoming_msg.lower() == "menu":
        set_state(user["id"], "menu")
        msg.body(
            "👋 *Bonjour et bienvenue chez Askely Express !*\n\n"
            "Je suis votre assistant intelligent 📲.\n\n"
            "Voici ce que je peux faire pour vous :\n"
            "✅ Vous mettre en relation avec un transporteur\n"
            "✅ Publier votre départ si vous êtes transporteur\n"
            "✅ Vous permettre d'évaluer un transporteur\n"
            "✅ Enregistrer vos colis et suivre leur état\n\n"
            "👉 *Tapez un chiffre pour continuer* :\n"
            "1️⃣ Je suis *client* (chercher un transporteur)\n"
            "2️⃣ Je suis *transporteur* (m'inscrire ou publier un départ)"
        )
        return str(resp)

    # Menu principal
    if state["state"] == "menu":
        if incoming_msg == "1":
            set_state(user["id"], "search_date")
            msg.body("📅 *Entrez la date souhaitée du départ* (AAAA-MM-JJ) :")
        elif incoming_msg == "2":
            if user["role"] != "transporteur":
                set_state(user["id"], "register_transporteur")
                msg.body("🚚 *Inscription transporteur*\n\nVeuillez saisir votre *nom complet* :")
            else:
                set_state(user["id"], "publish_date")
                msg.body("📝 *Entrez la date de votre départ* (AAAA-MM-JJ) :")
        else:
            msg.body("❗ *Choix invalide*. Tapez 1 ou 2.")
        return str(resp)

    # Inscription transporteur
    if state["state"] == "register_transporteur":
        nom = incoming_msg
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET nom = %s, role = %s WHERE id = %s", (nom, 'transporteur', user["id"]))
            conn.commit()
        set_state(user["id"], "publish_date")
        msg.body(
            f"✅ *Bienvenue {nom} !*\n\n"
            "📝 *Entrez la date de votre départ* (AAAA-MM-JJ) :"
        )
        return str(resp)

    # Publication départ - Date
    if state["state"] == "publish_date":
        try:
            datetime.strptime(incoming_msg, "%Y-%m-%d")
            set_state(user["id"], "publish_ville_depart", incoming_msg)
            msg.body("📍 *Entrez la ville de départ* :")
        except ValueError:
            msg.body("❗ *Format invalide*. Utilisez AAAA-MM-JJ.")
        return str(resp)

    if state["state"] == "publish_ville_depart":
        date_depart = state["last_message"]
        set_state(user["id"], "publish_ville_destination", f"{date_depart}|{incoming_msg}")
        msg.body("🏁 *Entrez la ville de destination* :")
        return str(resp)

    if state["state"] == "publish_ville_destination":
        parts = state["last_message"].split("|")
        date_depart = parts[0]
        ville_depart = parts[1]
        set_state(user["id"], "publish_description", f"{date_depart}|{ville_depart}|{incoming_msg}")
        msg.body("✏️ *Entrez une description* :")
        return str(resp)

    if state["state"] == "publish_description":
        parts = state["last_message"].split("|")
        date_depart, ville_depart, ville_destination = parts
        description = incoming_msg
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO departs (transporteur_id, date_depart, ville_depart, ville_destination, description)
                VALUES (%s, %s, %s, %s, %s)
            """, (user["id"], date_depart, ville_depart, ville_destination, description))
            conn.commit()
        set_state(user["id"], "menu")
        msg.body(
            "✅ *Votre départ a été publié avec succès.*\n\n"
            f"📝 *Récapitulatif* :\n"
            f"📅 Date : {date_depart}\n"
            f"📍 De : {ville_depart}\n"
            f"➡️ Vers : {ville_destination}\n"
            f"💬 {description}\n\n"
            "👉 Tapez *menu* pour revenir au menu principal."
        )
        return str(resp)

    # Recherche transporteur - Date
    if state["state"] == "search_date":
        try:
            datetime.strptime(incoming_msg, "%Y-%m-%d")
            set_state(user["id"], "search_ville_depart", incoming_msg)
            msg.body("📍 *Entrez la ville de départ* :")
        except ValueError:
            msg.body("❗ *Format invalide*. Utilisez AAAA-MM-JJ.")
        return str(resp)

    if state["state"] == "search_ville_depart":
        date_depart = state["last_message"]
        set_state(user["id"], "search_ville_destination", f"{date_depart}|{incoming_msg}")
        msg.body("🏁 *Entrez la ville de destination* :")
        return str(resp)

    if state["state"] == "search_ville_destination":
        parts = state["last_message"].split("|")
        date_depart = parts[0]
        ville_depart = parts[1]
        ville_destination = incoming_msg

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT d.*, u.nom, u.phone_number
                FROM departs d
                JOIN users u ON d.transporteur_id = u.id
                WHERE d.date_depart = %s
                  AND d.ville_depart ILIKE %s
                  AND d.ville_destination ILIKE %s
            """, (date_depart, ville_depart, ville_destination))
            results = cur.fetchall()

        if results:
            response = "🚚 *Transporteurs trouvés* :\n\n"
            for r in results:
                response += (
                    f"• *{r['nom']}*\n"
                    f"📅 {r['date_depart']}\n"
                    f"📍 De : {r['ville_depart']} ➡️ {r['ville_destination']}\n"
                    f"💬 {r['description']}\n"
                    f"📲 WhatsApp : {r['phone_number']}\n\n"
                )
        else:
            response = "❗ Aucun transporteur trouvé pour ces critères."

        set_state(user["id"], "menu")
        msg.body(response + "\n\n👉 Tapez *menu* pour recommencer.")
        return str(resp)

    msg.body("🤖 *Je n'ai pas compris.* Tapez *menu* pour revenir au menu.")
    return str(resp)

if __name__ == "__main__":
    app.run(debug=True, port=10000)
