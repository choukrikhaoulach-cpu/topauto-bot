# -*- coding: utf-8 -*-
"""
TopAuto Mohammedia — WhatsApp Bot
Architecture : Flask + Groq LLM + Google Sheets + WhatsApp Business API
"""
import os, re, json, base64, requests
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# ============================================================
# CONFIGURATION — toutes les vars lues dynamiquement
# ============================================================
def cfg(key, fallback=""):
    return os.environ.get(key, fallback)

PHONE_NUMBER_ID  = cfg("PHONE_NUMBER_ID",  "1031404513398168")
VERIFY_TOKEN     = cfg("VERIFY_TOKEN",     "topauto2024secret")
CONSEILLER_TEL   = cfg("CONSEILLER_WHATSAPP", "212774057668")

# IDs Google Sheets hardcodés en fallback (lus dynamiquement en priorité)
_SH_VENTES   = "104zrDmipMrXOzbXajmd9I6hf8WHVeogC8LU0GFXNk1I"
_SH_FACTURES = "12Zwfi5H3vxKJDN---5qeZspuqwd-VjQthfe4uZrUTGg"
_SH_SAV      = "12GxqngDty_PniBNkMycGGqHD6MWrXEAYjPsRKkvLI8A"

def sh_ventes():   return cfg("GOOGLE_SHEET_VENTES",   _SH_VENTES)
def sh_factures(): return cfg("GOOGLE_SHEET_FACTURES", _SH_FACTURES)
def sh_sav():      return cfg("GOOGLE_SHEET_SAV",      _SH_SAV)

SHEET_MAP = {
    "vn":                  lambda: (sh_ventes(),   "VN_Leads"),
    "vo":                  lambda: (sh_ventes(),   "VO_Leads"),
    "essai":               lambda: (sh_ventes(),   "Essais_VN"),
    "facture_vente":       lambda: (sh_factures(), "Factures_Vente"),
    "facture_mecanique":   lambda: (sh_factures(), "Factures_Mecanique"),
    "facture_carrosserie": lambda: (sh_factures(), "Factures_Carrosserie"),
    "facture_pieces":      lambda: (sh_factures(), "Factures_Pieces"),
    "sav_atelier":         lambda: (sh_sav(),      "SAV_Atelier"),
    "reclamation":         lambda: (sh_sav(),      "Reclamations"),
    "mainlevee":           lambda: (sh_sav(),      "Mainlevee"),
    "rdi":                 lambda: (sh_sav(),      "RDI_Immatriculation"),
}

def get_sheet_config(type_lead):
    fn = SHEET_MAP.get(type_lead.lower(), lambda: (sh_ventes(), "VN_Leads"))
    sid, sname = fn()
    print(f"[SHEETS] type={type_lead} | sheet={'OK' if sid else 'VIDE'} | onglet={sname}")
    return sid, sname

# ============================================================
# GOOGLE SHEETS SERVICE
# ============================================================
def get_sheets_service():
    try:
        creds_json = cfg("GOOGLE_CREDS_JSON")
        if not creds_json:
            print("[SHEETS] GOOGLE_CREDS_JSON absent")
            return None
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds = service_account.Credentials.from_service_account_info(
            json.loads(creds_json),
            scopes=["https://www.googleapis.com/auth/spreadsheets"])
        return build("sheets", "v4", credentials=creds)
    except Exception as e:
        print(f"[SHEETS] Erreur service: {e}")
        return None

