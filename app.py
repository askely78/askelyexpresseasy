from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime
from langdetect import detect

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

# Mettre à jour l'état de conversation
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

# Traduction simple
def translate(text, lang):
    translations = {
        "fr": text,
        "en": {
            "welcome": "👋 *Welcome to Askely Express*!\n\nI can help you:\n1️⃣ Search for a carrier\n2️⃣ Register and publish departures",
            "choice": "Type 1 or 2 to continue.",
            "invalid": "❗ Invalid choice. Please type 1 or 2.",
            "date": "📅 Enter the *departure date* (YYYY-MM-DD):",
            "city": "📍 Enter the *destination city*:",
            "desc": "✏️ Enter a *description*:",
            "saved": "✅ Your departure has been published.",
            "menu": "👋 *Main menu*\n1️⃣ Search for carrier\n2️⃣ Register as carrier",
            "not_understood": "🤖 I didn't understand. Type *menu* to return.",
        },
        "ar": {
            "welcome": "👋 *مرحبا بك في Askely Express*!\n\nيمكنني مساعدتك:\n1️⃣ البحث عن ناقل\n2️⃣ التسجيل وإضافة رحلة",
            "choice": "اكتب 1 أو 2 للمتابعة.",
            "invalid": "❗ اختيار غير صالح. اكتب 1 أو 2.",
            "date": "📅 أدخل *تاريخ الرحلة* (YYYY-MM-DD):",
            "city": "📍 أدخل *مدينة الوصول*:",
            "desc": "✏️ أدخل *وصف الرحلة*:",
            "saved": "✅ تم حفظ الرحلة.",
            "menu": "👋 *القائمة الرئيسية*\n1️⃣ البحث عن ناقل\n2️⃣ التسجيل كناقل",
            "not_understood": "🤖 لم أفهم. اكتب *menu* للرجوع.",
        }
    }
    return translations.get(lang, translations["fr"]).get(text, text)

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    phone = request.values.get("From", "").split(":")[-1]
    lang = detect(incoming_msg) if incoming_msg else "fr"
    resp = MessagingResponse()
    msg = resp.message()

    user = get_or_create_user(phone)
    state = get_state(user["id"])

    # Si pas d'état, menu d'accueil
    if not state:
        set_state(user["id"], "menu")
        msg.body(translate("welcome", lang))
        return str(resp)

    # Menu principal
    if state["state"] == "menu":
        if incoming_msg == "1":
            set_state(user["id"], "search_date")
            msg.body(translate("date", lang))
        elif incoming_msg == "2":
            if user["role"] != "transporteur":
                set_state(user["id"], "register_transporteur")
                msg.body("🚚 *Inscription transporteur*\n\nEntrez votre *nom complet* :")
            else:
                set_state(user["id"], "publish_date")
                msg.body("📝 Entrez la *date du départ* (YYYY-MM-DD):")
        else:
            msg.body(translate("invalid", lang))
        return str(resp)

    # Inscription transporteur
    if state["state"] == "register_transporteur":
        nom = incoming_msg
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET nom = %s, role = 'transporteur' WHERE id = %s", (nom, user["id"]))
            conn.commit()
        set_state(user["id"], "publish_date")
        msg.body("✅ Inscription enregistrée.\n\n📝 Entrez la *date du départ* (YYYY-MM-DD):")
        return str(resp)

    # Publication - Date
    if state["state"] == "publish_date":
        try:
            datetime.strptime(incoming_msg, "%Y-%m-%d")
            set_state(user["id"], "publish_ville_depart", incoming_msg)
            msg.body("🏠 Entrez la *ville de départ* :")
        except ValueError:
            msg.body("❗ Format invalide. Utilisez YYYY-MM-DD.")
        return str(resp)

    # Publication - Ville départ
    if state["state"] == "publish_ville_depart":
        date = state["last_message"]
        set_state(user["id"], "publish_ville_dest", f"{date}|{incoming_msg}")
        msg.body(translate("city", lang))
        return str(resp)

    # Publication - Ville destination
    if state["state"] == "publish_ville_dest":
        parts = state["last_message"].split("|")
        set_state(user["id"], "publish_desc", f"{parts[0]}|{parts[1]}|{incoming_msg}")
        msg.body(translate("desc", lang))
        return str(resp)

    # Publication - Description
    if state["state"] == "publish_desc":
        parts = state["last_message"].split("|")
        date, ville_dep, ville_dest = parts
        desc = incoming_msg
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO departs (transporteur_id, date_depart, ville_depart, ville_destination, description)
                VALUES (%s, %s, %s, %s, %s)
            """, (user["id"], date, ville_dep, ville_dest, desc))
            conn.commit()
        set_state(user["id"], "menu")
        msg.body(translate("saved", lang))
        return str(resp)

    # Recherche date
    if state["state"] == "search_date":
        try:
            datetime.strptime(incoming_msg, "%Y-%m-%d")
            set_state(user["id"], "search_ville_depart", incoming_msg)
            msg.body("🏠 Entrez la *ville de départ* :")
        except ValueError:
            msg.body("❗ Format invalide. Utilisez YYYY-MM-DD.")
        return str(resp)

    # Recherche ville départ
    if state["state"] == "search_ville_depart":
        set_state(user["id"], "search_ville_dest", f"{state['last_message']}|{incoming_msg}")
        msg.body(translate("city", lang))
        return str(resp)

    # Recherche ville destination
    if state["state"] == "search_ville_dest":
        date, ville_dep = state["last_message"].split("|")
        ville_dest = incoming_msg
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT d.*, u.nom, u.phone_number,
                COALESCE(avg(a.note), 0) as note_moyenne,
                (SELECT commentaire FROM avis_transporteurs a2 WHERE a2.transporteur_id = u.id ORDER BY created_at DESC LIMIT 1) as dernier_avis
                FROM departs d
                JOIN users u ON d.transporteur_id = u.id
                LEFT JOIN avis_transporteurs a ON a.transporteur_id = u.id
                WHERE d.date_depart = %s AND d.ville_depart ILIKE %s AND d.ville_destination ILIKE %s
                GROUP BY d.id, u.id
            """, (date, ville_dep, ville_dest))
            results = cur.fetchall()

        if results:
            response = "🚚 *Transporteurs disponibles* :\n\n"
            for r in results:
                stars = "⭐" * int(round(r["note_moyenne"] or 0))
                response += (
                    f"• *{r['nom']}*\n"
                    f"📅 {r['date_depart']} - 🏠 {r['ville_depart']} ➡️ {r['ville_destination']}\n"
                    f"💬 {r['description']}\n"
                    f"{stars}\n"
                    f"📝 Dernier avis : {r['dernier_avis'] or 'Aucun avis'}\n"
                    f"📲 WhatsApp: {r['phone_number']}\n\n"
                )
        else:
            response = "❗ Aucun transporteur trouvé."
        set_state(user["id"], "menu")
        msg.body(response)
        return str(resp)

    if incoming_msg.lower() == "menu":
        set_state(user["id"], "menu")
        msg.body(translate("menu", lang))
        return str(resp)

    msg.body(translate("not_understood", lang))
    return str(resp)

if __name__ == "__main__":
    app.run(debug=True, port=10000)
