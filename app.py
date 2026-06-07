# -*- coding: utf-8 -*-
import os, re, json, base64, requests
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# ============================================================
# CONFIG
# ============================================================
def cfg(k, fb=""):
    return os.environ.get(k, fb)

PHONE_NUMBER_ID = cfg("PHONE_NUMBER_ID", "1031404513398168")
VERIFY_TOKEN    = cfg("VERIFY_TOKEN",    "topauto2024secret")
CONSEILLER_TEL  = cfg("CONSEILLER_WHATSAPP", "212774057668")

_SH_V = "104zrDmipMrXOzbXajmd9I6hf8WHVeogC8LU0GFXNk1I"
_SH_F = "12Zwfi5H3vxKJDN---5qeZspuqwd-VjQthfe4uZrUTGg"
_SH_S = "12GxqngDty_PniBNkMycGGqHD6MWrXEAYjPsRKkvLI8A"

def sh_v(): return cfg("GOOGLE_SHEET_VENTES",   _SH_V)
def sh_f(): return cfg("GOOGLE_SHEET_FACTURES", _SH_F)
def sh_s(): return cfg("GOOGLE_SHEET_SAV",      _SH_S)

SHEET_CFG = {
    "vn":                  lambda: (sh_v(), "VN_Leads"),
    "vo":                  lambda: (sh_v(), "VO_Leads"),
    "essai":               lambda: (sh_v(), "Essais_VN"),
    "facture_vente":       lambda: (sh_f(), "Factures_Vente"),
    "facture_mecanique":   lambda: (sh_f(), "Factures_Mecanique"),
    "facture_carrosserie": lambda: (sh_f(), "Factures_Carrosserie"),
    "facture_pieces":      lambda: (sh_f(), "Factures_Pieces"),
    "sav_atelier":         lambda: (sh_s(), "SAV_Atelier"),
    "reclamation":         lambda: (sh_s(), "Reclamations"),
    "mainlevee":           lambda: (sh_s(), "Mainlevee"),
    "rdi":                 lambda: (sh_s(), "RDI_Immatriculation"),
}

def get_sheet(t):
    sid, sn = SHEET_CFG.get(t.lower(), lambda: (sh_v(), "VN_Leads"))()
    print(f"[SHEETS] type={t} sheet={'OK' if sid else 'VIDE'} onglet={sn}")
    return sid, sn

# ============================================================
# GOOGLE SHEETS
# ============================================================
def gsheets():
    try:
        cj = cfg("GOOGLE_CREDS_JSON")
        if not cj: return None
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds = service_account.Credentials.from_service_account_info(
            json.loads(cj), scopes=["https://www.googleapis.com/auth/spreadsheets"])
        return build("sheets", "v4", credentials=creds)
    except Exception as e:
        print(f"[SHEETS] ERR service: {e}")
        return None

def enregistrer(tel, langue, data):
    try:
        svc = gsheets()
        if not svc: return False
        t = data.get("type","vn").lower()
        sid, sn = get_sheet(t)
        if not sid:
            print(f"[SHEETS] sheet ID vide pour type={t}")
            return False
        now = datetime.now()
        res = svc.spreadsheets().values().get(spreadsheetId=sid, range=f"{sn}!A:P").execute()
        rows = res.get("values",[])
        idx = next((i+1 for i,r in enumerate(rows) if len(r)>11 and r[11]==tel), None)
        row = [now.strftime("%Y%m%d%H%M%S"), now.strftime("%d/%m/%Y %H:%M"),
               data.get("prenom",""), data.get("nom",""), data.get("tel",""),
               data.get("modele", data.get("vehicule","")), data.get("chassis",""),
               data.get("cin", data.get("rc","")), data.get("ville",""),
               data.get("type_facture", data.get("type_doc","")),
               data.get("description", data.get("reclamation","")),
               tel, langue, t, "WhatsApp Bot", "NOUVEAU"]
        if idx:
            svc.spreadsheets().values().update(
                spreadsheetId=sid, range=f"{sn}!A{idx}:P{idx}",
                valueInputOption="USER_ENTERED", body={"values":[row]}).execute()
            print(f"[SHEETS] MAJ {sn} ligne {idx}")
        else:
            svc.spreadsheets().values().append(
                spreadsheetId=sid, range=f"{sn}!A:P",
                valueInputOption="USER_ENTERED", body={"values":[row]}).execute()
            print(f"[SHEETS] INSERT {sn}")
        return True
    except Exception as e:
        print(f"[SHEETS] ERR insert: {e}")
        return False