def enregistrer_lead(telephone, langue, lead_data):
    try:
        svc = get_sheets_service()
        if not svc:
            return False
        t = lead_data.get("type", "vn").lower()
        sid, sname = get_sheet_config(t)
        if not sid:
            print(f"[SHEETS] Sheet ID vide — type={t}")
            return False
        now = datetime.now()
        # Chercher ligne existante par telephone WA (col L = index 11)
        res = svc.spreadsheets().values().get(
            spreadsheetId=sid, range=f"{sname}!A:P").execute()
        rows = res.get("values", [])
        exist_idx = next((i+1 for i, r in enumerate(rows) if len(r) > 11 and r[11] == telephone), None)
        row = [
            now.strftime("%Y%m%d%H%M%S"), now.strftime("%d/%m/%Y %H:%M"),
            lead_data.get("prenom",""), lead_data.get("nom",""),
            lead_data.get("tel",""),
            lead_data.get("modele", lead_data.get("vehicule","")),
            lead_data.get("chassis",""),
            lead_data.get("cin", lead_data.get("rc","")),
            lead_data.get("ville",""),
            lead_data.get("type_facture", lead_data.get("type_doc","")),
            lead_data.get("description", lead_data.get("reclamation","")),
            telephone, langue, t, "WhatsApp Bot", "NOUVEAU"
        ]
        if exist_idx:
            svc.spreadsheets().values().update(
                spreadsheetId=sid,
                range=f"{sname}!A{exist_idx}:P{exist_idx}",
                valueInputOption="USER_ENTERED", body={"values":[row]}).execute()
            print(f"[SHEETS] MAJ {sname} ligne {exist_idx}")
        else:
            svc.spreadsheets().values().append(
                spreadsheetId=sid, range=f"{sname}!A:P",
                valueInputOption="USER_ENTERED", body={"values":[row]}).execute()
            print(f"[SHEETS] INSERT {sname}")
        return True
    except Exception as e:
        print(f"[SHEETS] Erreur insert: {e}")
        return False

def verifier_rdi(chassis):
    try:
        svc = get_sheets_service()
        sid = sh_sav()
        if not svc or not sid:
            return None
        res = svc.spreadsheets().values().get(
            spreadsheetId=sid, range="RDI_Immatriculation!A:P").execute()
        rows = res.get("values", [])
        cl = chassis.lower().strip()
        for r in rows[1:]:
            if len(r) > 6 and r[6].lower().strip() == cl:
                return {
                    "trouve": True,
                    "statut": r[10] if len(r) > 10 else "En cours",
                    "date_dispo": r[11] if len(r) > 11 else ""
                }
        return {"trouve": False, "statut": "NON_TROUVE", "date_dispo": ""}
    except Exception as e:
        print(f"[RDI] Erreur: {e}")
        return None

# ============================================================
# SESSIONS — gestion d'état par client
# ============================================================
sessions = {}

def get_session(tel):
    if tel not in sessions:
        sessions[tel] = {
            "historique": [],
            "langue": "FR",
            "flux": None,          # flux actif : essai / rdi / facture / ...
            "infos": {},           # infos collectées dans le flux
            "attente_confirmation": False  # True = on attend oui/non après récap
        }
    return sessions[tel]

