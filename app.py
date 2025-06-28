from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL, sslmode='require')

# Récupérer ou créer un utilisateur
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

# Récupérer l'état
def get_state(user_id):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM user_states WHERE user_id = %s", (user_id,))
        return cur.fetchone()

# Sauvegarder l'état
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

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    phone = request.values.get("From", "").split(":")[-1]
    resp = MessagingResponse()
    msg = resp.message()

    user = get_or_create_user(phone)
    state = get_state(user["id"])

    if incoming_msg.lower() == "menu":
        set_state(user["id"], "menu")
        msg.body(
            "👋 *Menu principal*\n\n"
            "1️⃣ Je suis *client* (chercher un transporteur)\n"
            "2️⃣ Je suis *transporteur* (publier un départ)"
        )
        return str(resp)

    if not state:
        set_state(user["id"], "menu")
        msg.body(
            "👋 *Bienvenue chez Askely Express*\n\n"
            "1️⃣ Je suis *client* (chercher un transporteur)\n"
            "2️⃣ Je suis *transporteur* (publier un départ)"
        )
        return str(resp)

    if state["state"] == "menu":
        if incoming_msg == "1":
            set_state(user["id"], "search_date")
            msg.body("📅 Entrez *la date souhaitée* (AAAA-MM-JJ) :")
        elif incoming_msg == "2":
            if user["role"] != "transporteur":
                set_state(user["id"], "register_transporteur")
                msg.body("🚚 *Inscription transporteur*\n\nVeuillez saisir votre *nom complet* :")
            else:
                set_state(user["id"], "publish_date")
                msg.body("📅 Entrez *la date de départ* (AAAA-MM-JJ) :")
        else:
            msg.body("❗ Choix invalide. Tapez 1 ou 2.")
        return str(resp)

    if state["state"] == "register_transporteur":
        nom = incoming_msg
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET nom = %s, role = 'transporteur' WHERE id = %s", (nom, user["id"]))
            conn.commit()
        set_state(user["id"], "publish_date")
        msg.body("✅ Inscription enregistrée.\n\n📅 Entrez *la date de départ* (AAAA-MM-JJ) :")
        return str(resp)

    if state["state"] == "publish_date":
        try:
            datetime.strptime(incoming_msg, "%Y-%m-%d")
            set_state(user["id"], "publish_ville_depart", incoming_msg)
            msg.body("🚚 Entrez *la ville de départ* :")
        except ValueError:
            msg.body("❗ Format invalide. Utilisez AAAA-MM-JJ.")
        return str(resp)

    if state["state"] == "publish_ville_depart":
        date = state["last_message"]
        ville_depart = incoming_msg
        set_state(user["id"], "publish_ville_destination", f"{date}|{ville_depart}")
        msg.body("📍 Entrez *la ville de destination* :")
        return str(resp)

    if state["state"] == "publish_ville_destination":
        date_ville_dep = state["last_message"].split("|")
        date, ville_depart = date_ville_dep
        ville_dest = incoming_msg
        set_state(user["id"], "publish_description", f"{date}|{ville_depart}|{ville_dest}")
        msg.body("✏️ Entrez *une description* :")
        return str(resp)

    if state["state"] == "publish_description":
        date_villes = state["last_message"].split("|")
        date, ville_depart, ville_dest = date_villes
        description = incoming_msg
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO departs (transporteur_id, date_depart, ville_depart, ville_destination, description)
                VALUES (%s, %s, %s, %s, %s)
            """, (user["id"], date, ville_depart, ville_dest, description))
            conn.commit()
        set_state(user["id"], "menu")
        msg.body("✅ Votre départ a été publié.\n\nTaper *menu* pour revenir au menu principal.")
        return str(resp)

    if state["state"] == "search_date":
        try:
            datetime.strptime(incoming_msg, "%Y-%m-%d")
            set_state(user["id"], "search_ville_depart", incoming_msg)
            msg.body("🚚 Entrez *la ville de départ* :")
        except ValueError:
            msg.body("❗ Format invalide. Utilisez AAAA-MM-JJ.")
        return str(resp)

    if state["state"] == "search_ville_depart":
        date = state["last_message"]
        ville_depart = incoming_msg
        set_state(user["id"], "search_ville_destination", f"{date}|{ville_depart}")
        msg.body("📍 Entrez *la ville de destination* :")
        return str(resp)

    if state["state"] == "search_ville_destination":
        date_ville_dep = state["last_message"].split("|")
        date, ville_depart = date_ville_dep
        ville_dest = incoming_msg
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT d.*, u.nom, u.phone_number
                FROM departs d
                JOIN users u ON d.transporteur_id = u.id
                WHERE d.date_depart = %s
                AND d.ville_depart ILIKE %s
                AND d.ville_destination ILIKE %s
            """, (date, ville_depart, ville_dest))
            results = cur.fetchall()
        if results:
            response = "🚚 *Transporteurs trouvés* :\n\n"
            for idx, r in enumerate(results, 1):
                response += (
                    f"{idx}. *{r['nom']}*\n"
                    f"📅 {r['date_depart']} - {r['ville_depart']} ➡️ {r['ville_destination']}\n"
                    f"💬 {r['description']}\n"
                    f"---\n"
                )
            response += (
                "\n✉️ *Répondez avec le numéro* du transporteur choisi pour recevoir son WhatsApp."
            )
            # Stocker tous les IDs des transporteurs trouvés
            ids = ",".join(str(r["transporteur_id"]) for r in results)
            set_state(user["id"], "await_selection", ids)
        else:
            response = "❗ Aucun transporteur trouvé."
            set_state(user["id"], "menu")
        msg.body(response)
        return str(resp)

    if state["state"] == "await_selection":
        try:
            selection = int(incoming_msg.strip()) - 1
            transporteur_ids = state["last_message"].split(",")
            selected_id = int(transporteur_ids[selection])
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT nom, phone_number FROM users WHERE id = %s
                """, (selected_id,))
                t = cur.fetchone()
            msg.body(
                f"✅ Voici le contact de *{t['nom']}* :\n"
                f"📲 WhatsApp: {t['phone_number']}\n\n"
                "Tapez *menu* pour revenir au menu principal."
            )
        except:
            msg.body("❗ Saisie invalide. Entrez un numéro valide.")
        set_state(user["id"], "menu")
        return str(resp)

    msg.body("🤖 Je n'ai pas compris. Taper *menu* pour recommencer.")
    return str(resp)

if __name__ == "__main__":
    app.run(debug=True, port=10000)
