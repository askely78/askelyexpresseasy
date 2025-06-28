from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime

app = Flask(__name__)

# Connexion PostgreSQL
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

# Mettre à jour l'état de la conversation
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

# Récupérer l'état de la conversation
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
            "👋 *Bienvenue chez Askely Express*\n\n"
            "Tapez un chiffre :\n"
            "1️⃣ Je suis *client* (chercher un transporteur)\n"
            "2️⃣ Je suis *transporteur* (m'inscrire ou publier un départ)"
        )
        return str(resp)

    # Menu principal
    if state["state"] == "menu":
        if incoming_msg == "1":
            set_state(user["id"], "search_date")
            msg.body("📅 Entrez *la date souhaitée* du départ (AAAA-MM-JJ) :")
        elif incoming_msg == "2":
            if user["role"] != "transporteur":
                set_state(user["id"], "register_transporteur")
                msg.body("🚚 *Inscription transporteur*\n\nVeuillez saisir votre *nom complet* :")
            else:
                set_state(user["id"], "publish_date")
                msg.body("📝 Entrez la *date du départ* à publier (AAAA-MM-JJ) :")
        else:
            msg.body("❗ Choix invalide. Veuillez taper 1 ou 2.")
        return str(resp)

    # Inscription transporteur
    if state["state"] == "register_transporteur":
        nom = incoming_msg
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET nom = %s, role = %s WHERE id = %s", (nom, 'transporteur', user["id"]))
            conn.commit()
        set_state(user["id"], "publish_date")
        msg.body("✅ Inscription enregistrée.\n\n📝 Entrez la *date du départ* à publier (AAAA-MM-JJ) :")
        return str(resp)

    # Publication du départ - Date
    if state["state"] == "publish_date":
        try:
            datetime.strptime(incoming_msg, "%Y-%m-%d")
            set_state(user["id"], "publish_ville", incoming_msg)
            msg.body("📍 Entrez la *ville de destination* :")
        except ValueError:
            msg.body("❗ Format invalide. Utilisez AAAA-MM-JJ.")
        return str(resp)

    # Publication du départ - Ville
    if state["state"] == "publish_ville":
        date_depart = state["last_message"]
        ville = incoming_msg
        set_state(user["id"], "publish_desc", f"{date_depart}|{ville}")
        msg.body("✏️ Entrez une *description* du départ :")
        return str(resp)

    # Publication du départ - Description finale
    if state["state"] == "publish_desc":
        date_ville = state["last_message"].split("|")
        date_depart = date_ville[0]
        ville = date_ville[1]
        description = incoming_msg
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO departs (transporteur_id, date_depart, ville_destination, description)
                VALUES (%s, %s, %s, %s)
            """, (user["id"], date_depart, ville, description))
            conn.commit()
        set_state(user["id"], "menu")
        msg.body("✅ Votre départ a été publié avec succès.\n\nTapez *menu* pour revenir au menu principal.")
        return str(resp)

    # Recherche transporteur - Date
    if state["state"] == "search_date":
        try:
            datetime.strptime(incoming_msg, "%Y-%m-%d")
            set_state(user["id"], "search_ville", incoming_msg)
            msg.body("📍 Entrez la *ville de destination* :")
        except ValueError:
            msg.body("❗ Format invalide. Utilisez AAAA-MM-JJ.")
        return str(resp)

    # Recherche transporteur - Ville
    if state["state"] == "search_ville":
        date_depart = state["last_message"]
        ville = incoming_msg
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT d.*, u.nom, u.phone_number
                FROM departs d
                JOIN users u ON d.transporteur_id = u.id
                WHERE d.date_depart = %s AND d.ville_destination ILIKE %s
            """, (date_depart, ville))
            results = cur.fetchall()
        if results:
            response = "🚚 *Transporteurs disponibles* :\n\n"
            for r in results:
                response += (
                    f"• *{r['nom']}*\n"
                    f"📅 {r['date_depart']} - 📍 {r['ville_destination']}\n"
                    f"💬 {r['description']}\n"
                    f"📲 WhatsApp: {r['phone_number']}\n\n"
                )
            response += "✅ Vous pouvez les contacter directement."
        else:
            response = "❗ Aucun transporteur trouvé pour cette date et ville."
        set_state(user["id"], "menu")
        msg.body(response)
        return str(resp)

    # Commande spéciale
    if incoming_msg.lower() == "menu":
        set_state(user["id"], "menu")
        msg.body(
            "👋 *Menu principal*\n\n"
            "1️⃣ Je suis *client* (chercher un transporteur)\n"
            "2️⃣ Je suis *transporteur* (publier un départ)"
        )
        return str(resp)

    # Réponse par défaut
    msg.body("🤖 Je n'ai pas compris. Tapez *menu* pour revenir au menu principal.")
    return str(resp)

if __name__ == "__main__":
    app.run(debug=True, port=10000)