# ============================================================
# SYSTEM PROMPT — compact, clair, respecte le cahier des charges
# ============================================================
SYSTEM_PROMPT = """Tu es l'Assistant Virtuel officiel de TopAuto Mohammedia, concessionnaire agréé Renault et Dacia.

== IDENTITE ==
Nom : Assistant Virtuel TopAuto. Professionnel, chaleureux, concis. Disponible 24/7.

== REGLES ABSOLUES ==
1. JAMAIS de prix, tarifs, mensualités — orienter vers conseiller.
2. Une seule question par message. Jamais deux.
3. Ne jamais répéter le message de bienvenue.
4. Répondre DIRECTEMENT à la demande sans introduction.
5. Chaque flux est INDEPENDANT — ne jamais mélanger RDI / essai / facture / SAV.
6. JAMAIS reposer une question déjà répondue dans la même conversation.
7. Terminer TOUJOURS par : Merci pour votre confiance. (FR) / Chokran 3la t9a dyalek. (Darija) / شكرا على ثقتك. (AR)
8. Aucun emoji.

== LANGUE ==
Arabe (caractères arabes) → répondre en arabe
Darija latinisée (mots comme "bghit", "wach", "safi") → répondre en darija latinisée
Par défaut → français

== ETABLISSEMENT ==
TopAuto Mohammedia | Q.I Bd Sidi Mohamed Ben Abdellah, 208000 Mohammedia
Tel : 0523303194 (Renault) / 0523303195 (Dacia) | contact@top-auto.ma
GPS : 33.683384 N, 7.409769 W | Lun-Ven 8h-18h30 | Sam 8h30-15h | Dim fermé
Facebook : @topauto | Instagram : @top_auto_mohammedia
Localisation Google Maps : https://maps.google.com/?q=33.683384,-7.409769

== VEHICULES NEUFS DACIA ==
Spring électrique 24.3kWh 70/100ch | Sandero Streetway 2026 SCe65/TCe100/dCi102ch | Sandero Stepway TCe100/dCi102ch CVT | Logan coffre528L | Jogger 5/7pl HEV140ch | Duster 2025 dCi115/TCe130ch | Bigster 2025 HEV155ch toitPano

== VEHICULES NEUFS RENAULT VP ==
Clio5/6 TCe100/diesel/ETech145ch | Captur ETech145ch OpenRLink | R5 ETech électrique 400km | Express diesel | Mégane Sedan diesel | Mégane ETech 60kWh 450km | Arkana ETech145ch | Austral ETech200ch 2025 | Kardian SOMACA TCe100/dCi102ch

== RENAULT VU ==
Express Van 800kg 3.3m3 | Trafic Combi 9pl | Master 8-17m3

== VEHICULES OCCASION ==
Stock : https://top-auto.ma/Voitures_occasion
Collecter : prénom, nom, téléphone → type=vo

== SAV ATELIER ==
RDV via formulaire : https://top-auto.ma/Entretienr%C3%A9paration
(Renault : concessionnaire.renault.ma/top-auto-mohammedia.html | Dacia : reseau.dacia.ma/top-auto-mohammedia.html)
Collecter : prénom, nom, téléphone → type=sav_atelier

== MAINLEVEE ==
Documents : CIN + carte grise + relevé bancaire RCI + justificatif valeur résiduelle
RIB RCI Finance : 007 780 00000 054111 70005 29
Collecter : prénom, nom, téléphone, chassis → type=mainlevee

== RDI (Récépissé Dépôt Immatriculation) ==
Traité UNIQUEMENT si +30 jours depuis livraison.
Flux STRICT (ne jamais sauter d'étape, ne jamais mélanger avec essai) :
Étape 1 : "Votre véhicule a-t-il été livré il y a plus de 30 jours ?"
Étape 2 : "Êtes-vous un particulier ou une société ?"
Étape 3 : Prénom
Étape 4 : Numéro de châssis
Étape 5 : CIN (particulier) ou RC (société)
Étape 6 : Téléphone
Après collecte → type=rdi

== ESSAI VEHICULE NEUF ==
Flux STRICT et INDEPENDANT (ne jamais poser de questions RDI ici) :
Étape 1 : Prénom
Étape 2 : Nom
Étape 3 : Téléphone
Étape 4 : Modèle souhaité
Étape 5 : Ville
Après collecte → type=essai

== FACTURES ==
Identifier d'abord le type, puis collecter :
Vente VN/VO → chassis, nom titulaire, tel → type=facture_vente
Mécanique → matricule/chassis, nom, tel → type=facture_mecanique
Carrosserie → matricule/chassis, nom, tel → type=facture_carrosserie
Pièces → matricule/chassis, nom, tel → type=facture_pieces

== RECLAMATIONS ==
Collecter : prénom, nom, tel, chassis si applicable, description → type=reclamation
Confirmer traitement sous 48h.

== SUIVI TRAVAUX/COMMANDES/PIECES ==
Rediriger : "Pour le suivi, contactez le 0523303194."

== FINANCEMENT MOBILIZE ==
Présenter sans taux ni mensualités : Crédit 12-72mois, ZEN, Easy, Gratuit 0%, LOA
→ Orienter conseiller. Collecter prénom, tel, modèle.

== COLLECTE INFOS ==
UNE seule info par message.
Ne JAMAIS reposer une question déjà répondue.
Ne JAMAIS demander "votre prénom est X ?" pour confirmer — juste poser la question suivante.

== CONFIRMATION FINALE ==
Quand toutes les infos d'un flux sont collectées, afficher un récapitulatif :
"Récapitulatif :
- Prénom : X
- Nom : X
- Téléphone : X
- [autres infos]
Ces informations sont-elles correctes ? (Oui / Non)"
Attendre confirmation avant d'envoyer le tag LEAD.
Si le client dit Non → demander quelle info modifier.

== FORMAT OBLIGATOIRE ==
Chaque réponse DOIT contenir ||| :
[Texte réponse]|||TAG

TAGS :
|||RIEN
|||RECAP:prenom=X|nom=X|tel=X|modele=X|ville=X|type=essai
|||RECAP:prenom=X|nom=X|tel=X|chassis=X|cin=X|type=rdi
|||RECAP:prenom=X|nom=X|tel=X|chassis=X|rc=X|type=rdi
|||RECAP:prenom=X|nom=X|tel=X|chassis=X|type=mainlevee
|||RECAP:prenom=X|nom=X|tel=X|modele=X|type=vn
|||RECAP:prenom=X|nom=X|tel=X|modele=X|type=vo
|||RECAP:prenom=X|nom=X|tel=X|chassis=X|type_facture=vente|type=facture_vente
|||RECAP:prenom=X|nom=X|tel=X|chassis=X|type_facture=mecanique|type=facture_mecanique
|||RECAP:prenom=X|nom=X|tel=X|chassis=X|type_facture=carrosserie|type=facture_carrosserie
|||RECAP:prenom=X|nom=X|tel=X|chassis=X|type_facture=pieces|type=facture_pieces
|||RECAP:prenom=X|nom=X|tel=X|vehicule=X|type=sav_atelier
|||RECAP:prenom=X|nom=X|tel=X|chassis=X|reclamation=X|type=reclamation
|||LEAD:prenom=X|nom=X|tel=X|...|type=X   ← UNIQUEMENT après confirmation client
|||FIN

REGLES FORMAT :
- JAMAIS écrire ||| ou LEAD ou RECAP dans le texte visible
- RECAP = collecte terminée, attendre confirmation
- LEAD = client a confirmé, enregistrer
- Si infos incomplètes → |||RIEN
- LEAD seulement si prénom ET téléphone réels"""

