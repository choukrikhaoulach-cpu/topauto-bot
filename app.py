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
# CONFIGURATION — lues au démarrage
# ============================================================
GROQ_API_KEY      = os.environ.get("GROQ_API_KEY", "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")
# Fallback IDs si Railway ne passe pas les variables
_SHEET_VENTES   = "104zrDmipMrXOzbXajmd9I6hf8WHVeogC8LU0GFXNk1I"
_SHEET_FACTURES = "12Zwfi5H3vxKJDN---5qeZspuqwd-VjQthfe4uZrUTGg"
_SHEET_SAV      = "12GxqngDty_PniBNkMycGGqHD6MWrXEAYjPsRKkvLI8A"
WHATSAPP_TOKEN    = os.environ.get("WHATSAPP_TOKEN", "EAASp22f3wJMBRkg5rOSZCpaFrOPNaMzibYqTUxjLph5I9GGTQHLyAZAmDFAOz1bX5KcEGRzUZCC1nMCjtq11m68rhlszwnEo2AiewdrWoLh3ai1jyZAwrFwLLlp58uQnfOyvDkTZAKe0Cv7ZADFZBsmUt81v2TGiseH2ZAZCZAxEmpBXHGGcHOE9Q7ubcXChzMREpSZC0A58SgGZAEJSutwTQjj84H4fX9SK6drQx5rh0ewRdEAqKLaLZAedcIdfz1JN5X31ay1Mh1NRx9qSsozprfllY")
PHONE_NUMBER_ID   = os.environ.get("PHONE_NUMBER_ID", "1031404513398168")
VERIFY_TOKEN      = os.environ.get("VERIFY_TOKEN", "topauto2024secret")
CONSEILLER_TEL    = os.environ.get("CONSEILLER_WHATSAPP", "212774057668")
GOOGLE_SHEET_VENTES   = os.environ.get("GOOGLE_SHEET_VENTES", "104zrDmipMrXOzbXajmd9I6hf8WHVeogC8LU0GFXNk1I")
GOOGLE_SHEET_FACTURES = os.environ.get("GOOGLE_SHEET_FACTURES", "12Zwfi5H3vxKJDN---5qeZspuqwd-VjQthfe4uZrUTGg")
GOOGLE_SHEET_SAV      = os.environ.get("GOOGLE_SHEET_SAV", "12GxqngDty_PniBNkMycGGqHD6MWrXEAYjPsRKkvLI8A")
GOOGLE_CREDS_JSON     = os.environ.get("GOOGLE_CREDS_JSON", "")

# ============================================================
# GOOGLE SHEETS — IDs lus dynamiquement à chaque appel
# ============================================================
def get_sheet_config(type_lead):
    ventes   = os.environ.get("GOOGLE_SHEET_VENTES", _SHEET_VENTES)
    factures = os.environ.get("GOOGLE_SHEET_FACTURES", _SHEET_FACTURES)
    sav      = os.environ.get("GOOGLE_SHEET_SAV", _SHEET_SAV)
    mapping = {
        "vn":                  (ventes,   "VN_Leads"),
        "vo":                  (ventes,   "VO_Leads"),
        "essai":               (ventes,   "Essais_VN"),
        "facture_vente":       (factures, "Factures_Vente"),
        "facture_mecanique":   (factures, "Factures_Mecanique"),
        "facture_carrosserie": (factures, "Factures_Carrosserie"),
        "facture_pieces":      (factures, "Factures_Pieces"),
        "sav_atelier":         (sav,      "SAV_Atelier"),
        "reclamation":         (sav,      "Reclamations"),
        "mainlevee":           (sav,      "Mainlevee"),
        "rdi":                 (sav,      "RDI_Immatriculation"),
    }
    result = mapping.get(type_lead.lower(), (ventes, "VN_Leads"))
    print(f"[SHEETS] Config pour type={type_lead}: sheet_id={'OK' if result[0] else 'VIDE'}, onglet={result[1]}")
    return result


def get_sheets_service():
    try:
        creds_json = os.environ.get("GOOGLE_CREDS_JSON", GOOGLE_CREDS_JSON)
        if not creds_json:
            print("[SHEETS] GOOGLE_CREDS_JSON vide")
            return None
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        return build("sheets", "v4", credentials=creds)
    except Exception as e:
        print(f"[SHEETS] Erreur connexion: {e}")
        return None


