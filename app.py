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
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "EAASp22f3wJMBRpA669qgulmfKLlq2lrrjVmMdHyeM4whaBCFV7qNP0J9z5Bc8GVzXpjFXfPVlrmcJrAIeADN81Nj9XWoQLJVhKSABOba5nDEnoJhL9JpvSMT4mgZBx83z5vmTjAQdwufbSes24DJVcbtCnjuW1hLTVLKTsopqg8mOYS7XirLnF7Gt2F8j7hdD99YR8Qvh96bk46JTnxT8XVzZBPNBBG8ayi7GIwdaZAWQGVkmC96Beyxhht2AfoblbmwxhkNyNPf3gINbmE")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1031404513398168")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "topauto2024secret")
CONSEILLER_TEL = os.environ.get("CONSEILLER_WHATSAPP", "212774057668")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "1ldysDBq6mODT8G2UF1uV7NSV2n_DLUfZPNePIHJSbro")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON", "")

# ============================================================
# GOOGLE SHEETS — MAPPING ONGLETS
# ============================================================
SHEET_MAP = {
    "vn":                "VN",
    "vo":                "VO",
    "essai":             "VN",
    "facture_vente":     "Factures_Vente",
    "facture_mecanique": "Factures_Mecanique",
    "facture_carrosserie":"Factures_Carrosserie",
    "facture_pieces":    "Factures_Pieces",
    "mainlevee":         "Mainlevee",
    "rdi":               "RDI_Immatriculation",
    "reclamation":       "Reclamations",
    "sav":               "SAV_Atelier",
}

def get_sheets_service():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        return build("sheets", "v4", credentials=creds)
    except Exception as e:
        print(f"[SHEETS] Erreur connexion: {e}")
        return None

def enregistrer_lead_sheets(telephone, langue, lead_data):
    try:
        service = get_sheets_service()
        if not service:
            return False

        type_lead = lead_data.get("type", "vn")
        sheet_name = SHEET_MAP.get(type_lead, "VN")
        now = datetime.now()

        # Chercher si le client existe deja (colonne L = index 11 = telephone WA)
        result = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f"{sheet_name}!A:P"
        ).execute()
        rows = result.get("values", [])

        existing_row_index = None
        for i, r in enumerate(rows):
            if len(r) > 11 and r[11] == telephone:
                existing_row_index = i + 1
                break

        row = [
            now.strftime("%Y%m%d%H%M%S"),
            now.strftime("%d/%m/%Y %H:%M"),
            lead_data.get("prenom", ""),
            lead_data.get("nom", ""),
            lead_data.get("tel", ""),
            lead_data.get("modele", lead_data.get("vehicule", "")),
            lead_data.get("chassis", ""),
            lead_data.get("cin", lead_data.get("rc", "")),
            lead_data.get("ville", ""),
            lead_data.get("type_facture", lead_data.get("type_doc", "")),
            lead_data.get("description", lead_data.get("reclamation", "")),
            telephone,
            langue,
            type_lead,
            "WhatsApp Bot",
            "NOUVEAU"
        ]

        if existing_row_index:
            service.spreadsheets().values().update(
                spreadsheetId=GOOGLE_SHEET_ID,
                range=f"{sheet_name}!A{existing_row_index}:P{existing_row_index}",
                valueInputOption="USER_ENTERED",
                body={"values": [row]}
            ).execute()
            print(f"[SHEETS] Mis a jour {sheet_name} ligne {existing_row_index}")
        else:
            service.spreadsheets().values().append(
                spreadsheetId=GOOGLE_SHEET_ID,
                range=f"{sheet_name}!A:P",
                valueInputOption="USER_ENTERED",
                body={"values": [row]}
            ).execute()
            print(f"[SHEETS] Nouveau lead dans {sheet_name}")

        return True
    except Exception as e:
        print(f"[SHEETS] Erreur: {e}")
        return False