# ============================================================
# GROQ LLM
# ============================================================
def appeler_groq(historique, texte):
    key = cfg("GROQ_API_KEY")
    msgs = [{"role":"system","content":SYSTEM_PROMPT}] + historique[-12:] + [{"role":"user","content":texte}]
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
        json={"model":"llama-3.3-70b-versatile","messages":msgs,"max_tokens":600,"temperature":0.15},
        timeout=30)
    print(f"[GROQ] {r.status_code}")
    if r.status_code != 200:
        raise Exception(f"Groq {r.status_code}: {r.text[:150]}")
    return r.json()["choices"][0]["message"]["content"]

def appeler_groq_vision(img_b64, mime):
    key = cfg("GROQ_API_KEY")
    prompt = """Expert automobile TopAuto Mohammedia. Analyse cette image :
1. Problème visible (rayure, bosselure, voyant, pneu, panne)
2. Classification : carrosserie / mécanique / électronique / pneu / autre
3. Gravité : faible / modéré / urgent
4. Recommandation : atelier SAV / surveillance / aucune action urgente
Réponds en français. Termine par : Merci pour votre confiance."""
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
        json={"model":"meta-llama/llama-4-scout-17b-16e-instruct",
              "messages":[{"role":"user","content":[
                  {"type":"image_url","image_url":{"url":f"data:{mime};base64,{img_b64}"}},
                  {"type":"text","text":prompt}]}],
              "max_tokens":500},timeout=30)
    if r.status_code != 200:
        return "Impossible d'analyser cette image. Présentez-vous en atelier. Merci pour votre confiance."
    return r.json()["choices"][0]["message"]["content"]

