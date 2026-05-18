# -*- coding: utf-8 -*-
import os
import re
import json
import base64
import requests
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# ============================================================
# CONFIGURATION
# ============================================================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "EAASp22f3wJMBRXuVVU2AzrHK6dOGAknidYlFNZBJDygimEyJeS18uEpdEU8b0JoLsenCnb9WuSrm2Ssw1dPuZAfPty86tw2EnJHOIFKRu0DMs98dwd5PARQhqcpJ1IuOFMsQK8GqVprd9DfZAXGGPgyJpBhCpivhZBK7rlu5En65Yf9zj4vMZBZBIFTNZCbpZAYCfRnPLvAnTZA3cVs2J7A1XP86rYQWWrYkrJgQiEiudA8fsgkF6emiItxQIpZCyZCJwsBi2OpZCvfNHDTSq0Jxk9y3")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1031404513398168")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "topauto2024secret")
CONSEILLER_TEL = os.environ.get("CONSEILLER_WHATSAPP", "212774057668")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "1zym75m5DWfKI7-t4tByidTrBXe56jeZqS0eG0_Qp95g")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON", "")

SHEET_MAP = {
    "commercial": "Leads_Commerciaux",
    "sav_atelier": "SAV_Atelier",
    "pieces": "Pieces_Rechange",
    "sav_document": "SAV_Documents",
    "financement": "Financement_Assurance",
    "reclamation": "Reclamations"
}

# ============================================================
# GOOGLE SHEETS
# ============================================================
def enregistrer_lead_sheets(telephone, langue, lead_data):
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        service = build("sheets", "v4", credentials=creds)
        type_lead = lead_data.get("type", "commercial")
        sheet_name = SHEET_MAP.get(type_lead, "Leads_Commerciaux")
        now = datetime.now()

        result = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f"{sheet_name}!A:O"
        ).execute()
        rows = result.get("values", [])

        existing_row_index = None
        for i, r in enumerate(rows):
            if len(r) > 11 and r[11] == telephone:
                existing_row_index = i + 1
                break

        row = [
            now.strftime("%Y%m%d%H%M%S"), now.strftime("%d/%m/%Y %H:%M"),
            lead_data.get("prenom", ""), lead_data.get("tel", ""),
            lead_data.get("modele", lead_data.get("vehicule", "")),
            lead_data.get("type_financement", lead_data.get("nature", "")),
            lead_data.get("chassis", ""), type_lead,
            lead_data.get("immat", ""), lead_data.get("nature", ""),
            lead_data.get("description", ""), telephone, langue, "WhatsApp Bot", "NOUVEAU"
        ]

        if existing_row_index:
            service.spreadsheets().values().update(
                spreadsheetId=GOOGLE_SHEET_ID,
                range=f"{sheet_name}!A{existing_row_index}:O{existing_row_index}",
                valueInputOption="USER_ENTERED",
                body={"values": [row]}
            ).execute()
            print(f"[SHEETS] Lead mis a jour ligne {existing_row_index}")
        else:
            service.spreadsheets().values().append(
                spreadsheetId=GOOGLE_SHEET_ID, range=f"{sheet_name}!A:O",
                valueInputOption="USER_ENTERED", body={"values": [row]}).execute()
            print(f"[SHEETS] Nouveau lead enregistre dans {sheet_name}")

        return True
    except Exception as e:
        print(f"[SHEETS] Erreur: {e}")
        return False


# ============================================================
# ANALYSE PHOTO VEHICULE PAR IA
# ============================================================
def telecharger_image_whatsapp(media_id):
    """Telecharger une image depuis WhatsApp et la convertir en base64"""
    try:
        # Etape 1 : recuperer l'URL de l'image
        url_media = f"https://graph.facebook.com/v20.0/{media_id}"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        resp = requests.get(url_media, headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f"[PHOTO] Erreur recuperation URL: {resp.status_code}")
            return None
        media_url = resp.json().get("url")
        if not media_url:
            return None

        # Etape 2 : telecharger l'image
        resp_img = requests.get(media_url, headers=headers, timeout=15)
        if resp_img.status_code != 200:
            print(f"[PHOTO] Erreur telechargement image: {resp_img.status_code}")
            return None

        # Convertir en base64
        img_b64 = base64.b64encode(resp_img.content).decode("utf-8")
        content_type = resp_img.headers.get("Content-Type", "image/jpeg")
        print(f"[PHOTO] Image telechargee ({len(resp_img.content)} bytes)")
        return img_b64, content_type

    except Exception as e:
        print(f"[PHOTO] Erreur: {e}")
        return None