def verifier_statut_rdi(chassis):
    try:
        service = get_sheets_service()
        sav = os.environ.get("GOOGLE_SHEET_SAV", "")
        if not service or not sav:
            print("[RDI] Service ou Sheet ID manquant")
            return None
        result = service.spreadsheets().values().get(
            spreadsheetId=sav,
            range="RDI_Immatriculation!A:P"
        ).execute()
        rows = result.get("values", [])
        chassis_lower = chassis.lower().strip()
        for r in rows[1:]:
            if len(r) > 6 and r[6].lower().strip() == chassis_lower:
                statut = r[10] if len(r) > 10 else "En cours de traitement"
                date_dispo = r[11] if len(r) > 11 else ""
                return {"statut": statut, "date_dispo": date_dispo, "trouve": True}
        return {"statut": "NON_TROUVE", "date_dispo": "", "trouve": False}
    except Exception as e:
        print(f"[RDI] Erreur verification: {e}")
        return None


def enregistrer_lead_sheets(telephone, langue, lead_data):
    try:
        service = get_sheets_service()
        if not service:
            return False
        type_lead = lead_data.get("type", "vn")
        sheet_id, sheet_name = get_sheet_config(type_lead)
        if not sheet_id:
            print(f"[SHEETS] Sheet ID vide pour type={type_lead} — verifiez GOOGLE_SHEET_VENTES/FACTURES/SAV dans Railway")
            return False
        now = datetime.now()

        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
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
                spreadsheetId=sheet_id,
                range=f"{sheet_name}!A{existing_row_index}:P{existing_row_index}",
                valueInputOption="USER_ENTERED",
                body={"values": [row]}
            ).execute()
            print(f"[SHEETS] Mis a jour {sheet_name} ligne {existing_row_index}")
        else:
            service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=f"{sheet_name}!A:P",
                valueInputOption="USER_ENTERED",
                body={"values": [row]}
            ).execute()
            print(f"[SHEETS] Nouveau lead dans {sheet_name}")
        return True
    except Exception as e:
        print(f"[SHEETS] Erreur enregistrement: {e}")
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
6. INTERDIT de répéter le message de bienvenue dans une conversation déjà commencée.
7. Pour TOUTE demande -> répondre DIRECTEMENT sans introduction ni message de bienvenue.
8. Chaque flux de collecte est INDEPENDANT. Ne jamais mélanger les questions de flux différents.

HORAIRES :
Lun-Ven 8h00-18h30 | Sam Renault 8h30-13h00 | Sam Dacia 8h30-15h00 | Dim fermé
Si client contacte hors horaires -> répondre normalement mais préciser que l'équipe traitera dès la reprise.

ETABLISSEMENT :
Adresse : Q.I Bd Sidi Mohamed Ben Abdellah, 208000 Mohammedia
Tel : 0523303194 | Email : contact@top-auto.ma
GPS : 33.683384 N, 7.409769 W

GAMME DACIA :
Spring électrique | Sandero Streetway | Sandero Stepway | Logan | Jogger HEV | Duster 2025 | Bigster 2025

GAMME RENAULT VP :
Clio 5/6 | Captur | R5 ETech électrique | Express | Mégane Sedan | Mégane ETech | Arkana | Austral | Kardian

GAMME RENAULT VU :
Express Van | Trafic Combi | Master

VEHICULES D'OCCASION :
Stock : https://top-auto.ma/Voitures_occasion
Collecter prénom, téléphone -> type=vo

SAV — RDV ATELIER :
Lien : https://top-auto.ma/Entretienr%C3%A9paration
Collecter prénom, nom, téléphone -> type=sav_atelier

MAINLEVEE :
Documents : CIN + carte grise + relevé bancaire RCI + justificatif valeur résiduelle si applicable
RIB RCI Finance : 007 780 00000 054111 70005 29
Collecter : prénom, nom, téléphone, chassis -> type=mainlevee

RDI (Récépissé Dépôt Immatriculation) :
Traité si plus de 30 jours depuis livraison.
Ordre STRICT : 1-livré +30j? 2-particulier/société? 3-prénom 4-chassis 5-CIN ou RC 6-téléphone
Particulier -> type=rdi avec cin
Société -> type=rdi avec rc