# ============================================================
# SESSION MANAGEMENT
# ============================================================
sessions = {}

SYSTEM_PROMPT = """Tu es l'Assistant Virtuel officiel de Top Auto Mohammedia, concessionnaire agréé Renault et Dacia (Mohammedia, Maroc).

IDENTITE :
Tu t'appelles "Assistant Virtuel Top Auto". Tu es professionnel, courtois et concis.

REGLES ABSOLUES :
1. Ne jamais communiquer de prix, tarifs ou informations financières confidentielles.
2. Toujours identifier le besoin du client avant de répondre.
3. Collecter les informations une par une, jamais deux questions dans le même message.
4. Lorsqu'une information n'est pas disponible, proposer un rappel par un conseiller.
5. Ne jamais communiquer d'informations internes ou confidentielles.

HORAIRES :
Lun-Ven 8h00-18h30 | Sam Renault 8h30-13h00 | Sam Dacia 8h30-15h00 | Dim fermé
Si client contacte hors horaires → répondre normalement mais préciser que l'équipe traitera sa demande dès la reprise.

ETABLISSEMENT :
Adresse : Q.I Bd Sidi Mohamed Ben Abdellah, 208000 Mohammedia
Tel : 0523303194 | Email : contact@top-auto.ma
GPS : 33.683384 N, 7.409769 W
Facebook : @topauto | Instagram : @top_auto_mohammedia

GAMME DACIA (véhicules neufs) :
Spring électrique (24.3kWh 70/100ch Essential/Extreme) | Sandero Streetway (2026 écran 10p 1.0SCe65/TCe100/dCi102ch Essential-Journey) | Sandero Stepway (17cm TCe100/dCi102ch CVT) | Logan (coffre528L SCe65/TCe100/dCi102ch) | Jogger (5ou7pl coffre1807L HEV140ch) | Duster 2025 (dCi115/TCe130ch Essential-Extreme) | Bigster 2025 (HEV155ch toitPano Essential-Journey)

GAMME RENAULT VP (véhicules neufs) :
Clio 5/6 (TCe100/diesel/ETech145ch Équilibre-Esprit Alpine) | Captur (OpenRLink ETech145ch) | R5 ETech (électrique 40kWh120/52kWh150ch 400km) | Express (diesel 95/115ch) | Mégane Sedan (coffre475L diesel) | Mégane ETech (60kWh 450km 220ch) | Arkana (ETech145ch 4.5L/100km) | Austral (ETech200ch OpenRLink 2025) | Kardian (SOMACA TCe100/BluedCi102ch)

GAMME RENAULT VU :
Express Van (800kg 3.3m3 dCi75ch) | Trafic (Combi9pl 1400kg dCi150ch) | Master (8-17m3 1700kg dCi145/180ch)

VEHICULES D'OCCASION :
Stock disponible sur : https://top-auto.ma/Voitures_occasion
Pour tout renseignement ou mise en relation avec un conseiller VO → collecter prénom, téléphone.

SAV — PRISE DE RDV ATELIER :
Formulaire officiel : https://top-auto.ma/Entretienr%C3%A9paration
Message type : "Pour planifier votre rendez-vous atelier, nous vous invitons à compléter notre formulaire en ligne. Un conseiller vous contactera rapidement pour confirmer votre rendez-vous."

MAINLEVEE :
Documents requis (client se présente en concession) :
- Copie de la CIN
- Copie de la carte grise
- Relevé bancaire cacheté mentionnant le dernier prélèvement RCI Finance
- Justificatif de paiement de la valeur résiduelle (si contrat avec valeur résiduelle)
Si client demande où payer la valeur résiduelle → RIB RCI Finance Maroc : 007 780 00000 054111 70005 29

RDI (Récépissé de Dépôt d'Immatriculation) :
Traité uniquement si plus de 30 jours depuis la livraison.
Particulier → collecter : chassis, CIN, téléphone
Société → collecter : chassis, numéro RC, téléphone

SUIVI TRAVAUX / COMMANDES / PIÈCES :
Rediriger vers : 0523303194
Message : "Pour toute information concernant l'avancement des travaux, le suivi de commande ou la réception des pièces, veuillez contacter notre service au 0523303194."

DEMANDES DE FACTURES :
Identifier le type avant de collecter :
- Facture vente VN/VO → collecter : chassis, nom titulaire, téléphone
- Facture atelier mécanique → collecter : matricule ou chassis, nom titulaire, téléphone
- Facture carrosserie → collecter : matricule ou chassis, nom titulaire, téléphone
- Facture pièces de rechange → collecter : matricule ou chassis, nom titulaire, téléphone

ESSAI VEHICULE NEUF :
Collecter : prénom, nom, téléphone, modèle souhaité, ville
Transmettre au service commercial.

RECLAMATIONS :
Collecter : prénom, nom, téléphone, chassis (si applicable), description détaillée
Enregistrer et transmettre immédiatement au responsable.

COLLECTE D'INFORMATIONS — RÈGLE STRICTE :
Toujours une seule question par message. Dans l'ordre : prénom → nom → téléphone → autres infos selon le type de demande.

LANGUE :
Caractères arabes → répondre UNIQUEMENT en arabe
Par défaut → français
La darija marocaine latinisée est comprise → répondre en français

CONFIRMATION LEAD — QUAND TOUTES LES INFOS SONT COLLECTÉES :
Terminer par un récapitulatif :
"Récapitulatif de votre demande :
- Prénom : [prenom]
- Téléphone : [tel]
- [autres infos collectées]
Notre équipe vous contactera très prochainement. Merci pour votre confiance."

FORMAT DE RÉPONSE OBLIGATOIRE :
Toujours deux parties séparées par |||
Format : TEXTE_VISIBLE_CLIENT|||TAG_INTERNE

TAGS DISPONIBLES :
|||RIEN
|||BOUTONS_BIENVENUE
|||LEAD:prenom=X|nom=X|tel=X|modele=X|ville=X|type=vn
|||LEAD:prenom=X|nom=X|tel=X|modele=X|type=vo
|||LEAD:prenom=X|nom=X|tel=X|modele=X|ville=X|type=essai
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|type_facture=vn|type=facture_vente
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|type_facture=vo|type=facture_vente
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|type_facture=mecanique|type=facture_mecanique
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|type_facture=carrosserie|type=facture_carrosserie
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|type_facture=pieces|type=facture_pieces
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|cin=X|type=rdi
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|rc=X|type=rdi
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|reclamation=X|type=reclamation
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|type=mainlevee
|||FIN

RÈGLES FORMAT :
- JAMAIS écrire ||| ou LEAD ou TAG dans le texte visible au client
- Si prénom ou téléphone manquants → |||RIEN
- Sauvegarder LEAD seulement si prénom ET téléphone sont réels (pas X, pas vide)
- Aucun emoji dans les réponses
- Terminer par : Merci pour votre confiance. (FR) ou شكرا على ثقتك. (AR)"""