def verifier_rdi(chassis):
    try:
        svc = gsheets()
        sid = sh_s()
        if not svc or not sid: return None
        res = svc.spreadsheets().values().get(spreadsheetId=sid, range="RDI_Immatriculation!A:P").execute()
        cl = chassis.lower().strip()
        for r in res.get("values",[])[1:]:
            if len(r)>6 and r[6].lower().strip()==cl:
                return {"trouve":True, "statut":r[10] if len(r)>10 else "En cours",
                        "date_dispo":r[11] if len(r)>11 else ""}
        return {"trouve":False}
    except Exception as e:
        print(f"[RDI] ERR: {e}")
        return None

# ============================================================
# SESSIONS
# ============================================================
sessions = {}

def get_sess(tel):
    if tel not in sessions:
        sessions[tel] = {"hist":[], "langue":"FR", "infos":{}, "en_attente_confirm":False}
    return sessions[tel]

# ============================================================
# SYSTEM PROMPT
# ============================================================
SYSTEM_PROMPT = """Tu es l'Assistant Virtuel officiel de TopAuto Mohammedia, concessionnaire agréé Renault et Dacia.

== IDENTITE ==
Professionnel, chaleureux, concis. Disponible 24/7.

== REGLES ABSOLUES ==
1. JAMAIS de prix, tarifs, mensualités.
2. UNE seule question par message.
3. Ne JAMAIS répéter le message de bienvenue dans une conversation en cours.
4. Répondre DIRECTEMENT à la demande.
5. Chaque flux est INDEPENDANT — ne jamais mélanger RDI / essai / facture / SAV.
6. Ne JAMAIS reposer une question déjà répondue.
7. Terminer TOUJOURS par : Merci pour votre confiance. (FR) / Chokran 3la t9a dyalek. (Darija) / شكرا على ثقتك. (AR)
8. Aucun emoji.

== LANGUE ==
Arabe → répondre en arabe | Darija → répondre en darija | Défaut → français

== ETABLISSEMENT ==
TopAuto Mohammedia | Q.I Bd Sidi Mohamed Ben Abdellah, 208000 Mohammedia
Tel : 0523303194 (Renault) / 0523303195 (Dacia) | contact@top-auto.ma
GPS : 33.683384 N, 7.409769 W | Lun-Ven 8h-18h30 | Sam 8h30-15h | Dim fermé
Maps : https://maps.google.com/?q=33.683384,-7.409769

== VEHICULES NEUFS DACIA ==
Spring électrique 24.3kWh | Sandero Streetway 2026 | Sandero Stepway | Logan | Jogger HEV | Duster 2025 | Bigster 2025 HEV

== VEHICULES NEUFS RENAULT VP ==
Clio5/6 | Captur ETech | R5 ETech électrique | Express | Mégane Sedan | Mégane ETech | Arkana | Austral ETech200 | Kardian SOMACA

== RENAULT VU ==
Express Van | Trafic Combi 9pl | Master grand fourgon

== OCCASION ==
Stock : https://top-auto.ma/Voitures_occasion → collecter prénom, nom, tel → type=vo

== SAV ATELIER ==
Liens RDV : https://top-auto.ma/Entretienr%C3%A9paration
Collecter : prénom, nom, tel → type=sav_atelier

== MAINLEVEE ==
Docs : CIN + carte grise + relevé RCI + justif valeur résiduelle
RIB RCI : 007 780 00000 054111 70005 29
Collecter : prénom, nom, tel, chassis → type=mainlevee

== RDI — flux STRICT (ne pas mélanger avec essai) ==
Étape 1 : "Votre véhicule a-t-il été livré il y a plus de 30 jours ?"
Étape 2 : "Êtes-vous un particulier ou une société ?"
Étape 3 : Prénom
Étape 4 : Châssis
Étape 5 : CIN (particulier) ou RC (société)
Étape 6 : Téléphone
→ type=rdi

== ESSAI VN — flux STRICT (ne pas mélanger avec RDI) ==
Étape 1 : Prénom
Étape 2 : Nom
Étape 3 : Téléphone
Étape 4 : Modèle
Étape 5 : Ville
→ type=essai

== FACTURES ==
Vente → chassis, nom, tel → type=facture_vente
Mécanique → chassis, nom, tel → type=facture_mecanique
Carrosserie → chassis, nom, tel → type=facture_carrosserie
Pièces → chassis, nom, tel → type=facture_pieces

== RECLAMATIONS ==
Prénom, nom, tel, chassis si applicable, description → type=reclamation. Délai 48h.

== SUIVI TRAVAUX == → "Contactez le 0523303194."

== FINANCEMENT == → Présenter options sans chiffres, collecter prénom, tel, modèle.

== COLLECTE ==
Une seule info par message. Ne jamais reposer une question déjà répondue.

== CONFIRMATION ==
Quand TOUTES les infos d'un flux sont collectées :
1. Afficher récapitulatif propre
2. Demander "Ces informations sont-elles correctes ? (Oui / Non)"
3. Générer tag RECAP (PAS LEAD)

== FORMAT OBLIGATOIRE — chaque réponse DOIT avoir ||| ==
[Texte]|||TAG

TAGS :
|||RIEN
|||RECAP:prenom=X|nom=X|tel=X|type=essai|modele=X|ville=X
|||RECAP:prenom=X|nom=X|tel=X|type=rdi|chassis=X|cin=X
|||RECAP:prenom=X|nom=X|tel=X|type=rdi|chassis=X|rc=X
|||RECAP:prenom=X|nom=X|tel=X|type=mainlevee|chassis=X
|||RECAP:prenom=X|nom=X|tel=X|type=vn|modele=X
|||RECAP:prenom=X|nom=X|tel=X|type=vo
|||RECAP:prenom=X|nom=X|tel=X|type=facture_vente|chassis=X
|||RECAP:prenom=X|nom=X|tel=X|type=facture_mecanique|chassis=X
|||RECAP:prenom=X|nom=X|tel=X|type=facture_carrosserie|chassis=X
|||RECAP:prenom=X|nom=X|tel=X|type=facture_pieces|chassis=X
|||RECAP:prenom=X|nom=X|tel=X|type=sav_atelier
|||RECAP:prenom=X|nom=X|tel=X|type=reclamation|chassis=X|reclamation=X
|||FIN

REGLES FORMAT :
- JAMAIS ||| ou LEAD ou RECAP dans le texte visible
- RECAP quand toutes les infos collectées et on attend confirmation
- Si infos incomplètes → |||RIEN
- Prénom ET téléphone obligatoires pour RECAP"""

