
    import os, json
    import psycopg2
    from flask import Flask, request
    from twilio.twiml.messaging_response import MessagingResponse
    from datetime import datetime
    from dotenv import load_dotenv

    load_dotenv()

    app = Flask(__name__)

    # --- Database connection ---
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable not set")
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    conn.autocommit = True
    cur = conn.cursor()

    # Create tables if they don't exist
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_states (
            phone TEXT PRIMARY KEY,
            state TEXT DEFAULT 'initial',
            role  TEXT,
            data  JSONB DEFAULT '{}'::jsonb,
            updated_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS transporteurs (
            id SERIAL PRIMARY KEY,
            nom TEXT,
            date_depart DATE,
            numero TEXT
        );
    """)

    # ---------- Helper functions ----------
    def fetch_state(phone):
        cur.execute("SELECT state, role, data FROM user_states WHERE phone=%s", (phone,))
        row = cur.fetchone()
        return row if row else ("initial", None, {})

    def save_state(phone, state=None, role=None, data=None):
        # UPSERT
        cur.execute(
            """
            INSERT INTO user_states (phone, state, role, data)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (phone)
            DO UPDATE SET state = COALESCE(EXCLUDED.state, user_states.state),
                          role  = COALESCE(EXCLUDED.role , user_states.role ),
                          data  = COALESCE(EXCLUDED.data , user_states.data ),
                          updated_at = NOW()
            """, (phone, state, role, json.dumps(data or {}))
        )

    # ---------- Webhook ----------
    @app.route("/webhook", methods=["POST"])
    def whatsapp():
        text  = request.values.get("Body", "").strip()
        phone = request.values.get("From", "").split(":")[-1] or "unknown"

        state, role, data = fetch_state(phone)
        resp = MessagingResponse(); msg = resp.message()

        # ---- Reset / Welcome ----
        if text.lower() in ["bonjour", "hi", "hello", "salut"] or state == "initial":
            save_state(phone, state="ask_role", role=None, data={})
            msg.body(
                "👋 *Bienvenue chez Askely Express !*

"
                "📦 _Nous facilitons vos envois et vos trajets._

"
                "1️⃣ *Envoyer un colis*
"
                "2️⃣ *Devenir transporteur*
"
                "3️⃣ *Suivre un colis*

"
                "🧭 *Guide rapide :*
"
                "Client : tapez `1` → nom, date, transporteur, colis, suivi.
"
                "Transporteur : tapez `2` → nom, date de départ, ville.
"
                "Suivi : tapez `3` ou `suivre <référence>`.

"
                "💬 Tapez *1*, *2* ou *3* pour commencer."
            ); return str(resp)

        # ---- ask_role ----
        if state == "ask_role":
            if text == "1" or "client" in text.lower():
                save_state(phone, state="c_name", role="client", data={})
                msg.body("✒️ Entrez votre *nom complet* pour l'envoi du colis.")
            elif text == "2" or "transporteur" in text.lower():
                save_state(phone, state="t_name", role="transporteur", data={})
                msg.body("✒️ Entrez votre *nom complet* (transporteur).")
            elif text == "3" or text.startswith("suivre"):
                msg.body("🔍 Entrez votre numéro de suivi (ex: AX239DK)."); save_state(phone, state="track")
            else:
                msg.body("Répondez 1 (client) ou 2 (transporteur) ou 3 (suivi).")
            return str(resp)

        # ---------- CLIENT flow ----------
        if role == "client":
            if state == "c_name":
                data["nom"] = text.title()
                save_state(phone, state="c_date", data=data)
                msg.body("📅 Quelle *date d'envoi* ? (format AAAA-MM-JJ)")
                return str(resp)
            if state == "c_date":
                try:
                    dt = datetime.strptime(text, "%Y-%m-%d").date()
                except ValueError:
                    msg.body("❌ Format invalide. Utilisez AAAA-MM-JJ."); return str(resp)
                data["date"] = str(dt)
                # chercher transporteurs
                cur.execute("SELECT nom, numero FROM transporteurs WHERE date_depart=%s", (dt,))
                rows = cur.fetchall()
                if rows:
                    options = "\n".join([f"{i+1}. {r[0]} ({r[1]})" for i, r in enumerate(rows)])
                    msg.body(f"🚚 Transporteurs dispos le {dt} :\n{options}\nRépondez par le *nom* choisi.")
                    save_state(phone, state="c_choose", data=data)
                else:
                    msg.body("Aucun transporteur à cette date. Saisir une autre date ou tapez *bonjour*.")
                return str(resp)
            if state == "c_choose":
                data["transporteur"] = text.title()
                ref = f"AX{datetime.utcnow().strftime('%H%M%S')}"
                msg.body(f"✅ Votre demande est enregistrée avec référence *{ref}*. "
                         f"Le transporteur {data['transporteur']} vous contactera. Merci !")
                save_state(phone)  # reset
                return str(resp)

        # ---------- TRANSPORTEUR flow ----------
        if role == "transporteur":
            if state == "t_name":
                data["nom"] = text.title()
                save_state(phone, state="t_date", data=data)
                msg.body("📅 Quelle est votre *date de départ* ? (AAAA-MM-JJ)")
                return str(resp)
            if state == "t_date":
                try:
                    dt = datetime.strptime(text, "%Y-%m-%d").date()
                except ValueError:
                    msg.body("❌ Format invalide. Utilisez AAAA-MM-JJ."); return str(resp)
                data["date_depart"] = str(dt)
                # save in transporteurs table
                cur.execute(
                    "INSERT INTO transporteurs (nom, date_depart, numero) VALUES (%s,%s,%s) "
                    "ON CONFLICT DO NOTHING", (data["nom"], dt, phone))
                msg.body("📝 Merci ! Votre trajet est enregistré. Vous serez notifié des colis.")
                save_state(phone)  # reset
                return str(resp)

        # ---------- Tracking ----------
        if state == "track":
            msg.body(f"📦 Suivi {text.upper()} : votre colis est en transit (exemple).")
            save_state(phone)  # reset
            return str(resp)

        # ---------- Fallback ----------
        msg.body("🤖 Je n’ai pas compris. Tapez *bonjour* pour recommencer.")
        return str(resp)


    if __name__ == "__main__":
        app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