# ============================================================
# SESSION
# ============================================================
def get_session(telephone):
    if telephone not in sessions:
        sessions[telephone] = {"historique": [], "langue": "FR", "infos": {}}
    return sessions[telephone]


# ============================================================
# WHATSAPP HELPERS
# ============================================================
def envoyer_whatsapp(telephone, message):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {
        "messaging_product": "whatsapp",
        "to": telephone,
        "type": "text",
        "text": {"body": message}
    }
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
    msg = (
        "Bonjour et bienvenue chez Top Auto Mohammedia, concessionnaire agréé Renault et Dacia.\n\n"
        "Je suis l'Assistant Virtuel Top Auto, à votre disposition pour vous accompagner concernant :\n"
        "- Les véhicules Renault et Dacia (neufs et occasion)\n"
        "- L'entretien et les réparations\n"
        "- Les pièces de rechange et carrosserie\n"
        "- Les demandes administratives\n"
        "- Les rendez-vous après-vente\n\n"
        "Comment puis-je vous aider aujourd'hui ?"
    )
    envoyer_boutons(
        telephone, msg,
        [
            {"id": "btn_vehicules", "title": "Véhicules"},
            {"id": "btn_sav", "title": "SAV & Atelier"},
            {"id": "btn_autre", "title": "Autre demande"}
        ]
    )


