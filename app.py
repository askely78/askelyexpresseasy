from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import psycopg2
import os

app = Flask(__name__)

# Connexion PostgreSQL
DATABASE_URL = os.environ.get("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL, sslmode='require')

# États utilisateurs
state = {}

@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.form.get("Body", "").strip()
    num = request.form.get("From", "")
    resp = MessagingResponse()
    msg = resp.message()

    if num not in state:
        state[num] = {"flow": None, "step": None, "data": {}}

    current = state[num]

    if incoming_msg.lower() in ["bonjour", "salut", "hello", "hi"]:
        state[num] = {"flow": None, "step": "menu", "data": {}}
        msg.body(
            "👋 Bienvenue chez Askely Express !\n\n"
            "Que souhaitez-vous faire ?\n\n"
            "1️⃣ Envoyer un colis\n"
            "2️⃣ Devenir transporteur\n"
            "3️⃣ Publier un départ\n"
            "4️⃣ Suivre un colis\n\n"
            "Répondez par le numéro de votre choix."
        )
        return str(resp)

    # MENU SELECTION
    if current["step"] == "menu":
        if incoming_msg == "1":
            current.update({"flow": "colis", "step": "ask_name"})
            msg.body("📛 Quel est votre nom ?")
        elif incoming_msg == "2":
            current.update({"flow": "transporteur", "step": "ask_name"})
            msg.body("📛 Votre nom pour l'inscription transporteur ?")
        elif incoming_msg == "3":
            current.update({"flow": "depart", "step": "ask_name"})
            msg.body("📛 Votre nom ?")
        elif incoming_msg == "4":
            current.update({"flow": "suivi", "step": "ask_tracking"})
            msg.body("🔍 Entrez l'ID de votre envoi à suivre :")
        else:
            msg.body("❌ Choix invalide. Répondez avec 1, 2, 3 ou 4.")
        return str(resp)

    # FLOW : COLIS
    if current["flow"] == "colis":
        if current["step"] == "ask_name":
            current["data"]["name"] = incoming_msg
            current["step"] = "ask_whatsapp"
            msg.body("📞 Votre numéro WhatsApp ?")
        elif current["step"] == "ask_whatsapp":
            current["data"]["whatsapp"] = incoming_msg
            current["step"] = "ask_date"
            msg.body("📅 Date d'envoi ? (JJ/MM/AAAA)")
        elif current["step"] == "ask_date":
            current["data"]["date"] = incoming_msg
            current["step"] = "ask_desc"
            msg.body("📦 Description du colis ?")
        elif current["step"] == "ask_desc":
            current["data"]["desc"] = incoming_msg
            # Enregistrer dans la BDD
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO colis (nom_expediteur, numero_whatsapp, date_envoi, description) VALUES (%s, %s, %s, %s)",
                    (
                        current["data"]["name"],
                        current["data"]["whatsapp"],
                        current["data"]["date"],
                        current["data"]["desc"]
                    )
                )
                conn.commit()
            msg.body("✅ Votre demande a été enregistrée ! Merci.")
            state.pop(num)
        return str(resp)

    # FLOW : TRANSPORTEUR
    if current["flow"] == "transporteur":
        if current["step"] == "ask_name":
            current["data"]["name"] = incoming_msg
            current["step"] = "ask_whatsapp"
            msg.body("📞 Votre numéro WhatsApp ?")
        elif current["step"] == "ask_whatsapp":
            current["data"]["whatsapp"] = incoming_msg
            current["step"] = "ask_date"
            msg.body("📅 Date de disponibilité ? (JJ/MM/AAAA)")
        elif current["step"] == "ask_date":
            current["data"]["date"] = incoming_msg
            # Enregistrer
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO transporteurs (nom, numero_whatsapp, date_disponible) VALUES (%s, %s, %s)",
                    (
                        current["data"]["name"],
                        current["data"]["whatsapp"],
                        current["data"]["date"]
                    )
                )
                conn.commit()
            msg.body("✅ Vous êtes enregistré comme transporteur.")
            state.pop(num)
        return str(resp)

    # FLOW : DEPART
    if current["flow"] == "depart":
        if current["step"] == "ask_name":
            current["data"]["name"] = incoming_msg
            current["step"] = "ask_date"
            msg.body("📅 Date du départ ? (JJ/MM/AAAA)")
        elif current["step"] == "ask_date":
            current["data"]["date"] = incoming_msg
            # Enregistrement
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO departs (nom_transporteur, date_depart) VALUES (%s, %s)",
                    (
                        current["data"]["name"],
                        current["data"]["date"]
                    )
                )
                conn.commit()
            msg.body("✅ Votre départ est publié.")
            state.pop(num)
        return str(resp)

    # FLOW : SUIVI
    if current["flow"] == "suivi":
        if current["step"] == "ask_tracking":
            tracking_id = incoming_msg
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM colis WHERE id = %s", (tracking_id,))
                result = cur.fetchone()
            if result:
                msg.body(f"📦 Détails :\nExpéditeur: {result[1]}\nDate: {result[3]}\nDescription: {result[4]}")
            else:
                msg.body("❌ Aucun envoi trouvé avec cet ID.")
            state.pop(num)
        return str(resp)

    # Si aucune correspondance
    msg.body("🤖 Je n'ai pas compris. Tapez *bonjour* pour commencer.")
    return str(resp)

if __name__ == "__main__":
    app.run()