# ============================================================
# GROQ
# ============================================================
def groq_chat(hist, texte):
    key = cfg("GROQ_API_KEY")
    msgs = [{"role":"system","content":SYSTEM_PROMPT}] + hist[-12:] + [{"role":"user","content":texte}]
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
        json={"model":"llama-3.3-70b-versatile","messages":msgs,"max_tokens":600,"temperature":0.15},
        timeout=30)
    print(f"[GROQ] {r.status_code}")
    if r.status_code != 200:
        raise Exception(f"Groq {r.status_code}: {r.text[:150]}")
    return r.json()["choices"][0]["message"]["content"]

def groq_vision(b64, mime):
    key = cfg("GROQ_API_KEY")
    prompt = "Expert auto TopAuto. Analyse image: 1-problème 2-classification(carrosserie/mécanique/électronique/pneu) 3-gravité(faible/modéré/urgent) 4-recommandation. Français. Termine: Merci pour votre confiance."
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
        json={"model":"meta-llama/llama-4-scout-17b-16e-instruct",
              "messages":[{"role":"user","content":[
                  {"type":"image_url","image_url":{"url":f"data:{mime};base64,{b64}"}},
                  {"type":"text","text":prompt}]}],
              "max_tokens":500}, timeout=30)
    if r.status_code != 200:
        return "Impossible d'analyser. Présentez-vous en atelier. Merci pour votre confiance."
    return r.json()["choices"][0]["message"]["content"]