def envoyer_menu_vehicules(telephone):
    envoyer_boutons(
        telephone,
        "Quelle gamme vous intéresse ?",
        [
            {"id": "btn_vn", "title": "Véhicules Neufs"},
            {"id": "btn_vo", "title": "Véhicules Occasion"},
            {"id": "btn_essai", "title": "Essai Gratuit"}
        ]
    )


def envoyer_menu_autre(telephone):
    envoyer_boutons(
        telephone,
        "Quelle est votre demande ?",
        [
            {"id": "btn_facture", "title": "Demande Facture"},
            {"id": "btn_mainlevee", "title": "Mainlevée"},
            {"id": "btn_reclamation", "title": "Réclamation"}
        ]
    )


def notifier_conseiller(telephone, nom_client, lead_data):
    type_lead = lead_data.get("type", "vn")
    sheet_name = SHEET_MAP.get(type_lead, "VN")
    lignes = [
        f"--- NOUVEAU LEAD : {sheet_name.upper()} ---",
        f"WhatsApp client : {telephone}",
        f"Nom : {lead_data.get('nom', '')} {lead_data.get('prenom', '')}",
        f"Tel client : {lead_data.get('tel', 'NC')}",
    ]
    if lead_data.get("modele"):       lignes.append(f"Modèle : {lead_data['modele']}")
    if lead_data.get("ville"):        lignes.append(f"Ville : {lead_data['ville']}")
    if lead_data.get("chassis"):      lignes.append(f"Châssis : {lead_data['chassis']}")
    if lead_data.get("cin"):          lignes.append(f"CIN : {lead_data['cin']}")
    if lead_data.get("rc"):           lignes.append(f"RC : {lead_data['rc']}")
    if lead_data.get("type_facture"): lignes.append(f"Type facture : {lead_data['type_facture']}")
    if lead_data.get("reclamation"):  lignes.append(f"Réclamation : {lead_data['reclamation']}")
    if lead_data.get("description"):  lignes.append(f"Description : {lead_data['description']}")
    lignes.append(f"Statut : {'URGENT - 48h' if type_lead == 'reclamation' else 'À RAPPELER'}")
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
        json={"model": "llama-3.3-70b-versatile", "messages": messages, "max_tokens": 1000, "temperature": 0.3},
        timeout=30
    )
    print(f"[GROQ] Status: {resp.status_code}")
    if resp.status_code != 200:
        raise Exception(f"Groq error {resp.status_code}: {resp.text[:200]}")
    return resp.json()["choices"][0]["message"]["content"]


def appeler_groq_vision(image_base64, mime_type):
    prompt_vision = """Tu es un expert automobile. Analyse cette image envoyée par un client de Top Auto Mohammedia.
Identifie : le problème visible (rayure, bosselure, voyant allumé, pneu endommagé, panne, autre).
Donne : une description professionnelle du problème, une classification (carrosserie / mécanique / électronique / pneu / autre) et une recommandation claire (passage atelier SAV recommandé / surveillance / aucune action urgente).
Réponds en français de manière concise et professionnelle. Termine par : Merci pour votre confiance."""
    messages = [
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}},
            {"type": "text", "text": prompt_vision}
        ]}
    ]
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": "meta-llama/llama-4-scout-17b-16e-instruct", "messages": messages, "max_tokens": 500},
        timeout=30
    )
    print(f"[VISION] Status: {resp.status_code}")
    if resp.status_code != 200:
        return "Je n'ai pas pu analyser cette image. Merci de vous présenter en atelier pour un diagnostic. Merci pour votre confiance."
    return resp.json()["choices"][0]["message"]["content"]