def parse_reponse(raw):
    texte, tag = raw.strip(), "RIEN"
    if "|||" in raw:
        idx = raw.rfind("|||")
        texte, tag = raw[:idx].strip(), raw[idx+3:].strip()
    texte = re.sub(r'\|\|\|[\s\S]*','',texte)
    texte = re.sub(r'(LEAD|RECAP):[\w=|.\s\u0600-\u06FF-]*','',texte)
    texte = texte.replace("|||","").replace("RIEN","").replace("FIN","").strip()
    return texte, tag

def extraire_data(tag):
    """Extrait un dict depuis LEAD:... ou RECAP:..."""
    prefix = "LEAD:" if tag.startswith("LEAD:") else "RECAP:" if tag.startswith("RECAP:") else None
    if not prefix:
        return {}
    d = {}
    for p in tag.replace(prefix,"").split("|"):
        i = p.find("=")
        if i > 0:
            k, v = p[:i].strip(), p[i+1:].strip()
            if k and v and v not in ["X","","null","?"]:
                d[k] = v
    return d

# ============================================================
# WHATSAPP HELPERS
# ============================================================
def wa_send(tel, msg):
    tok = cfg("WHATSAPP_TOKEN")
    pid = cfg("PHONE_NUMBER_ID", PHONE_NUMBER_ID)
    r = requests.post(
        f"https://graph.facebook.com/v20.0/{pid}/messages",
        headers={"Authorization":f"Bearer {tok}","Content-Type":"application/json"},
        json={"messaging_product":"whatsapp","to":tel,"type":"text","text":{"body":msg}},
        timeout=10)
    print(f"[WA] text {r.status_code}")
    return r.status_code == 200

def wa_boutons(tel, body, btns):
    tok = cfg("WHATSAPP_TOKEN")
    pid = cfg("PHONE_NUMBER_ID", PHONE_NUMBER_ID)
    r = requests.post(
        f"https://graph.facebook.com/v20.0/{pid}/messages",
        headers={"Authorization":f"Bearer {tok}","Content-Type":"application/json"},
        json={"messaging_product":"whatsapp","to":tel,"type":"interactive",
              "interactive":{"type":"button","body":{"text":body},
                             "action":{"buttons":[{"type":"reply","reply":{"id":b["id"],"title":b["title"]}} for b in btns[:3]]}}},
        timeout=10)
    print(f"[WA] btns {r.status_code}")
    return r.status_code == 200

def wa_bienvenue(tel):
    wa_boutons(tel,
        "Bonjour et bienvenue chez TopAuto Mohammedia, concessionnaire agréé Renault et Dacia.\n\n"
        "Je suis l'Assistant Virtuel, disponible 24/7 pour vous accompagner concernant :\n"
        "- Les véhicules Renault et Dacia (neufs et occasion)\n"
        "- L'entretien et les réparations\n"
        "- Les pièces de rechange et carrosserie\n"
        "- Les demandes administratives\n"
        "- Les rendez-vous après-vente\n\n"
        "Comment puis-je vous aider aujourd'hui ? Merci pour votre confiance.",
        [{"id":"btn_vehicules","title":"Véhicules"},
         {"id":"btn_sav","title":"SAV & Atelier"},
         {"id":"btn_autre","title":"Autre demande"}])

def wa_menu_vehicules(tel):
    wa_boutons(tel, "Quelle gamme vous intéresse ?",
        [{"id":"btn_vn","title":"Véhicules Neufs"},
         {"id":"btn_vo","title":"Véhicules Occasion"},
         {"id":"btn_essai","title":"Essai Gratuit"}])