def analyser_photo_vehicule(img_b64, content_type, langue="FR"):
    """Analyser une photo de vehicule avec Groq Vision"""
    try:
        if langue == "AR":
            prompt = """أنت مساعد ذكاء اصطناعي متخصص في تشخيص مشاكل السيارات لوكالة Top Auto Mohammedia.
حلل هذه الصورة بدقة وأجب بالعربية:
1. ما الذي تراه في الصورة؟
2. ما هي المشكلة أو الحالة المحتملة؟
3. ما هي توصيتك؟ (صيانة عادية / إصلاح عاجل / تدخل الورشة)
كن دقيقاً ومهنياً. أنهِ بـ: شكرا على ثقتك."""
        else:
            prompt = """Tu es un expert en diagnostic automobile pour Top Auto Mohammedia (concessionnaire Renault et Dacia).
Analyse cette image avec precision et reponds en francais :
1. Que vois-tu sur cette image ?
2. Quel est le probleme ou l etat detecte ?
3. Quelle est ta recommandation ? (entretien normal / reparation urgente / intervention atelier necessaire)
Sois precis et professionnel. Termine par : Merci pour votre confiance."""

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{content_type};base64,{img_b64}"
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]

        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                "messages": messages,
                "max_tokens": 600,
                "temperature": 0.3
            },
            timeout=30
        )
        print(f"[VISION] Status: {resp.status_code}")
        if resp.status_code != 200:
            print(f"[VISION] Erreur: {resp.text[:200]}")
            return None
        return resp.json()["choices"][0]["message"]["content"]

    except Exception as e:
        print(f"[VISION] Erreur analyse: {e}")
        return None


# ============================================================
# SESSION MANAGEMENT
# ============================================================
sessions = {}