SUIVI TRAVAUX : contacter 0523303194

FACTURES :
Vente VN/VO -> chassis, nom, tel -> type=facture_vente
Mécanique -> matricule/chassis, nom, tel -> type=facture_mecanique
Carrosserie -> matricule/chassis, nom, tel -> type=facture_carrosserie
Pièces -> matricule/chassis, nom, tel -> type=facture_pieces

ESSAI VEHICULE NEUF — flux STRICT :
Ordre : 1-prénom 2-nom 3-téléphone 4-modèle 5-ville
UNE SEULE question par message.
NE JAMAIS demander confirmation ou reposer les questions déjà répondues.
NE JAMAIS afficher "Prénom : X, Nom : Y" sauf dans le récapitulatif final.
Quand les 5 infos sont collectées -> récapitulatif + tag type=essai immédiatement.
JAMAIS mélanger avec RDI ou autre flux.

RECLAMATIONS :
Collecter : prénom, nom, téléphone, chassis si applicable, description -> type=reclamation

COLLECTE : une seule question par message.

LANGUE : arabe -> arabe | darija -> français | défaut -> français

CONFIRMATION : récapitulatif avec toutes les infos collectées + "Notre équipe vous contactera. Merci pour votre confiance."

FORMAT OBLIGATOIRE — chaque réponse DOIT contenir |||  :
Texte réponse au client|||TAG

TAGS :
|||RIEN
|||LEAD:prenom=X|nom=X|tel=X|modele=X|ville=X|type=essai
|||LEAD:prenom=X|nom=X|tel=X|modele=X|type=vn
|||LEAD:prenom=X|nom=X|tel=X|modele=X|type=vo
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|type_facture=vente|type=facture_vente
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|type_facture=mecanique|type=facture_mecanique
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|type_facture=carrosserie|type=facture_carrosserie
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|type_facture=pieces|type=facture_pieces
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|cin=X|type=rdi
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|rc=X|type=rdi
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|reclamation=X|type=reclamation
|||LEAD:prenom=X|nom=X|tel=X|chassis=X|type=mainlevee
|||LEAD:prenom=X|nom=X|tel=X|type=sav_atelier
|||FIN