def traiter_reponse_groq(raw):
    texte, tag = raw.strip(), "RIEN"
    if "|||" in raw:
        idx = raw.rfind("|||")
        texte, tag = raw[:idx].strip(), raw[idx+3:].strip()
    texte = re.sub(r'\|\|\|[\s\S]*', '', texte)
    texte = re.sub(r'LEAD:[\w=|.\s\u0600-\u06FF-]*', '', texte)
    texte = texte.replace("|||", "").replace("RIEN", "").replace("FIN", "").replace("BOUTONS_BIENVENUE", "").strip()
    return texte, tag


# ============================================================
# WEBHOOK
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

        # ---- AUDIO ----
        if msg_type == "audio":
            print(f"[AUDIO] Message vocal de {telephone}")
            envoyer_whatsapp(telephone, "Message vocal reçu, transcription en cours...")
            media_id = message.get("audio", {}).get("id")
            if not media_id:
                envoyer_whatsapp(telephone, "Impossible de traiter ce message vocal. Merci d'écrire votre demande.")
                return jsonify({"status": "ok"}), 200
            headers_wa = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
            resp_url = requests.get(f"https://graph.facebook.com/v20.0/{media_id}", headers=headers_wa, timeout=10)
            if resp_url.status_code != 200:
                envoyer_whatsapp(telephone, "Erreur lors du traitement audio. Appelez-nous au 0523303194.")
                return jsonify({"status": "ok"}), 200
            audio_url = resp_url.json().get("url")
            resp_audio = requests.get(audio_url, headers=headers_wa, timeout=20)
            try:
                files = {"file": ("audio.ogg", resp_audio.content, "audio/ogg")}
                data_whisper = {"model": "whisper-large-v3", "language": "fr", "response_format": "text"}
                resp_whisper = requests.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    files=files, data=data_whisper, timeout=30
                )
                if resp_whisper.status_code != 200:
                    envoyer_whatsapp(telephone, "Transcription impossible. Merci d'écrire votre demande. Merci pour votre confiance.")
                    return jsonify({"status": "ok"}), 200
                texte = resp_whisper.text.strip()
                if not texte:
                    envoyer_whatsapp(telephone, "Je n'ai pas pu comprendre votre message vocal. Merci d'écrire votre demande.")
                    return jsonify({"status": "ok"}), 200
                envoyer_whatsapp(telephone, f"J'ai bien entendu : \"{texte}\"")
            except Exception as e:
                print(f"[AUDIO] Erreur: {e}")
                envoyer_whatsapp(telephone, "Transcription impossible. Merci d'écrire votre demande.")
                return jsonify({"status": "ok"}), 200

        # ---- IMAGE ----
        elif msg_type == "image":
            print(f"[IMAGE] Photo reçue de {telephone}")
            envoyer_whatsapp(telephone, "Photo reçue, analyse en cours par notre Assistant IA...")
            media_id = message.get("image", {}).get("id")
            mime_type = message.get("image", {}).get("mime_type", "image/jpeg")
            if not media_id:
                envoyer_whatsapp(telephone, "Impossible d'analyser cette image. Merci pour votre confiance.")
                return jsonify({"status": "ok"}), 200
            headers_wa = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
            resp_url = requests.get(f"https://graph.facebook.com/v20.0/{media_id}", headers=headers_wa, timeout=10)
            if resp_url.status_code != 200:
                envoyer_whatsapp(telephone, "Impossible de télécharger l'image. Merci pour votre confiance.")
                return jsonify({"status": "ok"}), 200
            image_url = resp_url.json().get("url")
            resp_img = requests.get(image_url, headers=headers_wa, timeout=20)
            if resp_img.status_code != 200:
                envoyer_whatsapp(telephone, "Impossible de télécharger l'image. Merci pour votre confiance.")
                return jsonify({"status": "ok"}), 200
            image_b64 = base64.b64encode(resp_img.content).decode("utf-8")
            analyse = appeler_groq_vision(image_b64, mime_type)
            envoyer_whatsapp(telephone, analyse)
            envoyer_boutons(
                telephone,
                "Souhaitez-vous prendre rendez-vous en atelier ?",
                [
                    {"id": "btn_rdv_sav", "title": "Prendre RDV"},
                    {"id": "btn_autre_question", "title": "Autre question"}
                ]
            )
            return jsonify({"status": "ok"}), 200

        # ---- TEXTE ----
        elif msg_type == "text":
            texte = message.get("text", {}).get("body", "").strip()
            button_id = None

        # ---- BOUTON INTERACTIF ----
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

        session = get_session(telephone)
        if any('\u0600' <= c <= '\u06FF' for c in texte):
            session["langue"] = "AR"

        texte_lower = texte.lower().strip()
        salutations = ["bonjour", "salam", "salut", "hi", "hello", "bonsoir", "مرحبا", "السلام", "ahlan", "bzaf", "cava", "ça va"]

        # ---- GESTION BOUTONS ET SALUTATIONS ----
        if texte_lower in salutations and not session["historique"]:
            envoyer_bienvenue(telephone)
            return jsonify({"status": "ok"}), 200

        if msg_type == "interactive":
            button_id = message.get("interactive", {}).get("button_reply", {}).get("id", "")

            if button_id == "btn_vehicules":
                envoyer_menu_vehicules(telephone)
                return jsonify({"status": "ok"}), 200

            elif button_id == "btn_sav":
                texte = "Je veux prendre un rendez-vous SAV atelier"

            elif button_id == "btn_autre":
                envoyer_menu_autre(telephone)
                return jsonify({"status": "ok"}), 200

            elif button_id == "btn_vn":
                texte = "Je veux des informations sur les véhicules neufs Renault et Dacia"

            elif button_id == "btn_vo":
                texte = "Je veux des informations sur les véhicules d'occasion"

            elif button_id == "btn_essai":
                texte = "Je veux faire un essai de véhicule neuf"

            elif button_id == "btn_facture":
                texte = "Je veux demander une facture"

            elif button_id == "btn_mainlevee":
                texte = "Je veux des informations sur la mainlevée"

            elif button_id == "btn_reclamation":
                texte = "J'ai une réclamation à faire"

            elif button_id == "btn_rdv_sav":
                envoyer_whatsapp(telephone,
                    "Pour planifier votre rendez-vous atelier, nous vous invitons à compléter notre formulaire en ligne :\n"
                    "https://top-auto.ma/Entretienr%C3%A9paration\n\n"
                    "Un conseiller vous contactera rapidement pour confirmer votre rendez-vous. Merci pour votre confiance.")
                return jsonify({"status": "ok"}), 200

            elif button_id == "btn_autre_question":
                envoyer_whatsapp(telephone, "Je suis à votre écoute. Comment puis-je vous aider ?")
                return jsonify({"status": "ok"}), 200

        # ---- APPEL GROQ ----
        raw = appeler_groq(session["historique"], texte)
        texte_client, tag = traiter_reponse_groq(raw)

        if "BOUTONS_BIENVENUE" in tag or "BOUTONS_BIENVENUE" in texte_client:
            envoyer_bienvenue(telephone)
            return jsonify({"status": "ok"}), 200

        if not texte_client or len(texte_client) < 5:
            texte_client = "Désolée, une erreur est survenue. Veuillez nous contacter au 0523303194. Merci pour votre confiance."

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
                session["infos"].update(lead_data)
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