SYSTEM_PROMPT = """Tu es l assistant virtuel de Top Auto Mohammedia (Renault et Dacia, Mohammedia Maroc).

COMPORTEMENT STRICT :
- Si le client envoie uniquement bonjour ou salam ou hi ou مرحبا -> NE PAS repondre par du texte. Retourner exactement : BOUTONS_BIENVENUE|||RIEN
- Pour TOUS les autres messages -> repondre IMMEDIATEMENT et DIRECTEMENT a la demande

ETABLISSEMENT :
Adresse : Q.I Bd Sidi Mohamed Ben Abdellah, 208000 Mohammedia
Tel Renault : 05 23 30 31 94 | Dacia : 05 23 30 31 95
Horaires : Lun-Ven 8h00-18h30 | Sam Renault 8h30-13h00 | Sam Dacia 8h30-15h00 | Dim ferme
GPS : 33.683384 N, 7.409769 W

GAMME DACIA :
Spring electrique (24.3kWh 70/100ch Essential/Extreme) | Sandero Streetway (2026 ecran10p 1.0SCe65ch/1.0TCe100ch/1.5dCi102ch Essential-Journey) | Sandero Stepway (17cm 1.0TCe100ch/1.5dCi102ch CVT) | Logan (coffre528L 1.0SCe65ch/1.0TCe100ch/1.5dCi102ch) | Jogger (5ou7pl coffre1807L HEV140ch) | Duster 2025 (1.5dCi115ch/1.3TCe130ch Essential-Extreme) | Bigster 2025 (HEV155ch toitPano Essential-Journey)

GAMME RENAULT VP :
Clio5/6 (1.0TCe100ch/diesel/ETech145ch Equilibre-EspritAlpine) | Captur (OpenRLink ETech145ch) | R5 ETech (electrique 40kWh120ch/52kWh150ch 400km) | Express (diesel 95/115ch) | Megane Sedan (coffre475L diesel) | Megane ETech (electrique 60kWh 450km 220ch) | Arkana (ETech145ch 4.5L) | Austral (ETech200ch OpenRLink 2025) | Kardian (SOMACA 1.0TCe100ch/1.5BluedCi102ch)

GAMME RENAULT VU :
Express Van (800kg 3.3m3 dCi75ch) | Trafic (Combi9pl 1400kg 2.0dCi150ch) | Master (8-17m3 1700kg 2.3dCi145/180ch)

SAV :
Agree Renault/Dacia. WinTech/OBD. Mecanique/Carrosserie/Peinture. Devis gratuit 24h.
RDV Renault : concessionnaire.renault.ma/top-auto-mohammedia.html
RDV Dacia : reseau.dacia.ma/top-auto-mohammedia.html

FINANCEMENT Mobilize :
Credit 12-72mois | ZEN | Easy | Gratuit 0% | LOA
Assurances : RC / Tous Risques / Perte Totale / Deces-Invalidite / garantie 5 ans

DOCUMENTS SAV :
Main levee : CIN/passeport + contrat vente + attestation fin credit Mobilize + chassis
Facture : CIN/passeport + chassis + motif (perte/administration/assurance)
Carte grise : prenom+nom + CIN + chassis

REGLES :
1. PRIX : Jamais de prix. Dire : Pour le meilleur tarif personnalise, contactez notre equipe.
2. RDV ET TEST DRIVE : Essai gratuit sans engagement. Donner les deux liens + collecter prenom et telephone
3. DOCUMENTS SAV : Lister justificatifs selon type + collecter prenom/telephone/chassis un par un
4. RECLAMATIONS : Empathie totale + collecter prenom/telephone/immat/description un par un + confirmer reponse 48h
5. FINANCEMENT : Presenter options sans taux ni mensualite + orienter conseiller
6. CATALOGUE : Afficher toute la gamme avec details techniques.

COLLECTE INFOS - UNE SEULE QUESTION A LA FOIS :
D abord prenom uniquement. Puis telephone. Puis modele si necessaire.
Ne jamais poser deux questions dans le meme message.

CONFIRMATION LEAD - QUAND TU AS PRENOM ET TELEPHONE :
Terminer le message par un recapitulatif :
"Recapitulatif :
- Prenom : [prenom]
- Telephone : [tel]
Notre equipe vous contactera tres prochainement."

LANGUE :
Caracteres arabes -> reponds UNIQUEMENT en arabe
Par defaut -> francais

FORMAT REPONSE OBLIGATOIRE :
TOUJOURS deux parties separees par |||
Format : TEXTE_VISIBLE_CLIENT|||TAG_INTERNE

TAG possible :
|||RIEN
|||LEAD:prenom=X|tel=X|modele=X|type=commercial
|||LEAD:prenom=X|tel=X|vehicule=X|intervention=X|type=sav_atelier
|||LEAD:prenom=X|tel=X|chassis=X|type_doc=X|type=sav_document
|||LEAD:prenom=X|tel=X|modele=X|type_financement=X|type=financement
|||LEAD:prenom=X|tel=X|immat=X|nature=X|description=X|type=reclamation
|||FIN

REGLES FORMAT :
- JAMAIS ecrire ||| ou LEAD ou TAG dans le texte visible
- Si prenom ou tel manquants -> |||RIEN
- Sauvegarder LEAD seulement si prenom ET tel sont reels
- Terminer par : Merci pour votre confiance. (FR) ou شكرا على ثقتك. (AR)
- Aucun emoji"""


# ============================================================
# WHATSAPP HELPERS
# ============================================================
def get_session(telephone):
    if telephone not in sessions:
        sessions[telephone] = {"historique": [], "langue": "FR", "infos_collectees": {}}
    return sessions[telephone]


