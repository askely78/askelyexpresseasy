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

# ✅ Vérifier et créer la colonne "ville_destination" si besoin
with conn.cursor() as cur:
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name='colis'
                AND column_name='ville_destination'
            ) THEN
                ALTER TABLE colis
                ADD COLUMN ville_destination VARCHAR(100) NOT NULL DEFAULT 'Non précisé';
            END IF;
        END
        $$;
    """)
    conn.commit()

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

    # Exemple: menu principal
    if state["state"] == "menu":
        if incoming_msg == "1":
            set_state(user["id"], "search_date")
            msg.body("📅 Entrez la *date souhaitée* du départ (AAAA-MM-JJ) :")
        elif incoming_msg == "2":
            if user["role"] != "transporteur":
                set_state(user["id"], "register_transporteur")
                msg.body("🚚 *Inscription transporteur*\n\nVeuillez saisir votre *nom complet* :")
            else:
                set_state(user["id"], "publish_date")
                msg.body("📝 Entrez la *date du départ* à publier (AAAA-MM-JJ) :")
        else:
            msg.body("❗ Choix invalide. Tapez 1 ou 2.")
        return str(resp)

    # Les autres états ici (inscription, publication, recherche...)
    # ...

    msg.body("🤖 Je n'ai pas compris. Tapez *menu* pour revenir au menu principal.")
    return str(resp)

if __name__ == "__main__":
    app.run(debug=True, port=10000)