def wa_menu_autre(tel):
    wa_boutons(tel, "Quelle est votre demande ?",
        [{"id":"btn_facture","title":"Demande Facture"},
         {"id":"btn_mainlevee","title":"Mainlevée"},
         {"id":"btn_reclamation","title":"Réclamation"}])

def notifier_conseiller(tel, nom_wa, data):
    t = data.get("type","vn")
    _, sname = get_sheet_config(t)
    lignes = [f"--- NOUVEAU : {sname} ---", f"WA : {tel}", f"Nom WA : {nom_wa}"]
    for k,l in [("prenom","Prénom"),("nom","Nom"),("tel","Tel"),("modele","Modèle"),
                ("ville","Ville"),("chassis","Châssis"),("cin","CIN"),("rc","RC"),
                ("type_facture","Type facture"),("reclamation","Réclamation"),("description","Desc")]:
        if data.get(k): lignes.append(f"{l} : {data[k]}")
    lignes.append(f"Statut : {'URGENT 48h' if t=='reclamation' else 'À RAPPELER'}")
    wa_send(cfg("CONSEILLER_WHATSAPP", CONSEILLER_TEL), "\n".join(lignes))

def recap_texte(data):
    t = "Récapitulatif de votre demande :\n"
    for k,l in [("prenom","Prénom"),("nom","Nom"),("tel","Téléphone"),
                ("modele","Modèle"),("ville","Ville"),("chassis","Châssis"),
                ("cin","CIN"),("rc","RC"),("type_facture","Type facture"),
                ("reclamation","Réclamation")]:
        if data.get(k) and data[k] not in ["X","","null","?"]:
            t += f"- {l} : {data[k]}\n"
    t += "\nCes informations sont-elles correctes ? (Oui / Non)"
    return t

