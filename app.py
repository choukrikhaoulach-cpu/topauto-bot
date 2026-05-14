# -*- coding: utf-8 -*-
import os
import json
import requests
from flask import Flask, request, jsonify
from groq import Groq

app = Flask(__name__)

# ============================================================
# CONFIGURATION
# ============================================================
GROQ_API_KEY = "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"
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "{{WHATSAPP_TOKEN}}")
PHONE_NUMBER_ID = "1031404513398168"
VERIFY_TOKEN = "topauto2024secret"
CONSEILLER_TEL = "212774057668"
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "{{GOOGLE_SHEET_ID}}")

groq_client = Groq(api_key=GROQ_API_KEY)

# ============================================================
# SESSION MANAGEMENT (memoire par client)
# ============================================================
sessions = {}

SYSTEM_PROMPT = """Tu es l assistant virtuel de Top Auto Mohammedia (Renault et Dacia, Mohammedia Maroc).

REGLE ABSOLUE NUMERO 1 : Ne JAMAIS commencer une reponse par Bienvenue, bonjour bienvenue, nous sommes ravis, nous proposons une gamme, comment pouvons-nous vous aider. Ces phrases sont STRICTEMENT INTERDITES sauf pour le tout premier message de salutation.

COMPORTEMENT STRICT :
- Si le client envoie uniquement bonjour ou salam ou hi ou مرحبا -> repondre en UNE seule phrase de bienvenue courte puis demander comment aider
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
    """Recuperer ou creer une session client"""
    if telephone not in sessions:
        sessions[telephone] = {
            "historique": [],
            "langue": "FR",
            "infos_collectees": {}
        }
    return sessions[telephone]


def envoyer_whatsapp(telephone, message):
    """Envoyer un message WhatsApp"""
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
    """Notifier le conseiller WhatsApp"""
    type_lead = lead_data.get("type", "commercial")
    lignes = [
        f"--- {type_lead.upper()} ---",
        f"Client WA : {telephone}",
        f"Nom : {nom}",
        f"Prenom : {lead_data.get('prenom', 'NC')}",
        f"Tel : {lead_data.get('tel', 'NC')}",
    ]
    if lead_data.get("modele"):    lignes.append(f"Modele : {lead_data['modele']}")
    if lead_data.get("vehicule"):  lignes.append(f"Vehicule : {lead_data['vehicule']}")
    if lead_data.get("chassis"):   lignes.append(f"Chassis : {lead_data['chassis']}")
    if lead_data.get("type_doc"):  lignes.append(f"Type doc : {lead_data['type_doc']}")
    if lead_data.get("immat"):     lignes.append(f"Immat : {lead_data['immat']}")
    if lead_data.get("nature"):    lignes.append(f"Nature : {lead_data['nature']}")
    if lead_data.get("description"): lignes.append(f"Description : {lead_data['description']}")
    statut = "NOUVEAU - 48h" if type_lead == "reclamation" else "A RAPPELER"
    lignes.append(f"Statut : {statut}")
    envoyer_whatsapp(CONSEILLER_TEL, "\n".join(lignes))


def extraire_lead(tag):
    """Extraire les donnees du tag LEAD"""
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
    """Appeler Groq avec historique complet - comme le test Python"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(historique)
    messages.append({"role": "user", "content": texte})

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        max_tokens=900,
        temperature=0.3
    )
    return response.choices[0].message.content


def traiter_reponse_groq(raw):
    """Separer texte visible et tag - identique au test Python"""
    texte = raw.strip()
    tag = "RIEN"

    if "|||" in raw:
        idx = raw.rfind("|||")
        texte = raw[:idx].strip()
        tag = raw[idx+3:].strip()

    # Nettoyage residus
    import re
    texte = re.sub(r'\|\|\|[\s\S]*', '', texte)
    texte = re.sub(r'LEAD:[\w=|.\s\u0600-\u06FF]*', '', texte)
    texte = texte.replace("|||", "").replace("RIEN", "").replace("FIN", "").strip()

    return texte, tag


# ============================================================
# ROUTES WEBHOOK
# ============================================================

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """Verification Meta"""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("[WEBHOOK] Verification reussie")
        return challenge, 200
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def receive_message():
    """Recevoir et traiter les messages WhatsApp"""
    try:
        body = request.get_json()

        # Extraire le message
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

        # Extraire texte
        if msg_type == "text":
            texte = message.get("text", {}).get("body", "").strip()
        elif msg_type == "interactive":
            texte = message.get("interactive", {}).get("button_reply", {}).get("title", "")
        else:
            return jsonify({"status": "ok"}), 200

        if not texte:
            return jsonify({"status": "ok"}), 200

        print(f"\n[MSG] {telephone} ({nom}): {texte}")

        # Recuperer session
        session = get_session(telephone)

        # Detecter langue
        if any('\u0600' <= c <= '\u06FF' for c in texte):
            session["langue"] = "AR"

        # Appeler Groq avec historique
        raw = appeler_groq(session["historique"], texte)
        texte_client, tag = traiter_reponse_groq(raw)

        # Fallback si reponse vide
        if not texte_client or len(texte_client) < 5:
            texte_client = "Desolee, une erreur est survenue. Appelez-nous au 05 23 30 31 94. Merci pour votre confiance."

        print(f"[BOT]: {texte_client[:100]}...")
        print(f"[TAG]: {tag}")

        # Mettre a jour historique
        session["historique"].append({"role": "user", "content": texte})
        session["historique"].append({"role": "assistant", "content": texte_client})

        # Limiter historique a 20 messages
        if len(session["historique"]) > 20:
            session["historique"] = session["historique"][-20:]

        # Envoyer reponse WhatsApp
        envoyer_whatsapp(telephone, texte_client)

        # Traiter lead si detecte
        if tag.startswith("LEAD:"):
            lead_data = extraire_lead(tag)
            if lead_data:
                print(f"[LEAD] {lead_data}")
                session["infos_collectees"].update(lead_data)
                notifier_conseiller(telephone, nom, lead_data)

        # Fin de conversation
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