def envoyer_whatsapp(telephone, message):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": telephone, "type": "text", "text": {"body": message}}
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        print(f"[WA] Text {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        print(f"[WA] Erreur: {e}")
        return False


def envoyer_boutons(telephone, body_text, buttons):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    btn_list = [{"type": "reply", "reply": {"id": b["id"], "title": b["title"]}} for b in buttons[:3]]
    data = {
        "messaging_product": "whatsapp",
        "to": telephone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": btn_list}
        }
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        print(f"[WA] Boutons {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        print(f"[WA] Erreur boutons: {e}")
        return False


def envoyer_bienvenue(telephone):
    envoyer_boutons(
        telephone,
        "Bienvenue chez Top Auto Mohammedia, votre concessionnaire officiel Renault et Dacia !\nComment puis-je vous aider aujourd'hui ?",
        [
            {"id": "btn_catalogue", "title": "Catalogue"},
            {"id": "btn_sav", "title": "SAV & Atelier"},
            {"id": "btn_autre", "title": "Autre"}
        ]
    )


def envoyer_catalogue(telephone):
    envoyer_boutons(
        telephone,
        "Quelle gamme vous interesse ?",
        [
            {"id": "btn_renault", "title": "Renault"},
            {"id": "btn_dacia", "title": "Dacia"},
            {"id": "btn_les_deux", "title": "Les deux"}
        ]
    )


def notifier_conseiller(telephone, nom, lead_data):
    type_lead = lead_data.get("type", "commercial")
    lignes = [f"--- NOUVEAU LEAD {type_lead.upper()} ---", f"Client WA : {telephone}",
              f"Nom : {nom}", f"Prenom : {lead_data.get('prenom', 'NC')}",
              f"Tel : {lead_data.get('tel', 'NC')}"]
    for k, label in [("modele","Modele"),("vehicule","Vehicule"),("chassis","Chassis"),
                     ("type_doc","Type doc"),("immat","Immat"),("nature","Nature"),("description","Description")]:
        if lead_data.get(k): lignes.append(f"{label} : {lead_data[k]}")
    lignes.append(f"Statut : {'NOUVEAU - 48h' if type_lead == 'reclamation' else 'A RAPPELER'}")
    envoyer_whatsapp(CONSEILLER_TEL, "\n".join(lignes))


def extraire_lead(tag):
    if not tag.startswith("LEAD:"):
        return None
    lead = {}
    for partie in tag.replace("LEAD:", "").split("|"):
        idx = partie.find("=")
        if idx > 0:
            k, v = partie[:idx].strip(), partie[idx+1:].strip()
            if k and v and v not in ["X", "", "null"]:
                lead[k] = v
    return lead if lead.get("prenom") and lead.get("tel") else None


def appeler_groq(historique, texte):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + historique + [{"role": "user", "content": texte}]
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": "llama-3.3-70b-versatile", "messages": messages, "max_tokens": 900, "temperature": 0.3},
        timeout=30
    )
    print(f"[GROQ] Status: {resp.status_code}")
    if resp.status_code != 200:
        raise Exception(f"Groq error {resp.status_code}: {resp.text[:200]}")
    return resp.json()["choices"][0]["message"]["content"]


def traiter_reponse_groq(raw):
    texte, tag = raw.strip(), "RIEN"
    if "|||" in raw:
        idx = raw.rfind("|||")
        texte, tag = raw[:idx].strip(), raw[idx+3:].strip()
    texte = re.sub(r'\|\|\|[\s\S]*', '', texte)
    texte = re.sub(r'LEAD:[\w=|.\s\u0600-\u06FF]*', '', texte)
    texte = texte.replace("|||", "").replace("RIEN", "").replace("FIN", "").strip()
    return texte, tag


# ============================================================
# ROUTES WEBHOOK
# ============================================================
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("[WEBHOOK] Verification reussie")
        return challenge, 200
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def receive_message():
    try:
        body = request.get_json()
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return jsonify({"status": "ok"}), 200

        message = messages[0]
        telephone = message.get("from")
        nom = value.get("contacts", [{}])[0].get("profile", {}).get("name", "Client")
        msg_type = message.get("type")

        session = get_session(telephone)

        # ============================================================
        # TRAITEMENT IMAGE - Analyse photo vehicule
        # ============================================================
        if msg_type == "image":
            print(f"[PHOTO] Image recue de {telephone}")
            envoyer_whatsapp(telephone, "Analyse de votre image en cours, veuillez patienter...")

            media_id = message.get("image", {}).get("id")
            if not media_id:
                envoyer_whatsapp(telephone, "Impossible de traiter cette image. Merci pour votre confiance.")
                return jsonify({"status": "ok"}), 200

            result = telecharger_image_whatsapp(media_id)
            if not result:
                envoyer_whatsapp(telephone, "Impossible de telecharger l image. Appelez-nous au 05 23 30 31 94. Merci pour votre confiance.")
                return jsonify({"status": "ok"}), 200

            img_b64, content_type = result
            diagnostic = analyser_photo_vehicule(img_b64, content_type, session.get("langue", "FR"))

            if diagnostic:
                envoyer_whatsapp(telephone, diagnostic)
                # Proposer un RDV apres le diagnostic
                envoyer_boutons(
                    telephone,
                    "Souhaitez-vous prendre un rendez-vous atelier ?",
                    [
                        {"id": "btn_sav", "title": "Prendre RDV"},
                        {"id": "btn_autre", "title": "Autre question"},
                        {"id": "btn_catalogue", "title": "Voir catalogue"}
                    ]
                )
            else:
                envoyer_whatsapp(telephone, "Analyse non disponible. Contactez-nous au 05 23 30 31 94 pour un diagnostic. Merci pour votre confiance.")

            return jsonify({"status": "ok"}), 200

        # ============================================================
        # TRAITEMENT TEXTE ET BOUTONS
        # ============================================================
        if msg_type == "text":
            texte = message.get("text", {}).get("body", "").strip()
            button_id = None
        elif msg_type == "interactive":
            interactive = message.get("interactive", {})
            if interactive.get("type") == "button_reply":
                button_id = interactive["button_reply"]["id"]
                texte = interactive["button_reply"]["title"]
            else:
                return jsonify({"status": "ok"}), 200
        else:
            return jsonify({"status": "ok"}), 200

        if not texte:
            return jsonify({"status": "ok"}), 200

        print(f"\n[MSG] {telephone} ({nom}): {texte}")

        if any('\u0600' <= c <= '\u06FF' for c in texte):
            session["langue"] = "AR"

        texte_lower = texte.lower().strip()
        salutations = ["bonjour", "salam", "salut", "hi", "hello", "bonsoir", "مرحبا", "السلام"]

        if texte_lower in salutations:
            envoyer_bienvenue(telephone)
            return jsonify({"status": "ok"}), 200

        if msg_type == "interactive":
            if button_id == "btn_catalogue":
                envoyer_catalogue(telephone)
                return jsonify({"status": "ok"}), 200
            elif button_id == "btn_renault":
                texte = "Montre moi la gamme Renault complete"
            elif button_id == "btn_dacia":
                texte = "Montre moi la gamme Dacia complete"
            elif button_id == "btn_les_deux":
                texte = "Montre moi toute la gamme Renault et Dacia"
            elif button_id == "btn_sav":
                texte = "Je veux prendre un rendez-vous SAV atelier"
            elif button_id == "btn_autre":
                envoyer_whatsapp(telephone, "Je suis a votre disposition. Dites-moi comment je peux vous aider : financement, documents, reclamation, localisation ou autre question.")
                return jsonify({"status": "ok"}), 200

        raw = appeler_groq(session["historique"], texte)
        texte_client, tag = traiter_reponse_groq(raw)

        if "BOUTONS_BIENVENUE" in texte_client or "BOUTONS_BIENVENUE" in tag:
            envoyer_bienvenue(telephone)
            return jsonify({"status": "ok"}), 200

        if not texte_client or len(texte_client) < 5:
            texte_client = "Desolee, une erreur est survenue. Appelez-nous au 05 23 30 31 94. Merci pour votre confiance."

        print(f"[BOT]: {texte_client[:100]}...")
        print(f"[TAG]: {tag}")

        session["historique"].append({"role": "user", "content": texte})
        session["historique"].append({"role": "assistant", "content": texte_client})

        if len(session["historique"]) > 20:
            session["historique"] = session["historique"][-20:]

        envoyer_whatsapp(telephone, texte_client)

        if tag.startswith("LEAD:"):
            lead_data = extraire_lead(tag)
            if lead_data:
                print(f"[LEAD] {lead_data}")
                session["infos_collectees"].update(lead_data)
                notifier_conseiller(telephone, nom, lead_data)
                enregistrer_lead_sheets(telephone, session["langue"], lead_data)

        if tag == "FIN":
            del sessions[telephone]

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"[ERREUR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 200


@app.route("/", methods=["GET"])
def home():
    return "TopAuto WhatsApp Bot - Online", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[START] TopAuto Bot sur port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