# ============================================================
# WEBHOOK
# ============================================================
@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.mode") == "subscribe" and \
       request.args.get("hub.verify_token") == cfg("VERIFY_TOKEN", VERIFY_TOKEN):
        return request.args.get("hub.challenge"), 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def receive():
    try:
        body = request.get_json()
        msgs = body.get("entry",[{}])[0].get("changes",[{}])[0].get("value",{}).get("messages",[])
        if not msgs:
            return jsonify({"status":"ok"}), 200

        msg = msgs[0]
        tel  = msg.get("from")
        nom  = body.get("entry",[{}])[0].get("changes",[{}])[0].get("value",{}).get("contacts",[{}])[0].get("profile",{}).get("name","Client")
        mtype = msg.get("type")
        tok_wa = cfg("WHATSAPP_TOKEN")

        # ---- AUDIO ----
        if mtype == "audio":
            wa_send(tel, "Message vocal reçu, transcription en cours...")
            mid = msg.get("audio",{}).get("id")
            if not mid:
                wa_send(tel, "Impossible de traiter ce vocal. Merci d'écrire.")
                return jsonify({"status":"ok"}), 200
            h = {"Authorization":f"Bearer {tok_wa}"}
            ru = requests.get(f"https://graph.facebook.com/v20.0/{mid}", headers=h, timeout=10)
            if ru.status_code != 200:
                wa_send(tel, "Erreur audio. Appelez le 0523303194.")
                return jsonify({"status":"ok"}), 200
            ra = requests.get(ru.json().get("url"), headers=h, timeout=20)
            rw = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization":f"Bearer {cfg('GROQ_API_KEY')}"},
                files={"file":("a.ogg", ra.content,"audio/ogg")},
                data={"model":"whisper-large-v3","language":"fr","response_format":"text"},
                timeout=30)
            if rw.status_code != 200 or not rw.text.strip():
                wa_send(tel, "Transcription impossible. Merci d'écrire votre demande.")
                return jsonify({"status":"ok"}), 200
            texte = rw.text.strip()
            wa_send(tel, f"J'ai bien entendu : \"{texte}\"")

        # ---- IMAGE ----
        elif mtype == "image":
            wa_send(tel, "Photo reçue, analyse en cours...")
            mid = msg.get("image",{}).get("id")
            mime = msg.get("image",{}).get("mime_type","image/jpeg")
            if not mid:
                wa_send(tel, "Impossible d'analyser. Merci pour votre confiance.")
                return jsonify({"status":"ok"}), 200
            h = {"Authorization":f"Bearer {tok_wa}"}
            ru = requests.get(f"https://graph.facebook.com/v20.0/{mid}", headers=h, timeout=10)
            if ru.status_code != 200:
                wa_send(tel, "Erreur téléchargement image.")
                return jsonify({"status":"ok"}), 200
            ri = requests.get(ru.json().get("url"), headers=h, timeout=20)
            if ri.status_code != 200:
                wa_send(tel, "Erreur téléchargement image.")
                return jsonify({"status":"ok"}), 200
            analyse = appeler_groq_vision(base64.b64encode(ri.content).decode(), mime)
            wa_send(tel, analyse)
            wa_boutons(tel, "Souhaitez-vous prendre rendez-vous en atelier ?",
                [{"id":"btn_rdv_sav","title":"Prendre RDV"},
                 {"id":"btn_autre_question","title":"Autre question"}])
            return jsonify({"status":"ok"}), 200

        # ---- TEXTE ----
        elif mtype == "text":
            texte = msg.get("text",{}).get("body","").strip()
        elif mtype == "interactive":
            br = msg.get("interactive",{}).get("button_reply",{})
            texte = br.get("title","")
        else:
            return jsonify({"status":"ok"}), 200

        if not texte:
            return jsonify({"status":"ok"}), 200

        print(f"\n[MSG] {tel} ({nom}): {texte}")
        sess = get_session(tel)

        # Détecter langue
        if any('\u0600' <= c <= '\u06FF' for c in texte):
            sess["langue"] = "AR"
        elif any(w in texte.lower() for w in ["bghit","wach","safi","3afak","chokran","labas","mzyan","iyeh","wah","daba"]):
            sess["langue"] = "DARIJA"

        tl = texte.lower().strip()
        saluts = ["bonjour","salam","salut","hi","hello","bonsoir","مرحبا","السلام",
                  "ahlan","bjr","bsr","coucou","sbah","msa","slm","labas","la bas"]

        # Salutation initiale → bienvenue
        mots = tl.split()
        if not sess["historique"] and len(mots) <= 3 and any(s in tl for s in saluts):
            wa_bienvenue(tel)
            return jsonify({"status":"ok"}), 200

        # ---- GESTION BOUTONS ----
        if mtype == "interactive":
            bid = msg.get("interactive",{}).get("button_reply",{}).get("id","")
            if bid == "btn_vehicules":
                wa_menu_vehicules(tel)
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_sav":
                texte = "Je veux prendre un rendez-vous SAV atelier"
            elif bid == "btn_autre":
                wa_menu_autre(tel)
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_vn":
                texte = "Je veux des informations sur les véhicules neufs"
            elif bid == "btn_vo":
                texte = "Je veux des informations sur les véhicules d'occasion"
            elif bid == "btn_essai":
                texte = "Je veux faire un essai de véhicule neuf"
            elif bid == "btn_facture":
                texte = "Je veux demander une facture"
            elif bid == "btn_mainlevee":
                texte = "Je veux faire une demande de mainlevée"
            elif bid == "btn_reclamation":
                texte = "J'ai une réclamation"
            elif bid == "btn_rdv_sav":
                wa_send(tel, "Pour votre rendez-vous atelier :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\nUn conseiller vous confirmera. Merci pour votre confiance.")
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_autre_question":
                wa_send(tel, "Je suis à votre écoute. Merci pour votre confiance.")
                return jsonify({"status":"ok"}), 200

        # ---- CAS CONFIRMATION APRES RECAP ----
        if sess.get("attente_confirmation") and sess.get("infos"):
            confirm_oui = any(w in tl for w in ["oui","yes","wah","iyeh","safi","ok","correct","parfait","exactement","c bon","c'est bon"])
            confirm_non = any(w in tl for w in ["non","no","la","modifier","changer","corriger","pas correct","faux","erreur"])

            if confirm_oui:
                data = sess["infos"]
                t = data.get("type","vn")
                # RDI → vérifier dans sheets
                if t == "rdi" and data.get("chassis"):
                    info_rdi = verifier_rdi(data["chassis"])
                    if info_rdi is None:
                        reponse = "Impossible d'accéder au système pour le moment. Notre équipe vous contactera. Merci pour votre confiance."
                    elif info_rdi["trouve"]:
                        reponse = f"Vérification de votre dossier :\nChâssis : {data['chassis']}\nStatut : {info_rdi['statut']}"
                        if info_rdi["date_dispo"]:
                            reponse += f"\nDate de disponibilité : {info_rdi['date_dispo']}"
                        reponse += "\n\nPour plus d'info : 0523303194. Merci pour votre confiance."
                    else:
                        reponse = f"Le dossier pour le châssis {data['chassis']} n'est pas encore enregistré. Notre équipe vous contactera. Merci pour votre confiance."
                    wa_send(tel, reponse)
                else:
                    wa_send(tel, "Votre demande a bien été enregistrée. Notre équipe vous contactera très prochainement. Merci pour votre confiance.")

                notifier_conseiller(tel, nom, data)
                enregistrer_lead(tel, sess["langue"], data)
                sess["attente_confirmation"] = False
                sess["infos"] = {}
                sess["flux"] = None
                return jsonify({"status":"ok"}), 200

            elif confirm_non:
                wa_send(tel, "Quelle information souhaitez-vous modifier ? (ex: prénom, téléphone, modèle...)")
                sess["attente_confirmation"] = False
                return jsonify({"status":"ok"}), 200

        # ---- APPEL GROQ ----
        raw = appeler_groq(sess["historique"], texte)
        tc, tag = parse_reponse(raw)

        # Fallback texte vide
        if not tc or len(tc) < 3:
            data_tmp = extraire_data(tag)
            if data_tmp and (tag.startswith("RECAP:") or tag.startswith("LEAD:")):
                tc = recap_texte(data_tmp)
                if tag.startswith("LEAD:"):
                    tag = tag.replace("LEAD:", "RECAP:")
            else:
                tc = "Désolée, une erreur est survenue. Contactez-nous au 0523303194. Merci pour votre confiance."

        # Traiter RECAP — attendre confirmation
        if tag.startswith("RECAP:"):
            data = extraire_data(tag)
            if data.get("prenom") and data.get("tel"):
                sess["infos"] = data
                sess["flux"] = data.get("type","vn")
                sess["attente_confirmation"] = True
                # Générer récap propre
                tc = recap_texte(data)
            else:
                tag = "RIEN"

        # Traiter LEAD direct (client a déjà confirmé ou LLM génère LEAD)
        elif tag.startswith("LEAD:"):
            data = extraire_data(tag)
            if data.get("prenom") and data.get("tel"):
                sess["infos"] = data
                sess["attente_confirmation"] = True
                tc = recap_texte(data)
                tag = "RECAP"  # forcer confirmation

        print(f"[BOT] {tc[:80]}...")
        print(f"[TAG] {tag}")

        sess["historique"].append({"role":"user","content":texte})
        sess["historique"].append({"role":"assistant","content":tc})
        if len(sess["historique"]) > 16:
            sess["historique"] = sess["historique"][-16:]

        wa_send(tel, tc)

        if tag == "FIN" and tel in sessions:
            del sessions[tel]

        return jsonify({"status":"ok"}), 200

    except Exception as e:
        print(f"[ERREUR] {e}")
        return jsonify({"status":"error"}), 200

@app.route("/", methods=["GET"])
def home():
    return "TopAuto WhatsApp Bot - Online", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[START] TopAuto Bot port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