def groq_whisper(audio_bytes):
    key = cfg("GROQ_API_KEY")
    r = requests.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization":f"Bearer {key}"},
        files={"file":("a.ogg", audio_bytes,"audio/ogg")},
        data={"model":"whisper-large-v3","language":"fr","response_format":"text"},
        timeout=30)
    if r.status_code != 200 or not r.text.strip():
        return None
    return r.text.strip()

def parse_tag(raw):
    texte, tag = raw.strip(), "RIEN"
    if "|||" in raw:
        idx = raw.rfind("|||")
        texte, tag = raw[:idx].strip(), raw[idx+3:].strip()
    texte = re.sub(r'\|\|\|[\s\S]*','',texte)
    texte = re.sub(r'(LEAD|RECAP):[\w=|.\s\u0600-\u06FF-]*','',texte)
    texte = texte.replace("|||","").replace("RIEN","").replace("FIN","").strip()
    return texte, tag

def extraire(tag):
    pfx = "RECAP:" if tag.startswith("RECAP:") else "LEAD:" if tag.startswith("LEAD:") else None
    if not pfx: return {}
    d = {}
    for p in tag.replace(pfx,"").split("|"):
        i = p.find("=")
        if i > 0:
            k,v = p[:i].strip(), p[i+1:].strip()
            if k and v and v not in ["X","","null","?"]:
                d[k] = v
    return d

def recap_msg(d):
    t = "Récapitulatif de votre demande :\n"
    for k,l in [("prenom","Prénom"),("nom","Nom"),("tel","Téléphone"),
                ("modele","Modèle"),("ville","Ville"),("chassis","Châssis"),
                ("cin","CIN"),("rc","RC"),("type_facture","Type facture"),
                ("reclamation","Réclamation")]:
        if d.get(k) and d[k] not in ["X","","null","?"]:
            t += f"- {l} : {d[k]}\n"
    t += "\nCes informations sont-elles correctes ? (Oui / Non) Merci pour votre confiance."
    return t

# ============================================================
# WHATSAPP
# ============================================================
def wa_token(): return cfg("WHATSAPP_TOKEN")
def wa_pid():   return cfg("PHONE_NUMBER_ID", PHONE_NUMBER_ID)

def wa_text(tel, msg):
    r = requests.post(
        f"https://graph.facebook.com/v20.0/{wa_pid()}/messages",
        headers={"Authorization":f"Bearer {wa_token()}","Content-Type":"application/json"},
        json={"messaging_product":"whatsapp","to":tel,"type":"text","text":{"body":msg}},
        timeout=10)
    print(f"[WA] text {r.status_code}")
    return r.status_code == 200

def wa_btns(tel, body, btns):
    r = requests.post(
        f"https://graph.facebook.com/v20.0/{wa_pid()}/messages",
        headers={"Authorization":f"Bearer {wa_token()}","Content-Type":"application/json"},
        json={"messaging_product":"whatsapp","to":tel,"type":"interactive",
              "interactive":{"type":"button","body":{"text":body},
                "action":{"buttons":[{"type":"reply","reply":{"id":b["id"],"title":b["title"]}} for b in btns[:3]]}}},
        timeout=10)
    print(f"[WA] btns {r.status_code}")
    return r.status_code == 200

