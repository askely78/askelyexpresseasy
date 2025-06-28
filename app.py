from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import psycopg2
import os
from datetime import datetime

# Configuration Flask
app = Flask(__name__)

# Connexion PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL")  # Exemple: "postgresql://..."
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cursor = conn.cursor()

# Helper: récupérer l'état utilisateur
def get_user_state(phone):
    cursor.execute("SELECT state FROM user_states WHERE user_id = (SELECT id FROM users WHERE phone = %s)", (phone,))
    result = cursor.fetchone()
    return result[0] if result else None

# Helper: mettre à jour l'état utilisateur
def set_user_state(phone, state):
    cursor.execute("SELECT id FROM users WHERE phone = %s", (phone,))
    user = cursor.fetchone()
    if user:
        user_id = user[0]
    else:
        cursor.execute("INSERT INTO users (phone) VALUES (%s) RETURNING id", (phone,))
        user_id = cursor.fetchone()[0]
    cursor.execute("""
        INSERT INTO user_states (user_id, state, last_message, updated_at)
        VALUES (%s, %s, '', NOW())
        ON CONFLICT (user_id) DO UPDATE SET state = EXCLUDED.state, updated_at = NOW()
    """, (user_id, state))

# Endpoint WhatsApp
@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.form.get("Body", "").strip()
    from_number = request.form.get("From", "").split(":")[-1]
    resp = MessagingResponse()
    msg = resp.message()

    state = get_user_state(from_number)

    if incoming_msg.lower() == "bonjour":
        set_user_state(from_number, "menu")
        msg.body(
            "👋 *Bienvenue chez Askely Express !*\n\n"
            "Envoyez un numéro :\n"
            "1️⃣ Devenir transporteur\n"
            "2️⃣ Déclarer un départ\n"
            "3️⃣ Envoyer un colis\n"
            "4️⃣ Voir les départs disponibles\n\n"
            "Répondez par *1*, *2*, *3* ou *4*."
        )
        return str(resp)

    if state == "menu":
        if incoming_msg == "1":
            set_user_state(from_number, "register_transporteur_nom")
            msg.body("✏️ Veuillez indiquer *votre nom complet*.")
        elif incoming_msg == "2":
            set_user_state(from_number, "declare_depart_date")
            msg.body("📅 Entrez *la date de départ* (AAAA-MM-JJ).")
        elif incoming_msg == "3":
            set_user_state(from_number, "envoi_colis_description")
            msg.body("📦 Décrivez le *colis à envoyer*.")
        elif incoming_msg == "4":
            set_user_state(from_number, "recherche_depart_date")
            msg.body("📅 Entrez *la date souhaitée* (AAAA-MM-JJ).")
        else:
            msg.body("❌ Option non valide. Tapez *bonjour* pour recommencer.")
        return str(resp)

    if state == "register_transporteur_nom":
        cursor.execute("INSERT INTO transporteurs (nom, date_depart, details, created_at) VALUES (%s, %s, '', NOW())",
                       (incoming_msg, datetime.now().date()))
        set_user_state(from_number, None)
        msg.body("✅ Vous êtes maintenant *transporteur* enregistré.")
        return str(resp)

    if state == "declare_depart_date":
        try:
            date_depart = datetime.strptime(incoming_msg, "%Y-%m-%d").date()
            cursor.execute("""
                INSERT INTO transporteurs (nom, date_depart, details, created_at)
                VALUES (%s, %s, %s, NOW())
            """, (from_number, date_depart, "Départ ajouté via WhatsApp."))
            set_user_state(from_number, None)
            msg.body(f"✅ *Départ déclaré* pour le {date_depart}.")
        except ValueError:
            msg.body("❌ Format invalide. Entrez la date au format AAAA-MM-JJ.")
        return str(resp)

    if state == "envoi_colis_description":
        cursor.execute("""
            INSERT INTO colis (user_id, description, date_envoi, destinataire, created_at)
            VALUES (
                (SELECT id FROM users WHERE phone = %s),
                %s, NOW(), '', NOW()
            )
        """, (from_number, incoming_msg))
        set_user_state(from_number, None)
        msg.body("✅ *Colis enregistré* avec succès.")
        return str(resp)

    if state == "recherche_depart_date":
        try:
            date_depart = datetime.strptime(incoming_msg, "%Y-%m-%d").date()
            cursor.execute("SELECT nom FROM transporteurs WHERE date_depart = %s", (date_depart,))
            rows = cursor.fetchall()
            if rows:
                noms = "\n".join([f"• {r[0]}" for r in rows])
                msg.body(f"🚚 *Transporteurs le {date_depart}*:\n{noms}")
            else:
                msg.body(f"ℹ️ Aucun transporteur trouvé pour le {date_depart}.")
            set_user_state(from_number, None)
        except ValueError:
            msg.body("❌ Format invalide. Entrez la date au format AAAA-MM-JJ.")
        return str(resp)

    msg.body("🤖 *Je n'ai pas compris.* Tapez *bonjour* pour voir les options.")
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
