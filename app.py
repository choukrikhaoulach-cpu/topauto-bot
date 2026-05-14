# -*- coding: utf-8 -*-
import os
import json
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from groq import Groq
import google.auth
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = Flask(__name__)

# ============================================================
# CONFIGURATION
# ============================================================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
print(f"[DEBUG] GROQ_API_KEY length: {len(GROQ_API_KEY)} chars, starts with: {GROQ_API_KEY[:8]}")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "EAASp22f3wJMBRXZCwltPEHez3rZAwMiOZAAhiTvEtByPcSMWTv1eWKlisVx8mCUtiUvpOwqXqgxU2z6PzEvg7RCXmZA2kRVvn4OoLphpQhZCXmJWMmPyLP8jNVyZAdcUSAz2H7CZAwZBZBp3nv3JpoAZC6X1S9WKVNqMlExB2ZBbpUF5wqaA1ZC7fNIWzh58CKIxYHPfn6IZAtm7zZBZAMsEDZBnt4Tgh8QfpX0QyGllghJMFQC6IiLQIPF6ELSJ09HZCZCGq2C9vb3ZAlZCQGxLZBODwnXQUR2Wc")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1031404513398168")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "topauto2024secret")
CONSEILLER_TEL = os.environ.get("CONSEILLER_WHATSAPP", "212774057668")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")

groq_client = Groq(api_key=GROQ_API_KEY)

# ============================================================
# GOOGLE SHEETS SETUP
# ============================================================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON", "")

def get_sheets_service():
    try:
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        service = build("sheets", "v4", credentials=creds)
        return service
    except Exception as e:
        print(f"[SHEETS] Erreur connexion: {e}")
        return None

# Mapping type lead -> onglet
SHEET_MAP = {
    "commercial": "Leads_Commerciaux",
    "sav_atelier": "SAV_Atelier",
    "pieces": "Pieces_Rechange",
    "sav_document": "SAV_Documents",
    "financement": "Financement_Assurance",
    "reclamation": "Reclamations"
}

def enregistrer_lead_sheets(telephone, langue, lead_data):
    try:
        service = get_sheets_service()
        if not service:
            return False

        type_lead = lead_data.get("type", "commercial")
        sheet_name = SHEET_MAP.get(type_lead, "Leads_Commerciaux")

        # Generer ID unique
        now = datetime.now()
        lead_id = now.strftime("%Y%m%d%H%M%S")
        date_str = now.strftime("%d/%m/%Y %H:%M")

        row = [
            lead_id,
            date_str,
            lead_data.get("prenom", ""),
            lead_data.get("tel", ""),
            lead_data.get("modele", lead_data.get("vehicule", "")),
            lead_data.get("type_financement", lead_data.get("nature", "")),
            lead_data.get("chassis", ""),
            type_lead,
            lead_data.get("immat", ""),
            lead_data.get("nature", ""),
            lead_data.get("description", ""),
            telephone,
            langue,
            "WhatsApp Bot",
            "NOUVEAU"
        ]

        body = {"values": [row]}
        service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f"{sheet_name}!A:O",
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()

        print(f"[SHEETS] Lead enregistre dans {sheet_name}")
        return True
    except Exception as e:
        print(f"[SHEETS] Erreur enregistrement: {e}")
        return False


# ============================================================
# SESSION MANAGEMENT
# ============================================================
sessions = {}

SYSTEM_PROMPT = """Tu es l assistant virtuel de Top Auto Mohammedia (Renault et Dacia, Mohammedia Maroc).

REGLE ABSOLUE NUMERO 1 : Ne JAMAIS commencer une reponse par "Bonjour, comment puis-je vous aider ?" seul. Ce message est trop sec et INTERDIT comme reponse unique a une salutation.

COMPORTEMENT STRICT :
- Si le client envoie uniquement bonjour ou salam ou hi ou مرحبا -> repondre avec un message de bienvenue chaleureux sur 2-3 lignes qui presente Top Auto Mohammedia et invite le client a exprimer son besoin. Exemple : "Bienvenue chez Top Auto Mohammedia, votre concessionnaire officiel Renault et Dacia ! Nous sommes ravis de vous accueillir. Comment pouvons-nous vous aider aujourd'hui ?"
- Pour TOUS les autres messages -> repondre IMMEDIATEMENT et DIRECTEMENT a la demande sans aucune introduction ni presentation

ETABLISSEMENT :
Adresse : Q.I Bd Sidi Mohamed Ben Abdellah, 208000 Mohammedia
Tel Renault : 05 23 30 31 94 | Dacia : 05 23 30 31 95
Horaires : Lun-Ven 8h00-18h30 | Sam Renault 8h30-13h00 | Sam Dacia 8h30-15h00 | Dim ferme
GPS : 33.683384 N, 7.409769 W
Facebook : @topauto | Instagram : @top_auto_mohammedia

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
1. PRIX : Jamais de prix. Dire : Pour le meilleur tarif personnalise, je transmets a notre equipe. Puis-je noter votre prenom ?
2. RDV ET TEST DRIVE : Essai gratuit sans engagement. Donner les deux liens + collecter prenom et telephone
3. DOCUMENTS SAV : Lister justificatifs selon type + collecter prenom/telephone/chassis un par un
4. RECLAMATIONS : Empathie totale + collecter prenom/telephone/immat/description un par un + confirmer reponse 48h
5. FINANCEMENT : Presenter options sans taux ni mensualite + orienter conseiller
6. CATALOGUE : Afficher toute la gamme avec details techniques. Ne pas demander prenom/tel.

COLLECTE INFOS - UNE SEULE QUESTION A LA FOIS :
D abord prenom uniquement. Puis telephone. Puis modele si necessaire.
Ne jamais poser deux questions dans le meme message.

CONFIRMATION LEAD - QUAND TU AS PRENOM ET TELEPHONE :
Terminer le message par un recapitulatif comme :
"Recapitulatif de votre demande :
- Prenom : [prenom]
- Telephone : [tel]
- Modele : [modele]
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

REGLES FORMAT STRICTES :
- JAMAIS ecrire ||| ou LEAD ou TAG dans le texte visible
- Si prenom ou tel manquants -> |||RIEN
- Sauvegarder LEAD seulement si prenom ET tel sont reels
- Terminer par : Merci pour votre confiance. (FR) ou شكرا على ثقتك. (AR)
- Aucun emoji"""