def wa_bienvenue(tel):
    wa_btns(tel,
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

def wa_menu_veh(tel):
    wa_btns(tel, "Quelle gamme vous intéresse ?",
        [{"id":"btn_vn","title":"Véhicules Neufs"},
         {"id":"btn_vo","title":"Véhicules Occasion"},
         {"id":"btn_essai","title":"Essai Gratuit"}])

def wa_menu_autre(tel):
    wa_btns(tel, "Quelle est votre demande ?",
        [{"id":"btn_facture","title":"Demande Facture"},
         {"id":"btn_mainlevee","title":"Mainlevée"},
         {"id":"btn_reclamation","title":"Réclamation"}])

def notifier(tel, nom_wa, data):
    t = data.get("type","vn")
    _, sn = get_sheet(t)
    lignes = [f"--- NOUVEAU : {sn} ---", f"WA : {tel}", f"Contact : {nom_wa}"]
    for k,l in [("prenom","Prénom"),("nom","Nom"),("tel","Tel"),("modele","Modèle"),
                ("ville","Ville"),("chassis","Châssis"),("cin","CIN"),("rc","RC"),
                ("type_facture","Type facture"),("reclamation","Réclamation"),("description","Desc")]:
        if data.get(k): lignes.append(f"{l} : {data[k]}")
    lignes.append(f"Statut : {'URGENT 48h' if t=='reclamation' else 'À RAPPELER'}")
    wa_text(cfg("CONSEILLER_WHATSAPP", CONSEILLER_TEL), "\n".join(lignes))

# ============================================================
# TEXTES BOUTONS → actions directes (sans passer par Groq)
# ============================================================
BOUTON_ACTIONS = {
    # bienvenue
    "véhicules": "MENU_VEH",
    "vehicules": "MENU_VEH",
    "sav & atelier": "SAV",
    "sav &amp; atelier": "SAV",
    "autre demande": "MENU_AUTRE",
    "autre": "MENU_AUTRE",
    # sous-menu véhicules
    "véhicules neufs": "VN",
    "vehicules neufs": "VN",
    "véhicules occasion": "VO",
    "vehicules occasion": "VO",
    "essai gratuit": "ESSAI",
    # sous-menu autre
    "demande facture": "FACTURE",
    "mainlevée": "MAINLEVEE",
    "mainlevee": "MAINLEVEE",
    "réclamation": "RECLAMATION",
    "reclamation": "RECLAMATION",
    # après image
    "prendre rdv": "RDV_SAV",
    "autre question": "AUTRE_Q",
}

TEXTE_TO_GROQ = {
    "VN":          "Je veux des informations sur les véhicules neufs Renault et Dacia disponibles",
    "VO":          "Je veux consulter les véhicules d'occasion disponibles",
    "ESSAI":       "Je veux faire un essai gratuit de véhicule neuf",
    "SAV":         "Je veux prendre un rendez-vous SAV atelier",
    "FACTURE":     "Je veux demander une facture",
    "MAINLEVEE":   "Je veux faire une demande de mainlevée",
    "RECLAMATION": "J'ai une réclamation à déposer",
}

# ============================================================
# WEBHOOK
# ============================================================
@app.route("/webhook", methods=["GET"])
def verify():
    if (request.args.get("hub.mode") == "subscribe" and
        request.args.get("hub.verify_token") == cfg("VERIFY_TOKEN", VERIFY_TOKEN)):
        return request.args.get("hub.challenge"), 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def receive():
    try:
        body  = request.get_json()
        value = body.get("entry",[{}])[0].get("changes",[{}])[0].get("value",{})
        msgs  = value.get("messages",[])
        if not msgs:
            return jsonify({"status":"ok"}), 200

        msg   = msgs[0]
        tel   = msg.get("from")
        nom   = value.get("contacts",[{}])[0].get("profile",{}).get("name","Client")
        mtype = msg.get("type")
        tok   = cfg("WHATSAPP_TOKEN")

        # ---- AUDIO ----
        if mtype == "audio":
            wa_text(tel, "Message vocal reçu, transcription en cours...")
            mid = msg.get("audio",{}).get("id")
            if not mid:
                wa_text(tel, "Impossible de traiter ce vocal. Merci d'écrire.")
                return jsonify({"status":"ok"}), 200
            h = {"Authorization":f"Bearer {tok}"}
            ru = requests.get(f"https://graph.facebook.com/v20.0/{mid}", headers=h, timeout=10)
            if ru.status_code != 200:
                wa_text(tel, "Erreur audio. Appelez le 0523303194.")
                return jsonify({"status":"ok"}), 200
            ra = requests.get(ru.json().get("url"), headers=h, timeout=20)
            transcrit = groq_whisper(ra.content)
            if not transcrit:
                wa_text(tel, "Transcription impossible. Merci d'écrire votre demande.")
                return jsonify({"status":"ok"}), 200
            wa_text(tel, f"J'ai bien entendu : \"{transcrit}\"")
            texte = transcrit

        # ---- IMAGE ----
        elif mtype == "image":
            wa_text(tel, "Photo reçue, analyse en cours...")
            mid  = msg.get("image",{}).get("id")
            mime = msg.get("image",{}).get("mime_type","image/jpeg")
            if not mid:
                wa_text(tel, "Impossible d'analyser cette image. Merci pour votre confiance.")
                return jsonify({"status":"ok"}), 200
            h  = {"Authorization":f"Bearer {tok}"}
            ru = requests.get(f"https://graph.facebook.com/v20.0/{mid}", headers=h, timeout=10)
            if ru.status_code != 200:
                wa_text(tel, "Erreur téléchargement.")
                return jsonify({"status":"ok"}), 200
            ri = requests.get(ru.json().get("url"), headers=h, timeout=20)
            if ri.status_code != 200:
                wa_text(tel, "Erreur téléchargement.")
                return jsonify({"status":"ok"}), 200
            analyse = groq_vision(base64.b64encode(ri.content).decode(), mime)
            wa_text(tel, analyse)
            wa_btns(tel, "Souhaitez-vous prendre rendez-vous en atelier ?",
                [{"id":"btn_rdv_sav","title":"Prendre RDV"},
                 {"id":"btn_autre_question","title":"Autre question"}])
            return jsonify({"status":"ok"}), 200

        # ---- TEXTE ----
        elif mtype == "text":
            texte = msg.get("text",{}).get("body","").strip()

        # ---- BOUTON INTERACTIF ----
        elif mtype == "interactive":
            br    = msg.get("interactive",{}).get("button_reply",{})
            bid   = br.get("id","")
            texte = br.get("title","")

            # Router par ID de bouton (priorité absolue)
            if bid == "btn_vehicules":
                wa_menu_veh(tel)
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_sav":
                texte = TEXTE_TO_GROQ["SAV"]
            elif bid == "btn_autre":
                wa_menu_autre(tel)
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_vn":
                texte = TEXTE_TO_GROQ["VN"]
            elif bid == "btn_vo":
                texte = TEXTE_TO_GROQ["VO"]
            elif bid == "btn_essai":
                texte = TEXTE_TO_GROQ["ESSAI"]
            elif bid == "btn_facture":
                texte = TEXTE_TO_GROQ["FACTURE"]
            elif bid == "btn_mainlevee":
                texte = TEXTE_TO_GROQ["MAINLEVEE"]
            elif bid == "btn_reclamation":
                texte = TEXTE_TO_GROQ["RECLAMATION"]
            elif bid in ("btn_rdv_sav","prendre rdv"):
                wa_text(tel, "Pour votre rendez-vous :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\nUn conseiller vous confirmera. Merci pour votre confiance.")
                return jsonify({"status":"ok"}), 200
            elif bid in ("btn_autre_question","autre question"):
                wa_text(tel, "Je suis à votre écoute. Comment puis-je vous aider ? Merci pour votre confiance.")
                return jsonify({"status":"ok"}), 200
        else:
            return jsonify({"status":"ok"}), 200

        if not texte:
            return jsonify({"status":"ok"}), 200

        print(f"\n[MSG] {tel} ({nom}): {texte}")
        sess = get_sess(tel)

        # Détecter langue
        tl = texte.lower().strip()
        if any('\u0600' <= c <= '\u06FF' for c in texte):
            sess["langue"] = "AR"
        elif any(w in tl for w in ["bghit","wach","safi","3afak","chokran","labas","mzyan","iyeh","wah","daba","3ndkm"]):
            sess["langue"] = "DARIJA"

        # ---- INTERCEPTER TEXTES DE BOUTONS (au cas où envoyés comme texte) ----
        action = BOUTON_ACTIONS.get(tl)
        if action and not sess["hist"]:
            # Seulement si pas d'historique (= premier contact ou menu)
            action = None  # laisser passer à la logique salutation

        if action:
            if action == "MENU_VEH":
                wa_menu_veh(tel)
                return jsonify({"status":"ok"}), 200
            elif action == "MENU_AUTRE":
                wa_menu_autre(tel)
                return jsonify({"status":"ok"}), 200
            elif action == "RDV_SAV":
                wa_text(tel, "Pour votre rendez-vous :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\nUn conseiller vous confirmera. Merci pour votre confiance.")
                return jsonify({"status":"ok"}), 200
            elif action == "AUTRE_Q":
                wa_text(tel, "Je suis à votre écoute. Merci pour votre confiance.")
                return jsonify({"status":"ok"}), 200
            elif action in TEXTE_TO_GROQ:
                texte = TEXTE_TO_GROQ[action]

        # ---- SALUTATION INITIALE ----
        saluts = ["bonjour","salam","salut","hi","hello","bonsoir","مرحبا","السلام",
                  "ahlan","bjr","bsr","coucou","sbah","msa","slm","labas","la bas",
                  "salam 3likom","wa3likom salam"]
        mots = tl.split()
        if not sess["hist"] and len(mots) <= 4 and any(s in tl for s in saluts):
            wa_bienvenue(tel)
            return jsonify({"status":"ok"}), 200

        # ---- CONFIRMATION APRES RECAP ----
        if sess["en_attente_confirm"] and sess["infos"]:
            oui = any(w in tl for w in ["oui","yes","wah","iyeh","safi","ok","correct","parfait","c bon","c'est bon","mzyan","confirme","d'accord"])
            non = any(w in tl for w in ["non","no","la","modifier","changer","corriger","pas correct","faux","erreur","bghit nbdel"])

            if oui:
                data = sess["infos"]
                t = data.get("type","vn")
                if t == "rdi" and data.get("chassis"):
                    info = verifier_rdi(data["chassis"])
                    if info is None:
                        rep = "Impossible d'accéder au système. Notre équipe vous contactera. Merci pour votre confiance."
                    elif info.get("trouve"):
                        rep = f"Vérification dossier :\nChâssis : {data['chassis']}\nStatut : {info['statut']}"
                        if info.get("date_dispo"):
                            rep += f"\nDate disponibilité : {info['date_dispo']}"
                        rep += "\n\nPour info : 0523303194. Merci pour votre confiance."
                    else:
                        rep = f"Dossier châssis {data['chassis']} non enregistré. Notre équipe vous contactera. Merci pour votre confiance."
                else:
                    rep = "Votre demande a bien été enregistrée. Notre équipe vous contactera très prochainement. Merci pour votre confiance."
                wa_text(tel, rep)
                notifier(tel, nom, data)
                enregistrer(tel, sess["langue"], data)
                sess["en_attente_confirm"] = False
                sess["infos"] = {}
                return jsonify({"status":"ok"}), 200

            elif non:
                wa_text(tel, "Quelle information souhaitez-vous modifier ? (ex: prénom, téléphone, modèle...) Merci pour votre confiance.")
                sess["en_attente_confirm"] = False
                return jsonify({"status":"ok"}), 200

        # ---- APPEL GROQ ----
        raw = groq_chat(sess["hist"], texte)
        tc, tag = parse_tag(raw)

        # Fallback si texte vide mais tag RECAP/LEAD présent
        if (not tc or len(tc) < 3) and tag.startswith(("RECAP:","LEAD:")):
            d = extraire(tag)
            if d.get("prenom") and d.get("tel"):
                tc = recap_msg(d)
                tag = tag.replace("LEAD:","RECAP:")
            else:
                tc = "Désolée, une erreur est survenue. Contactez-nous au 0523303194. Merci pour votre confiance."
                tag = "RIEN"

        if not tc or len(tc) < 3:
            tc = "Désolée, une erreur est survenue. Contactez-nous au 0523303194. Merci pour votre confiance."

        # Traiter RECAP → attendre confirmation
        if tag.startswith("RECAP:"):
            d = extraire(tag)
            if d.get("prenom") and d.get("tel"):
                sess["infos"] = d
                sess["en_attente_confirm"] = True
                tc = recap_msg(d)
            else:
                tag = "RIEN"

        # Traiter LEAD direct → forcer confirmation
        elif tag.startswith("LEAD:"):
            d = extraire(tag)
            if d.get("prenom") and d.get("tel"):
                sess["infos"] = d
                sess["en_attente_confirm"] = True
                tc = recap_msg(d)

        print(f"[BOT] {tc[:80]}...")
        print(f"[TAG] {tag}")

        sess["hist"].append({"role":"user","content":texte})
        sess["hist"].append({"role":"assistant","content":tc})
        if len(sess["hist"]) > 16:
            sess["hist"] = sess["hist"][-16:]

        wa_text(tel, tc)

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