REGLES FORMAT :
- JAMAIS écrire ||| ou LEAD dans le texte visible
- LEAD seulement si prénom ET téléphone réels (pas X, pas vide)
- Si infos incomplètes -> |||RIEN
- Si toutes les infos collectées -> TOUJOURS tag LEAD, JAMAIS |||RIEN
- Aucun emoji
- Terminer par : Merci pour votre confiance. (FR) ou شكرا على ثقتك. (AR)"""


def get_session(telephone):
    if telephone not in sessions:
        sessions[telephone] = {"historique": [], "langue": "FR", "infos": {}}
    return sessions[telephone]


# ============================================================
# WHATSAPP HELPERS
# ============================================================
def envoyer_whatsapp(telephone, message):
    token = os.environ.get("WHATSAPP_TOKEN", WHATSAPP_TOKEN)
    phone_id = os.environ.get("PHONE_NUMBER_ID", PHONE_NUMBER_ID)
    url = f"https://graph.facebook.com/v20.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": telephone, "type": "text", "text": {"body": message}}
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        print(f"[WA] Text {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        print(f"[WA] Erreur: {e}")
        return False


def envoyer_boutons(telephone, body_text, buttons):
    token = os.environ.get("WHATSAPP_TOKEN", WHATSAPP_TOKEN)
    phone_id = os.environ.get("PHONE_NUMBER_ID", PHONE_NUMBER_ID)
    url = f"https://graph.facebook.com/v20.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
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
        "Je suis l'Assistant Virtuel Top Auto, à votre disposition pour :\n"
        "- Les véhicules Renault et Dacia (neufs et occasion)\n"
        "- L'entretien et les réparations\n"
        "- Les pièces de rechange et carrosserie\n"
        "- Les demandes administratives\n"
        "- Les rendez-vous après-vente\n\n"
        "Comment puis-je vous aider aujourd'hui ?"
    )
    envoyer_boutons(telephone, msg, [
        {"id": "btn_vehicules", "title": "Véhicules"},
        {"id": "btn_sav",       "title": "SAV & Atelier"},
        {"id": "btn_autre",     "title": "Autre demande"}
    ])


def envoyer_menu_vehicules(telephone):
    envoyer_boutons(telephone, "Quelle gamme vous intéresse ?", [
        {"id": "btn_vn",    "title": "Véhicules Neufs"},
        {"id": "btn_vo",    "title": "Véhicules Occasion"},
        {"id": "btn_essai", "title": "Essai Gratuit"}
    ])


def envoyer_menu_autre(telephone):
    envoyer_boutons(telephone, "Quelle est votre demande ?", [
        {"id": "btn_facture",     "title": "Demande Facture"},
        {"id": "btn_mainlevee",   "title": "Mainlevée"},
        {"id": "btn_reclamation", "title": "Réclamation"}
    ])


def notifier_conseiller(telephone, nom_client, lead_data):
    type_lead = lead_data.get("type", "vn")
    _, sheet_name = get_sheet_config(type_lead)
    lignes = [
        f"--- NOUVEAU LEAD : {sheet_name} ---",
        f"WhatsApp : {telephone}",
        f"Nom : {lead_data.get('nom', '')} {lead_data.get('prenom', '')}",
        f"Tel : {lead_data.get('tel', 'NC')}",
    ]
    for k, label in [
        ("modele","Modèle"), ("ville","Ville"), ("chassis","Châssis"),
        ("cin","CIN"), ("rc","RC"), ("type_facture","Type facture"),
        ("reclamation","Réclamation"), ("description","Description")
    ]:
        if lead_data.get(k):
            lignes.append(f"{label} : {lead_data[k]}")
    lignes.append(f"Statut : {'URGENT 48h' if type_lead == 'reclamation' else 'À RAPPELER'}")
    envoyer_whatsapp(os.environ.get("CONSEILLER_WHATSAPP", CONSEILLER_TEL), "\n".join(lignes))


def extraire_lead(tag):
    if not tag.startswith("LEAD:"):
        return None
    lead = {}
    for partie in tag.replace("LEAD:", "").split("|"):
        idx = partie.find("=")
        if idx > 0:
            k, v = partie[:idx].strip(), partie[idx+1:].strip()
            if k and v and v not in ["X", "", "null", "?"]:
                lead[k] = v
    return lead if lead.get("prenom") and lead.get("tel") else None


def appeler_groq(historique, texte):
    groq_key = os.environ.get("GROQ_API_KEY", GROQ_API_KEY)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + historique + [{"role": "user", "content": texte}]
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
        json={"model": "llama-3.1-8b-instant", "messages": messages, "max_tokens": 400, "temperature": 0.2},
        timeout=30
    )
    print(f"[GROQ] Status: {resp.status_code}")
    if resp.status_code != 200:
        raise Exception(f"Groq error {resp.status_code}: {resp.text[:200]}")
    return resp.json()["choices"][0]["message"]["content"]


def appeler_groq_vision(image_base64, mime_type):
    groq_key = os.environ.get("GROQ_API_KEY", GROQ_API_KEY)
    prompt_vision = """Tu es un expert automobile de Top Auto Mohammedia.