# ============================================================
# FONCTIONS UTILITAIRES
# ============================================================

def get_session(telephone):
    if telephone not in sessions:
        sessions[telephone] = {
            "historique": [],
            "langue": "FR",
            "infos_collectees": {}
        }
    return sessions[telephone]


def envoyer_whatsapp(telephone, message):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": telephone,
        "type": "text",
        "text": {"body": message}
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        print(f"[WA] Envoye a {telephone}: {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        print(f"[WA] Erreur: {e}")
        return False


def notifier_conseiller(telephone, nom, lead_data):
    type_lead = lead_data.get("type", "commercial")
    lignes = [
        f"--- NOUVEAU LEAD {type_lead.upper()} ---",
        f"Client WA : {telephone}",
        f"Nom WhatsApp : {nom}",
        f"Prenom : {lead_data.get('prenom', 'NC')}",
        f"Tel : {lead_data.get('tel', 'NC')}",
    ]
    if lead_data.get("modele"):      lignes.append(f"Modele : {lead_data['modele']}")
    if lead_data.get("vehicule"):    lignes.append(f"Vehicule : {lead_data['vehicule']}")
    if lead_data.get("chassis"):     lignes.append(f"Chassis : {lead_data['chassis']}")
    if lead_data.get("type_doc"):    lignes.append(f"Type doc : {lead_data['type_doc']}")
    if lead_data.get("immat"):       lignes.append(f"Immat : {lead_data['immat']}")
    if lead_data.get("nature"):      lignes.append(f"Nature : {lead_data['nature']}")
    if lead_data.get("description"): lignes.append(f"Description : {lead_data['description']}")
    statut = "NOUVEAU - reponse 48h" if type_lead == "reclamation" else "A RAPPELER"
    lignes.append(f"Statut : {statut}")
    envoyer_whatsapp(CONSEILLER_TEL, "\n".join(lignes))


def extraire_lead(tag):
    if not tag.startswith("LEAD:"):
        return None
    lead = {}
    for partie in tag.replace("LEAD:", "").split("|"):
        idx = partie.find("=")
        if idx > 0:
            k = partie[:idx].strip()
            v = partie[idx+1:].strip()
            if k and v and v not in ["X", "", "null"]:
                lead[k] = v
    if not lead.get("prenom") or not lead.get("tel"):
        return None
    return lead


def appeler_groq(historique, texte):
    try:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(historique)
        messages.append({"role": "user", "content": texte})
        print(f"[GROQ] Appel HTTP direct...")
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": messages,
                "max_tokens": 900,
                "temperature": 0.3
            },
            timeout=30
        )
        print(f"[GROQ] Status: {resp.status_code}")
        print(f"[GROQ] Reponse: {resp.text[:200]}")
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[GROQ ERREUR] {type(e).__name__}: {e}")
        raise


def traiter_reponse_groq(raw):
    import re
    texte = raw.strip()
    tag = "RIEN"
    if "|||" in raw:
        idx = raw.rfind("|||")
        texte = raw[:idx].strip()
        tag = raw[idx+3:].strip()
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

        if msg_type == "text":
            texte = message.get("text", {}).get("body", "").strip()
        elif msg_type == "interactive":
            texte = message.get("interactive", {}).get("button_reply", {}).get("title", "")
        else:
            return jsonify({"status": "ok"}), 200

        if not texte:
            return jsonify({"status": "ok"}), 200

        print(f"\n[MSG] {telephone} ({nom}): {texte}")

        session = get_session(telephone)

        if any('\u0600' <= c <= '\u06FF' for c in texte):
            session["langue"] = "AR"

        raw = appeler_groq(session["historique"], texte)
        texte_client, tag = traiter_reponse_groq(raw)

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


# ============================================================
# LANCEMENT
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[START] TopAuto Bot sur port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
