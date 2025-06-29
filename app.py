from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime
from openai import OpenAI

# Configuration Flask
app = Flask(__name__)

# Connexion PostgreSQL
DATABASE_URL = os.environ.get("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL, sslmode="require")

# Connexion OpenAI
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Récupérer ou créer un utilisateur
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

# Récupérer l'état
def get_state(user_id):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM user_states WHERE user_id = %s", (user_id,))
        return cur.fetchone()

# Corriger une ville avec GPT
def correct_text(input_text):
    prompt = (
        f"Corrige la faute de frappe suivante, retourne uniquement le mot corrigé sans phrase : {input_text}"
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Tu es un correcteur orthographique."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )
    return response.choices[0].message.content.strip()

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    phone = request.values.get("From", "").split(":")[-1]
    resp = MessagingResponse()
    msg = resp.message()

    user = get_or_create_user(phone)
    state = get_state(user["id"])

    # Accueil si "bonjour" ou "menu"
    if incoming_msg.lower() in ["bonjour", "menu"]:
        set_state(user["id"], "menu")
        msg.body(
            "👋 Bonjour et bienvenue chez *Askely Express* !\n\n"
            "✅ Chercher un transporteur\n"
            "✅ Publier un départ\n"
            "✅ Noter un transporteur\n"
            "✅ Recevoir des rappels\n\n"
            "✨ Tapez le numéro correspondant :\n"
            "1️⃣ Je suis *Client*\n"
            "2️⃣ Je suis *Transporteur*"
        )
        return str(resp)

    # Menu principal
    if state and state["state"] == "menu":
        if incoming_msg == "1":
            set_state(user["id"], "search_date")
            msg.body("📅 Entrez la date souhaitée du départ (AAAA-MM-JJ) :")
        elif incoming_msg == "2":
            if user["role"] != "transporteur":
                set_state(user["id"], "register_transporteur")
                msg.body("🚚 *Inscription transporteur*\n\nVeuillez saisir votre *nom complet* :")
            else:
                set_state(user["id"], "publish_date")
                msg.body("📅 Entrez la date de votre départ (AAAA-MM-JJ) :")
        else:
            msg.body("❗ Choix invalide. Tapez 1 ou 2.")
        return str(resp)

    # Inscription transporteur
    if state and state["state"] == "register_transporteur":
        nom = incoming_msg
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET nom=%s, role='transporteur' WHERE id=%s", (nom, user["id"]))
            conn.commit()
        set_state(user["id"], "publish_date")
        msg.body("✅ Inscription enregistrée.\n\n📅 Entrez la date de votre départ (AAAA-MM-JJ) :")
        return str(resp)

    # Publication départ
    if state and state["state"] == "publish_date":
        try:
            datetime.strptime(incoming_msg, "%Y-%m-%d")
            set_state(user["id"], "publish_ville_depart", incoming_msg)
            msg.body("📍 Entrez la *ville de départ* :")
        except ValueError:
            msg.body("❗ Format invalide. Utilisez AAAA-MM-JJ.")
        return str(resp)

    if state and state["state"] == "publish_ville_depart":
        date = state["last_message"]
        ville_depart = correct_text(incoming_msg)
        set_state(user["id"], "publish_ville_dest", f"{date}|{ville_depart}")
        msg.body("🏁 Entrez la *ville de destination* :")
        return str(resp)

    if state and state["state"] == "publish_ville_dest":
        date, ville_depart = state["last_message"].split("|")
        ville_dest = correct_text(incoming_msg)
        set_state(user["id"], "publish_desc", f"{date}|{ville_depart}|{ville_dest}")
        msg.body("✏️ Entrez une *description* du départ :")
        return str(resp)

    if state and state["state"] == "publish_desc":
        date, ville_depart, ville_dest = state["last_message"].split("|")
        description = incoming_msg
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO departs (transporteur_id, date_depart, ville_depart, ville_destination, description)
                VALUES (%s, %s, %s, %s, %s)
            """, (user["id"], date, ville_depart, ville_dest, description))
            conn.commit()
        set_state(user["id"], "menu")
        msg.body(
            "✅ *Votre départ a été publié.*\n\n"
            f"📅 {date}\n"
            f"🏁 {ville_depart} ➡️ {ville_dest}\n"
            f"💬 {description}\n\nTapez *menu* pour revenir."
        )
        return str(resp)

    # Recherche client
    if state and state["state"] == "search_date":
        try:
            datetime.strptime(incoming_msg, "%Y-%m-%d")
            set_state(user["id"], "search_ville_depart", incoming_msg)
            msg.body("📍 Entrez la *ville de départ* :")
        except ValueError:
            msg.body("❗ Format invalide.")
        return str(resp)

    if state and state["state"] == "search_ville_depart":
        date = state["last_message"]
        ville_depart = correct_text(incoming_msg)
        set_state(user["id"], "search_ville_dest", f"{date}|{ville_depart}")
        msg.body("🏁 Entrez la *ville de destination* :")
        return str(resp)

    if state and state["state"] == "search_ville_dest":
        date, ville_depart = state["last_message"].split("|")
        ville_dest = correct_text(incoming_msg)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT d.*, u.nom, u.phone_number,
                       COALESCE(ROUND(AVG(a.note),1), 'Non noté') AS moyenne,
                       (SELECT avis FROM avis WHERE transporteur_id=u.id ORDER BY created_at DESC LIMIT 1) AS dernier_avis
                FROM departs d
                JOIN users u ON d.transporteur_id = u.id
                LEFT JOIN avis a ON a.transporteur_id = u.id
                WHERE d.date_depart=%s AND d.ville_depart ILIKE %s AND d.ville_destination ILIKE %s
                GROUP BY d.id, u.id
            """, (date, ville_depart, ville_dest))
            results = cur.fetchall()
        if results:
            response = "🚚 *Transporteurs disponibles* :\n\n"
            for r in results:
                response += (
                    f"• *{r['nom']}*\n"
                    f"📅 {r['date_depart']} – {r['ville_depart']} ➡️ {r['ville_destination']}\n"
                    f"💬 {r['description']}\n"
                    f"⭐ Note : {r['moyenne']}\n"
                    f"📝 Avis : {r['dernier_avis'] or 'Aucun avis'}\n"
                    f"📲 WhatsApp : {r['phone_number']}\n\n"
                )
            response += "✅ Pour noter un transporteur, tapez 'note NOM_TRANSPORTEUR votre avis et la note sur 5'."
        else:
            response = "❗ Aucun transporteur trouvé."
        set_state(user["id"], "menu")
        msg.body(response)
        return str(resp)

    # Notation
    if incoming_msg.lower().startswith("note "):
        try:
            parts = incoming_msg.split(" ", 2)
            nom = parts[1]
            contenu = parts[2]
            note = int("".join([c for c in contenu if c.isdigit()]) or "0")
            avis = contenu.replace(str(note), "").strip()
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE nom ILIKE %s", (nom,))
                res = cur.fetchone()
                if res:
                    cur.execute(
                        "INSERT INTO avis (transporteur_id, note, avis) VALUES (%s, %s, %s)",
                        (res[0], note, avis)
                    )
                    conn.commit()
                    msg.body("✅ Votre avis a été enregistré.")
                else:
                    msg.body("❗ Transporteur introuvable.")
        except Exception:
            msg.body("❗ Format incorrect. Exemple : note Karim Très ponctuel 5")
        return str(resp)

    msg.body("🤖 Je n'ai pas compris. Tapez *menu* pour recommencer.")
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