Analyse cette image et fournis :
1. Description du problème visible
2. Classification : carrosserie / mécanique / électronique / pneu / autre
3. Gravité : faible / modéré / urgent
4. Recommandation : atelier SAV / surveillance / aucune action urgente
Réponds en français, concis. Termine par : Merci pour votre confiance."""
    messages = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}},
        {"type": "text", "text": prompt_vision}
    ]}]
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
        json={"model": "meta-llama/llama-4-scout-17b-16e-instruct", "messages": messages, "max_tokens": 500},
        timeout=30
    )
    if resp.status_code != 200:
        return "Impossible d'analyser cette image. Présentez-vous en atelier. Merci pour votre confiance."
    return resp.json()["choices"][0]["message"]["content"]


def traiter_reponse_groq(raw):
    texte, tag = raw.strip(), "RIEN"
    if "|||" in raw:
        idx = raw.rfind("|||")
        texte, tag = raw[:idx].strip(), raw[idx+3:].strip()
    texte = re.sub(r'\|\|\|[\s\S]*', '', texte)
    texte = re.sub(r'LEAD:[\w=|.\s\u0600-\u06FF-]*', '', texte)
    texte = texte.replace("|||", "").replace("RIEN", "").replace("FIN", "").strip()
    return texte, tag


def generer_recap(lead_data):
    texte = "Récapitulatif de votre demande :\n"
    if lead_data.get("prenom"): texte += f"- Prénom : {lead_data['prenom']}\n"
    if lead_data.get("nom"):    texte += f"- Nom : {lead_data['nom']}\n"
    if lead_data.get("tel"):    texte += f"- Téléphone : {lead_data['tel']}\n"
    if lead_data.get("modele"): texte += f"- Modèle : {lead_data['modele']}\n"
    if lead_data.get("ville"):  texte += f"- Ville : {lead_data['ville']}\n"
    if lead_data.get("chassis"):texte += f"- Châssis : {lead_data['chassis']}\n"
    if lead_data.get("cin"):    texte += f"- CIN : {lead_data['cin']}\n"
    if lead_data.get("rc"):     texte += f"- RC : {lead_data['rc']}\n"
    texte += "Notre équipe vous contactera très prochainement. Merci pour votre confiance."
    return texte


# ============================================================
# WEBHOOK
# ============================================================
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    verify = os.environ.get("VERIFY_TOKEN", VERIFY_TOKEN)
    if mode == "subscribe" and token == verify:
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

        token_wa = os.environ.get("WHATSAPP_TOKEN", WHATSAPP_TOKEN)

        # ---- AUDIO ----
        if msg_type == "audio":
            envoyer_whatsapp(telephone, "Message vocal reçu, transcription en cours...")
            media_id = message.get("audio", {}).get("id")
            if not media_id:
                envoyer_whatsapp(telephone, "Impossible de traiter ce message vocal.")
                return jsonify({"status": "ok"}), 200
            headers_wa = {"Authorization": f"Bearer {token_wa}"}
            resp_url = requests.get(f"https://graph.facebook.com/v20.0/{media_id}", headers=headers_wa, timeout=10)
            if resp_url.status_code != 200:
                envoyer_whatsapp(telephone, "Erreur audio. Appelez le 0523303194.")
                return jsonify({"status": "ok"}), 200
            audio_url = resp_url.json().get("url")
            resp_audio = requests.get(audio_url, headers=headers_wa, timeout=20)
            try:
                groq_key = os.environ.get("GROQ_API_KEY", GROQ_API_KEY)
                files = {"file": ("audio.ogg", resp_audio.content, "audio/ogg")}
                resp_whisper = requests.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    files=files,
                    data={"model": "whisper-large-v3", "language": "fr", "response_format": "text"},
                    timeout=30
                )
                if resp_whisper.status_code != 200:
                    envoyer_whatsapp(telephone, "Transcription impossible. Merci d'écrire.")
                    return jsonify({"status": "ok"}), 200
                texte = resp_whisper.text.strip()
                if not texte:
                    envoyer_whatsapp(telephone, "Message incompréhensible. Merci d'écrire.")
                    return jsonify({"status": "ok"}), 200
                envoyer_whatsapp(telephone, f"J'ai bien entendu : \"{texte}\"")
            except Exception as e:
                print(f"[AUDIO] Erreur: {e}")
                envoyer_whatsapp(telephone, "Transcription impossible. Merci d'écrire.")
                return jsonify({"status": "ok"}), 200

        # ---- IMAGE ----
        elif msg_type == "image":
            envoyer_whatsapp(telephone, "Photo reçue, analyse en cours...")
            media_id = message.get("image", {}).get("id")
            mime_type = message.get("image", {}).get("mime_type", "image/jpeg")
            if not media_id:
                envoyer_whatsapp(telephone, "Impossible d'analyser cette image.")
                return jsonify({"status": "ok"}), 200
            headers_wa = {"Authorization": f"Bearer {token_wa}"}
            resp_url = requests.get(f"https://graph.facebook.com/v20.0/{media_id}", headers=headers_wa, timeout=10)
            if resp_url.status_code != 200:
                envoyer_whatsapp(telephone, "Impossible de télécharger l'image.")
                return jsonify({"status": "ok"}), 200
            image_url = resp_url.json().get("url")
            resp_img = requests.get(image_url, headers=headers_wa, timeout=20)
            if resp_img.status_code != 200:
                envoyer_whatsapp(telephone, "Impossible de télécharger l'image.")
                return jsonify({"status": "ok"}), 200
            image_b64 = base64.b64encode(resp_img.content).decode("utf-8")
            analyse = appeler_groq_vision(image_b64, mime_type)
            envoyer_whatsapp(telephone, analyse)
            envoyer_boutons(telephone, "Souhaitez-vous prendre rendez-vous en atelier ?", [
                {"id": "btn_rdv_sav",        "title": "Prendre RDV"},
                {"id": "btn_autre_question", "title": "Autre question"}
            ])
            return jsonify({"status": "ok"}), 200

        elif msg_type == "text":
            texte = message.get("text", {}).get("body", "").strip()
        elif msg_type == "interactive":
            interactive = message.get("interactive", {})
            if interactive.get("type") == "button_reply":
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
        salutations = ["bonjour", "salam", "salut", "hi", "hello", "bonsoir",
                       "مرحبا", "السلام", "ahlan", "bjr", "bsr", "coucou"]

        mots = texte_lower.split()
        if msg_type == "text" and len(mots) <= 2 and any(s in texte_lower for s in salutations) and not session["historique"]:
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
                texte = "Je veux des informations sur les véhicules neufs"
            elif button_id == "btn_vo":
                texte = "Je veux des informations sur les véhicules d'occasion"
            elif button_id == "btn_essai":
                texte = "Je veux faire un essai de véhicule neuf"
            elif button_id == "btn_facture":
                texte = "Je veux demander une facture"
            elif button_id == "btn_mainlevee":
                texte = "Je veux faire une demande de mainlevée"
            elif button_id == "btn_reclamation":
                texte = "J'ai une réclamation à déposer"
            elif button_id == "btn_rdv_sav":
                envoyer_whatsapp(telephone,
                    "Pour votre rendez-vous atelier :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\nUn conseiller vous contactera. Merci pour votre confiance.")
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

        # Fallback si texte vide
        if not texte_client or len(texte_client) < 3:
            if tag.startswith("LEAD:"):
                lead_tmp = extraire_lead(tag)
                texte_client = generer_recap(lead_tmp) if lead_tmp else "Votre demande a été enregistrée. Notre équipe vous contactera. Merci pour votre confiance."
            else:
                texte_client = "Désolée, une erreur est survenue. Veuillez nous contacter au 0523303194. Merci pour votre confiance."

        # ---- VERIFICATION RDI ----
        if "type=rdi" in tag and "chassis=" in tag:
            chassis_match = re.search(r'chassis=([^|]+)', tag)
            chassis_rdi = chassis_match.group(1).strip() if chassis_match else None
            if chassis_rdi and chassis_rdi not in ["X", "", "null", "?"]:
                print(f"[RDI] Verification chassis: {chassis_rdi}")
                try:
                    statut_info = verifier_statut_rdi(chassis_rdi)
                    if statut_info is None:
                        texte_client = "Impossible d'accéder au système. Notre équipe vous contactera. Merci pour votre confiance."
                    elif statut_info.get("trouve"):
                        statut = statut_info.get("statut", "En cours")
                        date_dispo = statut_info.get("date_dispo", "")
                        texte_client = f"Vérification dossier :\n\nChâssis : {chassis_rdi}\nStatut : {statut}"
                        if date_dispo:
                            texte_client += f"\nDate disponibilité : {date_dispo}"
                        texte_client += "\n\nContactez le 0523303194 pour plus d'info. Merci pour votre confiance."
                    else:
                        texte_client = f"Le dossier pour le châssis {chassis_rdi} n'est pas encore enregistré. Notre équipe vous contactera. Merci pour votre confiance."
                except Exception as e:
                    print(f"[RDI] Erreur: {e}")

        print(f"[BOT]: {texte_client[:100]}...")
        print(f"[TAG]: {tag}")

        session["historique"].append({"role": "user", "content": texte})
        session["historique"].append({"role": "assistant", "content": texte_client})
        if len(session["historique"]) > 10:
            session["historique"] = session["historique"][-10:]

        envoyer_whatsapp(telephone, texte_client)

        if tag.startswith("LEAD:"):
            lead_data = extraire_lead(tag)
            if lead_data:
                print(f"[LEAD] {lead_data}")
                session["infos"].update(lead_data)
                notifier_conseiller(telephone, nom, lead_data)
                enregistrer_lead_sheets(telephone, session["langue"], lead_data)

        if tag == "FIN":
            if telephone in sessions:
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
