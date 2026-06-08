# -*- coding: utf-8 -*-
"""
TopAuto Mohammedia — WhatsApp Bot
Architecture : Flask + Machines à états + Groq LLM + Google Sheets
"""
import os, re, json, base64, requests, time
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# ============================================================
# CONFIG
# ============================================================
def cfg(k, fb=""):
    return os.environ.get(k, fb)

PHONE_NUMBER_ID = "1031404513398168"
VERIFY_TOKEN    = "topauto2024secret"
CONSEILLER_TEL  = "212774057668"

# IDs Google Sheets hardcodés
def sh_v(): return "1Z4ar_AxrsV2k7uytSi-K9i2OtrCWyFtiRv0U2S-nSY0"
def sh_f(): return "12Zwfi5H3vxKJDN---5qeZspuqwd-VjQthfe4uZrUTGg"
def sh_s(): return "12GxqngDty_PniBNkMycGGqHD6MWrXEAYjPsRKkvLI8A"

SHEET_MAP = {
    "essai":               lambda: (sh_v(), "Essais_VN"),
    "vn":                  lambda: (sh_v(), "VN_Leads"),
    "vo":                  lambda: (sh_v(), "VO_Leads"),
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
    fn = SHEET_MAP.get(t.lower())
    if fn:
        sid, sn = fn()
        print(f"[FLOW] sheet={sn} id={'OK' if sid else 'VIDE'}")
        return sid, sn
    return sh_v(), "VN_Leads"

# ============================================================
# GOOGLE SHEETS
# ============================================================
def gsheets():
    try:
        cj = cfg("GOOGLE_CREDS_JSON")
        if not cj:
            print("[SHEETS] GOOGLE_CREDS_JSON absent")
            return None
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
        if not svc:
            return False
        t = data.get("type", "vn").lower()
        sid, sn = get_sheet(t)
        if not sid:
            print(f"[SHEETS] sheet ID vide type={t}")
            return False
        now = datetime.now()
        res = svc.spreadsheets().values().get(
            spreadsheetId=sid, range=f"{sn}!A:P").execute()
        rows = res.get("values", [])
        idx = next((i+1 for i, r in enumerate(rows) if len(r) > 11 and r[11] == tel), None)

        if t == "essai":
            row = [
                now.strftime("%Y%m%d%H%M%S"), now.strftime("%d/%m/%Y %H:%M"),
                data.get("prenom",""), data.get("nom",""), data.get("tel",""),
                data.get("modele",""), "", data.get("ville",""),
                data.get("date_essai",""), "NOUVEAU", "", tel, langue
            ]
        else:
            row = [
                now.strftime("%Y%m%d%H%M%S"), now.strftime("%d/%m/%Y %H:%M"),
                data.get("prenom",""), data.get("nom",""), data.get("tel",""),
                data.get("modele", data.get("vehicule","")),
                data.get("chassis",""),
                data.get("cin", data.get("rc","")),
                data.get("ville",""),
                data.get("type_facture",""),
                data.get("description", data.get("reclamation","")),
                tel, langue, t, "WhatsApp Bot", "NOUVEAU"
            ]

        if idx:
            svc.spreadsheets().values().update(
                spreadsheetId=sid, range=f"{sn}!A{idx}:P{idx}",
                valueInputOption="USER_ENTERED", body={"values": [row]}).execute()
            print(f"[SHEETS] MAJ {sn} ligne {idx}")
        else:
            svc.spreadsheets().values().append(
                spreadsheetId=sid, range=f"{sn}!A:P",
                valueInputOption="USER_ENTERED", body={"values": [row]}).execute()
            print(f"[SHEETS] INSERT {sn}")
        return True
    except Exception as e:
        print(f"[SHEETS] ERR insert: {e}")
        return False

def verifier_rdi(chassis):
    try:
        svc = gsheets()
        sid = sh_s()
        if not svc or not sid:
            return None
        res = svc.spreadsheets().values().get(
            spreadsheetId=sid, range="RDI_Immatriculation!A:P").execute()
        cl = chassis.lower().strip()
        for r in res.get("values", [])[1:]:
            if len(r) > 6 and r[6].lower().strip() == cl:
                statut = r[10] if len(r) > 10 else "En cours"
                date_dispo = ""
                for ci in [11, 12, 13]:
                    if len(r) > ci:
                        v = r[ci].strip()
                        if v and ("/" in v or "-" in v) and len(v) < 15:
                            date_dispo = v
                            break
                return {"trouve": True, "statut": statut, "date_dispo": date_dispo}
        return {"trouve": False}
    except Exception as e:
        print(f"[RDI] ERR: {e}")
        return None

# ============================================================
# SESSIONS — machines à états
# ============================================================
sessions = {}
SESSION_TIMEOUT = 1800  # 30 min
processed_ids = set()
def get_sess(tel):
    now = time.time()
    if tel in sessions and now - sessions[tel].get("last", 0) > SESSION_TIMEOUT:
        del sessions[tel]
    if tel not in sessions:
        sessions[tel] = {
            "hist": [], "langue": "FR",
            "flow": None, "step": 0, "infos": {},
            "last": now
        }
    sessions[tel]["last"] = now
    return sessions[tel]

def reset_flow(sess):
    sess["flow"] = None
    sess["step"] = 0
    sess["infos"] = {}

# ============================================================
# VALIDATION
# ============================================================
def valider_tel(tel):
    t = tel.replace(" ", "").replace("-", "").replace(".", "")
    return bool(re.match(r'^(212[567]\d{8}|0[567]\d{8})$', t))

def valider_chassis(ch):
    return len(ch.replace(" ", "")) >= 11

def valider_cin(cin):
    return bool(re.match(r'^[A-Za-z]{1,2}[0-9]{4,8}$', cin.strip()))

def nettoyer(val):
    """Nettoie une valeur — retire 'Merci pour votre confiance' etc."""
    val = val.strip()
    val = re.sub(r'[Mm]erci pour votre confiance\.?', '', val).strip()
    val = re.sub(r'[Cc]hokran.*', '', val).strip()
    val = val.strip('. \n')
    return val

# ============================================================
# GOOGLE SHEETS KNOWLEDGE BASE
# ============================================================
CATALOGUE = """
═══════════════════════════════════════
    GAMME DACIA — VÉHICULES NEUFS
═══════════════════════════════════════

🔋 DACIA SPRING — Citadine électrique
   • Batterie LFP 24,3 kWh | Recharge AC 7kW | DC 40kW
   • 70 ch ou 100 ch
   • V2L (Vehicle-to-Load)
   • Coffre : 308L
   • Finitions : Essential / Extreme

🚗 DACIA SANDERO STREETWAY 2026 — Citadine
   • Restylée 2026 — Écran 10 pouces dès Expression
   • Moteurs : 1.0 SCe 65ch | 1.0 TCe 100ch | 1.5 dCi 102ch
   • Finitions : Essential → Journey

🚙 DACIA SANDERO STEPWAY — Crossover urbain
   • Garde au sol : 17 cm | Protections Starkle
   • Moteurs : TCe 100ch | dCi 102ch | CVT Extreme
   • Finitions : Essential → Extreme

🚗 DACIA LOGAN — Berline familiale
   • Coffre : 528L | Restylée 2026
   • Moteurs : SCe 65ch | TCe 100ch | dCi 102ch
   • Finitions : Essential → Journey

🚐 DACIA JOGGER — Break 5/7 places
   • Coffre : 1 807L (banquettes rabattues)
   • Moteurs : TCe 100ch | dCi 102ch | HEV 140ch auto
   • Finitions : Essential → Extreme

🏔️ DACIA DUSTER 2025 — SUV 3e génération
   • Écran Media Nav 8" | Caméra recul | CarPlay
   • Moteurs : dCi 115ch | TCe 130ch
   • Finitions : Essential → Extreme

🦁 DACIA BIGSTER 2025 — Grand SUV NOUVEAU
   • +23 cm vs Duster | Toit panoramique | Coffre électrique
   • Moteurs : dCi 115ch | HEV 155ch auto
   • Finitions : Essential → Journey

═══════════════════════════════════════
    GAMME RENAULT VP — VÉHICULES NEUFS
═══════════════════════════════════════

🚗 RENAULT CLIO 5 Phase 2 — Citadine
   • TCe 100ch | Blue dCi 115ch | E-Tech 145ch auto
   • Finitions : Equilibre → Esprit Alpine

🚗 RENAULT CLIO 6 — Nouvelle génération
   • Design repensé | Connectivité avancée
   • TCe 100ch | E-Tech 145ch auto
   • Finitions : Equilibre → Esprit Alpine

🏙️ RENAULT CAPTUR — SUV urbain
   • OpenR Link | Google intégré | Écran 10"
   • TCe 100ch CVT | E-Tech 145ch auto
   • Finitions : Equilibre → Esprit Alpine

⚡ RENAULT 5 E-TECH — 100% Électrique iconique
   • 40 kWh 120ch ou 52 kWh 150ch
   • Autonomie : jusqu'à 400 km WLTP
   • Recharge DC 100 kW
   • Finitions : Evolution → Esprit Alpine

🚗 RENAULT EXPRESS — Berline économique
   • Diesel 95ch (Confort) ou 115ch (Techno)
   • Robuste et économique

🚘 RENAULT MÉGANE SEDAN — Berline familiale
   • Coffre : 475L | Blue dCi 115ch
   • Finitions : Equilibre → Esprit Alpine

⚡ RENAULT MÉGANE E-TECH — Compacte électrique
   • 60 kWh | 450 km WLTP | 130 kW DC | 220ch
   • Google intégré | Écran 12"
   • Finitions : Equilibre → Iconic

🏎️ RENAULT ARKANA — Coupé-SUV hybride
   • E-Tech 145ch | 4,5L/100km
   • Finitions : Techno / Esprit Alpine

🚙 RENAULT AUSTRAL — SUV familial
   • E-Tech 200ch | OpenR Link | Google natif
   • Full digital | 4,5L/100km | Disponible 2025
   • Finitions : Techno / Esprit Alpine

🌟 RENAULT KARDIAN — SUV compact SOMACA
   • Fabriqué au Maroc | Caméra 360°
   • TCe 100ch CVT | Blue dCi 102ch
   • Finitions : Equilibre / Techno

═══════════════════════════════════════
    GAMME RENAULT VU — UTILITAIRES
═══════════════════════════════════════

📦 EXPRESS VAN — Léger
   • 800 kg | 3,3 m³ | dCi 75ch

🚐 TRAFIC — Polyvalent
   • 1 400 kg | L1/L2, H1/H2 | dCi 150ch
   • Combi 9 places disponible

🚛 MASTER — Grand fourgon
   • 1 700 kg | 8 à 17 m³ | dCi 145/180ch
"""

ETABLISSEMENT = """
TopAuto Mohammedia — Concessionnaire agréé Renault & Dacia
📍 Q.I Bd Sidi Mohamed Ben Abdellah, 208000 Mohammedia
📞 0523303194 (Renault) | 0523303195 (Dacia)
✉️ contact@top-auto.ma
🗺️ GPS : 33.683384 N, 7.409769 W
🔗 Maps : https://maps.google.com/?q=33.683384,-7.409769

Horaires :
• Lun-Ven : 8h00 – 18h30
• Samedi  : 8h30 – 15h00
• Dimanche : Fermé
"""

# ============================================================
# DÉTECTION RAPIDE — sans appel Groq
# ============================================================
PRIX_KEYWORDS = ["prix", "tarif", "combien", "coûte", "cout", "coute",
                 "remise", "promotion", "mensualité", "mensualite", "budget",
                 "cher", "moins cher", "thaman", "b7al", "bchhal"]

FAQ_KEYWORDS = {
    "horaire": ["horaire", "heure", "ouvert", "fermé", "ferme", "ouverture"],
    "adresse": ["adresse", "localisation", "où êtes", "ou etes", "situé", "situe", "comment venir", "plan", "gps", "maps", "itinéraire"],
    "telephone": ["téléphone", "telephone", "numéro", "numero", "appeler", "joindre", "contact"],
    "electrique": ["électrique", "electrique", "ev", "zev", "batterie", "recharge", "autonomie", "spring", "mégane e-tech", "r5"],
    "suv": ["suv", "tout-terrain", "4x4", "duster", "bigster", "captur", "kardian", "arkana", "austral"],
    "occasion": ["occasion", "voiture d'occasion", "vo", "used", "d'occasion"],
    "suivi": ["suivi", "avancement", "travaux", "commande", "pièces", "pieces", "réparation", "reparation"],
}

def detecter_intent_direct(texte):
    tl = texte.lower()
    for kw in PRIX_KEYWORDS:
        if kw in tl:
            return "PRIX"
    if any(w in tl for w in FAQ_KEYWORDS["horaire"]):
        return "FAQ_HORAIRE"
    if any(w in tl for w in FAQ_KEYWORDS["adresse"]):
        return "FAQ_ADRESSE"
    if any(w in tl for w in FAQ_KEYWORDS["telephone"]):
        return "FAQ_TEL"
    if any(w in tl for w in FAQ_KEYWORDS["suivi"]):
        return "FAQ_SUIVI"
    return None

# ============================================================
# GROQ LLM — uniquement pour réponses générales
# ============================================================
SYSTEM_PROMPT_GENERAL = """Tu es l'Assistant Virtuel de TopAuto Mohammedia, concessionnaire agréé Renault et Dacia.

REGLES ABSOLUES :
1. JAMAIS de prix, tarifs, mensualités — dire "notre conseiller vous communiquera le meilleur tarif"
2. Répondre DIRECTEMENT, pas d'introduction inutile
3. Aucun emoji
4. Terminer par : Merci pour votre confiance.
5. Répondre dans la langue du client (FR / AR / Darija)
6. Pour les questions sur les véhicules : donner des infos techniques DETAILLEES (moteurs, finitions, équipements)
7. Pour les SUV : mentionner Duster, Bigster, Captur, Kardian, Arkana, Austral
8. Pour les électriques : Spring, R5 E-Tech, Mégane E-Tech

CATALOGUE VEHICULES :""" + CATALOGUE + """

ETABLISSEMENT :""" + ETABLISSEMENT

def groq_general(hist, texte):
    key = cfg("GROQ_API_KEY")
    msgs = [{"role": "system", "content": SYSTEM_PROMPT_GENERAL}] + hist[-8:] + [{"role": "user", "content": texte}]
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "llama-3.3-70b-versatile", "messages": msgs, "max_tokens": 500, "temperature": 0.2},
        timeout=30)
    print(f"[GROQ] {r.status_code}")
    if r.status_code != 200:
        raise Exception(f"Groq {r.status_code}: {r.text[:100]}")
    return r.json()["choices"][0]["message"]["content"]

def groq_vision(b64, mime):
    key = cfg("GROQ_API_KEY")
    prompt = "Tu es expert automobile TopAuto. Analyse image: 1-Problème visible 2-Classification(carrosserie/mécanique/électronique/pneu) 3-Gravité(faible/modéré/urgent) 4-Recommandation. Français concis. Termine: Merci pour votre confiance."
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "meta-llama/llama-4-scout-17b-16e-instruct",
              "messages": [{"role": "user", "content": [
                  {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                  {"type": "text", "text": prompt}]}],
              "max_tokens": 400}, timeout=30)
    if r.status_code != 200:
        return "Impossible d'analyser. Présentez-vous en atelier. Merci pour votre confiance."
    return r.json()["choices"][0]["message"]["content"]

def groq_whisper(audio_bytes):
    key = cfg("GROQ_API_KEY")
    r = requests.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {key}"},
        files={"file": ("a.ogg", audio_bytes, "audio/ogg")},
        data={"model": "whisper-large-v3", "language": "fr", "response_format": "text"},
        timeout=30)
    if r.status_code != 200 or not r.text.strip():
        return None
    return r.text.strip()

# ============================================================
# WHATSAPP
# ============================================================
def wa_token():  return cfg("WHATSAPP_TOKEN")
def wa_pid():    return cfg("PHONE_NUMBER_ID", PHONE_NUMBER_ID)
def wa_cons():   return cfg("CONSEILLER_WHATSAPP", CONSEILLER_TEL)

def wa_text(tel, msg):
    r = requests.post(
        f"https://graph.facebook.com/v20.0/{wa_pid()}/messages",
        headers={"Authorization": f"Bearer {wa_token()}", "Content-Type": "application/json"},
        json={"messaging_product": "whatsapp", "to": tel, "type": "text", "text": {"body": msg}},
        timeout=10)
    print(f"[WA] text {r.status_code}")
    return r.status_code == 200

def wa_btns(tel, body, btns):
    r = requests.post(
        f"https://graph.facebook.com/v20.0/{wa_pid()}/messages",
        headers={"Authorization": f"Bearer {wa_token()}", "Content-Type": "application/json"},
        json={"messaging_product": "whatsapp", "to": tel, "type": "interactive",
              "interactive": {"type": "button", "body": {"text": body},
                "action": {"buttons": [{"type": "reply", "reply": {"id": b["id"], "title": b["title"]}} for b in btns[:3]]}}},
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
        "Comment puis-je vous aider aujourd'hui ?",
        [{"id": "btn_vehicules", "title": "Véhicules"},
         {"id": "btn_sav", "title": "SAV & Atelier"},
         {"id": "btn_autre", "title": "Autre demande"}])

def wa_menu_veh(tel):
    wa_btns(tel, "Quelle gamme vous intéresse ?",
        [{"id": "btn_vn", "title": "Véhicules Neufs"},
         {"id": "btn_vo", "title": "Véhicules Occasion"},
         {"id": "btn_essai", "title": "Essai Gratuit"}])

def wa_menu_autre(tel):
    wa_btns(tel, "Quelle est votre demande ?",
        [{"id": "btn_facture", "title": "Demande Facture"},
         {"id": "btn_mainlevee", "title": "Mainlevée"},
         {"id": "btn_reclamation", "title": "Réclamation"}])

def notifier_conseiller(tel, nom_wa, data):
    t = data.get("type", "vn")
    _, sn = get_sheet(t)
    lignes = [f"--- NOUVEAU LEAD : {sn} ---", f"WA client : {tel}", f"Nom WhatsApp : {nom_wa}"]
    for k, l in [("prenom","Prénom"),("nom","Nom"),("tel","Tel"),("modele","Modèle"),
                 ("ville","Ville"),("chassis","Châssis"),("cin","CIN"),("rc","RC"),
                 ("type_facture","Type facture"),("reclamation","Réclamation"),
                 ("description","Description"),("date_essai","Date essai souhaitée")]:
        if data.get(k):
            lignes.append(f"{l} : {data[k]}")
    lignes.append(f"Statut : {'URGENT 48h' if t == 'reclamation' else 'À RAPPELER'}")
    wa_text(wa_cons(), "\n".join(lignes))

def recap_texte(data, flow):
    """Génère le récapitulatif propre selon le flux"""
    t = "Récapitulatif de votre demande :\n"
    mapping = [
        ("prenom","Prénom"), ("nom","Nom"), ("tel","Téléphone"),
        ("modele","Modèle souhaité"), ("ville","Ville"), ("date_essai","Date souhaitée"),
        ("chassis","Numéro de châssis"), ("cin","CIN"), ("rc","RC (société)"),
        ("type_facture","Type de facture"), ("reclamation","Réclamation"),
        ("description","Description"),
    ]
    for k, l in mapping:
        v = data.get(k, "")
        if v and v not in ["X", "", "null", "?"]:
            t += f"- {l} : {v}\n"
    t += "\nCes informations sont-elles correctes ? (Répondez Oui ou Non)"
    return t

# ============================================================
# MACHINES À ÉTATS — logique métier pure, sans LLM
# ============================================================

def traiter_flow(sess, tel, nom, texte):
    """
    Gère les flux structurés step-by-step.
    Retourne (reponse_str, flow_terminé_bool)
    """
    flow = sess["flow"]
    step = sess["step"]
    infos = sess["infos"]
    tl = texte.strip()

    print(f"[FLOW] {flow} | STEP {step} | texte={tl[:40]}")

    # ----------------------------------------------------------------
    # FLUX ESSAI VN
    # ----------------------------------------------------------------
    if flow == "essai":
        if step == 1:
            infos["prenom"] = nettoyer(tl)
            sess["step"] = 2
            return "Votre nom, s'il vous plaît ?", False

        elif step == 2:
            infos["nom"] = nettoyer(tl)
            sess["step"] = 3
            return "Votre numéro de téléphone ?", False

        elif step == 3:
            if not valider_tel(tl):
                return "Numéro invalide. Merci de saisir un numéro marocain valide (ex: 0612345678 ou 212612345678).", False
            infos["tel"] = nettoyer(tl)
            sess["step"] = 4
            return "Quel modèle souhaitez-vous essayer ? (ex: Dacia Duster, Renault Clio...)", False

        elif step == 4:
            infos["modele"] = nettoyer(tl)
            sess["step"] = 5
            return "Dans quelle ville souhaitez-vous effectuer l'essai ?", False

        elif step == 5:
            infos["ville"] = nettoyer(tl)
            sess["step"] = 6
            return "Avez-vous une date souhaitée pour l'essai ? (ex: 15/06/2026 ou 'dès que possible')", False

        elif step == 6:
            infos["date_essai"] = nettoyer(tl) if tl.lower() not in ["non","no","la","pas"] else "Dès que possible"
            sess["step"] = 7
            # Afficher récap
            return recap_texte(infos, flow), False

        elif step == 7:
            # Attente confirmation
            if any(w in tl.lower() for w in ["oui","yes","wah","iyeh","safi","ok","correct","parfait","confirme","d'accord","mzyan"]):
                ok = enregistrer(tel, sess["langue"], {**infos, "type": "essai"})
                notifier_conseiller(tel, nom, {**infos, "type": "essai"})
                reset_flow(sess)
                msg = "Votre demande d'essai a bien été enregistrée. Notre service commercial vous contactera très prochainement pour confirmer la date."
                if not ok:
                    msg += "\n\nNote : un incident technique est survenu lors de l'enregistrement. Un conseiller vous contactera directement."
                return msg + "\n\nMerci pour votre confiance.", True
            elif any(w in tl.lower() for w in ["non","no","la","modifier","changer","corriger","faux"]):
                sess["step"] = 8
                return "Quelle information souhaitez-vous modifier ? (prénom / nom / téléphone / modèle / ville / date)", False
            else:
                return "Veuillez répondre par Oui ou Non.\n\n" + recap_texte(infos, flow), False

        elif step == 8:
            tl_lower = tl.lower()
            if "prénom" in tl_lower or "prenom" in tl_lower:
                infos.pop("prenom", None)
                sess["step"] = 1
                return "Votre prénom ?", False
            elif "nom" in tl_lower:
                infos.pop("nom", None)
                sess["step"] = 2
                return "Votre nom ?", False
            elif "téléphone" in tl_lower or "telephone" in tl_lower or "tel" in tl_lower:
                infos.pop("tel", None)
                sess["step"] = 3
                return "Votre numéro de téléphone ?", False
            elif "modèle" in tl_lower or "modele" in tl_lower or "vehicule" in tl_lower:
                infos.pop("modele", None)
                sess["step"] = 4
                return "Quel modèle souhaitez-vous essayer ?", False
            elif "ville" in tl_lower:
                infos.pop("ville", None)
                sess["step"] = 5
                return "Dans quelle ville ?", False
            elif "date" in tl_lower:
                infos.pop("date_essai", None)
                sess["step"] = 6
                return "Quelle date souhaitée pour l'essai ?", False
            else:
                return "Veuillez préciser l'information à modifier : prénom, nom, téléphone, modèle, ville ou date.", False

    # ----------------------------------------------------------------
    # FLUX RDI
    # ----------------------------------------------------------------
    elif flow == "rdi":
        if step == 1:
            # 30 jours ?
            oui = any(w in tl.lower() for w in ["oui","yes","wah","iyeh","safi","ok","ouai","si"])
            non = any(w in tl.lower() for w in ["non","no","la","pas encore","pas"])
            if oui:
                sess["step"] = 2
                return "Êtes-vous un particulier ou une société ?", False
            elif non:
                reset_flow(sess)
                return "Le délai réglementaire de 30 jours n'est pas encore écoulé depuis la date de livraison. Vous pourrez faire votre demande de RDI passé ce délai. Merci pour votre confiance.", True
            else:
                return "Votre véhicule a-t-il été livré il y a plus de 30 jours ? (Oui / Non)", False

        elif step == 2:
            if any(w in tl.lower() for w in ["particulier","prive","privé","individuel","personne"]):
                infos["type_client"] = "particulier"
                sess["step"] = 3
            elif any(w in tl.lower() for w in ["société","societe","entreprise","sté","ste","rc","commerce"]):
                infos["type_client"] = "societe"
                sess["step"] = 3
            else:
                return "Êtes-vous un particulier ou une société ?", False
            return "Votre prénom, s'il vous plaît ?", False

        elif step == 3:
            infos["prenom"] = nettoyer(tl)
            sess["step"] = 4
            return "Votre numéro de châssis (VIN) ?", False

        elif step == 4:
            ch = tl.replace(" ","")
            if not valider_chassis(ch):
                return "Le numéro de châssis semble incomplet. Merci de le vérifier (minimum 11 caractères).", False
            infos["chassis"] = ch.upper()
            sess["step"] = 5
            if infos.get("type_client") == "societe":
                return "Votre numéro de Registre de Commerce (RC) ?", False
            else:
                return "Votre numéro de CIN ?", False

        elif step == 5:
            if infos.get("type_client") == "societe":
                infos["rc"] = nettoyer(tl).upper()
            else:
                cin = nettoyer(tl).upper()
                if not valider_cin(cin):
                    return "Format CIN invalide (ex: BE123456). Merci de le vérifier.", False
                infos["cin"] = cin
            sess["step"] = 6
            return "Votre numéro de téléphone ?", False

        elif step == 6:
            if not valider_tel(tl):
                return "Numéro invalide. Format attendu : 0612345678 ou 212612345678.", False
            infos["tel"] = nettoyer(tl)
            sess["step"] = 7
            return recap_texte(infos, flow), False

        elif step == 7:
            if any(w in tl.lower() for w in ["oui","yes","wah","iyeh","safi","ok","correct","parfait","confirme","d'accord","mzyan"]):
                # Vérification dans Google Sheets
                info_rdi = verifier_rdi(infos.get("chassis",""))
                if info_rdi is None:
                    rep = "Impossible d'accéder au système pour le moment. Notre équipe vous contactera très prochainement avec l'état de votre dossier."
                    notifier_conseiller(tel, nom, {**infos, "type": "rdi"})
                elif info_rdi.get("trouve"):
                    statut = info_rdi.get("statut","En cours")
                    date_d = info_rdi.get("date_dispo","")
                    rep = f"Vérification de votre dossier :\n- Châssis : {infos['chassis']}\n- Statut : {statut}"
                    if date_d:
                        rep += f"\n- Date de disponibilité : {date_d}"
                    rep += "\n\nPour toute question, contactez-nous au 0523303194."
                else:
                    rep = f"Le dossier pour le châssis {infos['chassis']} n'est pas encore enregistré dans notre système. Notre équipe va vérifier et vous contactera très prochainement."
                    notifier_conseiller(tel, nom, {**infos, "type": "rdi"})
                reset_flow(sess)
                return rep + "\n\nMerci pour votre confiance.", True
            elif any(w in tl.lower() for w in ["non","no","la","modifier","changer"]):
                sess["step"] = 8
                return "Quelle information souhaitez-vous modifier ? (prénom / châssis / CIN / RC / téléphone)", False
            else:
                return "Veuillez répondre par Oui ou Non.\n\n" + recap_texte(infos, flow), False

        elif step == 8:
            tl_lower = tl.lower()
            if "prénom" in tl_lower or "prenom" in tl_lower:
                sess["step"] = 3
                return "Votre prénom ?", False
            elif "châssis" in tl_lower or "chassis" in tl_lower or "vin" in tl_lower:
                infos.pop("chassis", None)
                sess["step"] = 4
                return "Votre numéro de châssis ?", False
            elif "cin" in tl_lower:
                infos.pop("cin", None)
                sess["step"] = 5
                return "Votre numéro de CIN ?", False
            elif "rc" in tl_lower or "registre" in tl_lower:
                infos.pop("rc", None)
                sess["step"] = 5
                return "Votre numéro RC ?", False
            elif "téléphone" in tl_lower or "tel" in tl_lower:
                infos.pop("tel", None)
                sess["step"] = 6
                return "Votre numéro de téléphone ?", False
            else:
                return "Précisez : prénom, châssis, CIN, RC ou téléphone.", False

    # ----------------------------------------------------------------
    # FLUX FACTURE
    # ----------------------------------------------------------------
    elif flow == "facture":
        if step == 1:
            # Identifier le type
            tl_lower = tl.lower()
            if any(w in tl_lower for w in ["vente","achat","neuf","occasion","vn","vo"]):
                infos["type_facture"] = "Vente VN/VO"
                infos["type"] = "facture_vente"
            elif any(w in tl_lower for w in ["mécanique","mecanique","atelier","entretien","réparation","reparation"]):
                infos["type_facture"] = "Mécanique"
                infos["type"] = "facture_mecanique"
            elif any(w in tl_lower for w in ["carrosserie","peinture","bosselure","rayure"]):
                infos["type_facture"] = "Carrosserie"
                infos["type"] = "facture_carrosserie"
            elif any(w in tl_lower for w in ["pièce","piece","rechange","accessoire"]):
                infos["type_facture"] = "Pièces de rechange"
                infos["type"] = "facture_pieces"
            else:
                return ("Quel type de facture souhaitez-vous ?\n\n"
                        "1. Achat véhicule (VN/VO)\n"
                        "2. Atelier mécanique\n"
                        "3. Carrosserie\n"
                        "4. Pièces de rechange"), False
            sess["step"] = 2
            return "Votre numéro de châssis ou matricule du véhicule ?", False

        elif step == 2:
            infos["chassis"] = nettoyer(tl).upper()
            sess["step"] = 3
            return "Nom du titulaire de la facture ?", False

        elif step == 3:
            infos["nom"] = nettoyer(tl)
            sess["step"] = 4
            return "Votre numéro de téléphone ?", False

        elif step == 4:
            if not valider_tel(tl):
                return "Numéro invalide. Format : 0612345678 ou 212612345678.", False
            infos["tel"] = nettoyer(tl)
            sess["step"] = 5
            return recap_texte(infos, flow), False

        elif step == 5:
            if any(w in tl.lower() for w in ["oui","yes","wah","iyeh","safi","ok","correct","parfait","confirme","d'accord","mzyan"]):
                t = infos.get("type","facture_vente")
                ok = enregistrer(tel, sess["langue"], infos)
                notifier_conseiller(tel, nom, infos)
                reset_flow(sess)
                msg = f"Votre demande de facture ({infos.get('type_facture','')}) a bien été enregistrée. Notre équipe vous contactera rapidement."
                if not ok:
                    msg += "\n\nNote : incident technique lors de l'enregistrement. Un conseiller vous contactera."
                return msg + "\n\nMerci pour votre confiance.", True
            elif any(w in tl.lower() for w in ["non","no","la","modifier","changer"]):
                sess["step"] = 6
                return "Quelle information souhaitez-vous modifier ? (type facture / châssis / nom / téléphone)", False
            else:
                return "Répondez Oui ou Non.\n\n" + recap_texte(infos, flow), False

        elif step == 6:
            tl_lower = tl.lower()
            if "type" in tl_lower or "facture" in tl_lower:
                infos.pop("type_facture", None)
                infos.pop("type", None)
                sess["step"] = 1
                return ("Quel type de facture ?\n\n"
                        "1. Achat véhicule (VN/VO)\n"
                        "2. Atelier mécanique\n"
                        "3. Carrosserie\n"
                        "4. Pièces de rechange"), False
            elif "châssis" in tl_lower or "chassis" in tl_lower or "matricule" in tl_lower:
                sess["step"] = 2
                return "Numéro de châssis ou matricule ?", False
            elif "nom" in tl_lower:
                sess["step"] = 3
                return "Nom du titulaire ?", False
            elif "téléphone" in tl_lower or "tel" in tl_lower:
                sess["step"] = 4
                return "Numéro de téléphone ?", False
            else:
                return "Précisez : type facture, châssis, nom ou téléphone.", False

    # ----------------------------------------------------------------
    # FLUX RÉCLAMATION
    # ----------------------------------------------------------------
    elif flow == "reclamation":
        if step == 1:
            infos["prenom"] = nettoyer(tl)
            sess["step"] = 2
            return "Votre nom ?", False

        elif step == 2:
            infos["nom"] = nettoyer(tl)
            sess["step"] = 3
            return "Votre numéro de téléphone ?", False

        elif step == 3:
            if not valider_tel(tl):
                return "Numéro invalide. Format : 0612345678.", False
            infos["tel"] = nettoyer(tl)
            sess["step"] = 4
            return "Numéro de châssis ou plaque d'immatriculation (si applicable, sinon tapez 'non') ?", False

        elif step == 4:
            if tl.lower() not in ["non","no","la","pas","n/a"]:
                infos["chassis"] = nettoyer(tl).upper()
            sess["step"] = 5
            return "Décrivez votre réclamation en détail :", False

        elif step == 5:
            infos["reclamation"] = nettoyer(tl)
            infos["type"] = "reclamation"
            sess["step"] = 6
            return recap_texte(infos, flow), False

        elif step == 6:
            if any(w in tl.lower() for w in ["oui","yes","wah","iyeh","safi","ok","correct","confirme","d'accord","mzyan"]):
                ok = enregistrer(tel, sess["langue"], infos)
                notifier_conseiller(tel, nom, infos)
                reset_flow(sess)
                msg = "Votre réclamation a bien été enregistrée et transmise immédiatement à notre responsable qualité. Vous recevrez une réponse dans un délai de 48 heures ouvrées."
                if not ok:
                    msg += "\n\nNote : incident technique. Un conseiller vous contactera."
                return msg + "\n\nMerci pour votre confiance.", True
            elif any(w in tl.lower() for w in ["non","no","la","modifier","changer"]):
                sess["step"] = 7
                return "Quelle information à modifier ? (prénom / nom / téléphone / châssis / description)", False
            else:
                return "Répondez Oui ou Non.\n\n" + recap_texte(infos, flow), False

        elif step == 7:
            tl_lower = tl.lower()
            if "prénom" in tl_lower or "prenom" in tl_lower:
                sess["step"] = 1
                return "Votre prénom ?", False
            elif "nom" in tl_lower:
                sess["step"] = 2
                return "Votre nom ?", False
            elif "téléphone" in tl_lower or "tel" in tl_lower:
                sess["step"] = 3
                return "Votre téléphone ?", False
            elif "châssis" in tl_lower or "chassis" in tl_lower:
                sess["step"] = 4
                return "Numéro de châssis ?", False
            elif "description" in tl_lower or "réclamation" in tl_lower or "reclamation" in tl_lower:
                sess["step"] = 5
                return "Décrivez votre réclamation :", False
            else:
                return "Précisez : prénom, nom, téléphone, châssis ou description.", False

    # ----------------------------------------------------------------
    # FLUX SAV ATELIER
    # ----------------------------------------------------------------
    elif flow == "sav":
        if step == 1:
            infos["prenom"] = nettoyer(tl)
            sess["step"] = 2
            return "Votre nom ?", False
        elif step == 2:
            infos["nom"] = nettoyer(tl)
            sess["step"] = 3
            return "Votre numéro de téléphone ?", False
        elif step == 3:
            if not valider_tel(tl):
                return "Numéro invalide. Format : 0612345678.", False
            infos["tel"] = nettoyer(tl)
            infos["type"] = "sav_atelier"
            sess["step"] = 4
            return recap_texte(infos, flow), False
        elif step == 4:
            if any(w in tl.lower() for w in ["oui","yes","wah","iyeh","safi","ok","correct","confirme","d'accord","mzyan"]):
                ok = enregistrer(tel, sess["langue"], infos)
                notifier_conseiller(tel, nom, infos)
                reset_flow(sess)
                msg = ("Pour planifier votre rendez-vous atelier, complétez notre formulaire en ligne :\n"
                       "https://top-auto.ma/Entretienr%C3%A9paration\n\n"
                       "Votre demande a également été transmise à notre équipe qui vous contactera pour confirmer.")
                return msg + "\n\nMerci pour votre confiance.", True
            else:
                return recap_texte(infos, flow), False

    # ----------------------------------------------------------------
    # FLUX VN (informations véhicules neufs)
    # ----------------------------------------------------------------
    elif flow == "vn":
        if step == 1:
            infos["prenom"] = nettoyer(tl)
            sess["step"] = 2
            return "Votre numéro de téléphone ?", False
        elif step == 2:
            if not valider_tel(tl):
                return "Numéro invalide. Format : 0612345678.", False
            infos["tel"] = nettoyer(tl)
            infos["type"] = "vn"
            ok = enregistrer(tel, sess["langue"], infos)
            notifier_conseiller(tel, nom, infos)
            reset_flow(sess)
            return "Merci ! Notre conseiller commercial vous contactera très prochainement avec toutes les informations et le meilleur tarif personnalisé. Merci pour votre confiance.", True

    # ----------------------------------------------------------------
    # FLUX VO (véhicules occasion)
    # ----------------------------------------------------------------
    elif flow == "vo":
        if step == 1:
            infos["prenom"] = nettoyer(tl)
            sess["step"] = 2
            return "Votre numéro de téléphone ?", False
        elif step == 2:
            if not valider_tel(tl):
                return "Numéro invalide. Format : 0612345678.", False
            infos["tel"] = nettoyer(tl)
            infos["type"] = "vo"
            ok = enregistrer(tel, sess["langue"], infos)
            notifier_conseiller(tel, nom, infos)
            reset_flow(sess)
            return "Merci ! Notre conseiller VO vous contactera rapidement. En attendant, consultez notre stock : https://top-auto.ma/Voitures_occasion\n\nMerci pour votre confiance.", True

    # ----------------------------------------------------------------
    # FLUX MAINLEVÉE
    # ----------------------------------------------------------------
    elif flow == "mainlevee":
        if step == 1:
            infos["prenom"] = nettoyer(tl)
            sess["step"] = 2
            return "Votre nom ?", False
        elif step == 2:
            infos["nom"] = nettoyer(tl)
            sess["step"] = 3
            return "Votre numéro de téléphone ?", False
        elif step == 3:
            if not valider_tel(tl):
                return "Numéro invalide. Format : 0612345678.", False
            infos["tel"] = nettoyer(tl)
            sess["step"] = 4
            return "Votre numéro de châssis ?", False
        elif step == 4:
            infos["chassis"] = nettoyer(tl).upper()
            infos["type"] = "mainlevee"
            sess["step"] = 5
            return recap_texte(infos, flow), False
        elif step == 5:
            if any(w in tl.lower() for w in ["oui","yes","wah","iyeh","safi","ok","correct","confirme","d'accord","mzyan"]):
                ok = enregistrer(tel, sess["langue"], infos)
                notifier_conseiller(tel, nom, infos)
                reset_flow(sess)
                return ("Votre demande de mainlevée a été enregistrée. Notre équipe SAV vous contactera sous 24-48h.\n\n"
                        "Merci pour votre confiance."), True
            else:
                return recap_texte(infos, flow), False

    return None, False

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
        msg_id = msgs[0].get("id","")
        if msg_id and msg_id in processed_ids:
            print(f"[DUP] Message déjà traité: {msg_id}")
            return jsonify({"status":"ok"}), 200
        if msg_id:
            processed_ids.add(msg_id)
            if len(processed_ids) > 500:
                processed_ids.clear()
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
                wa_text(tel, "Impossible de traiter ce vocal. Merci d'écrire votre demande.")
                return jsonify({"status":"ok"}), 200
            h = {"Authorization": f"Bearer {tok}"}
            ru = requests.get(f"https://graph.facebook.com/v20.0/{mid}", headers=h, timeout=10)
            if ru.status_code != 200:
                wa_text(tel, "Erreur audio. Appelez le 0523303194.")
                return jsonify({"status":"ok"}), 200
            ra = requests.get(ru.json().get("url"), headers=h, timeout=20)
            transcrit = groq_whisper(ra.content)
            if not transcrit:
                wa_text(tel, "Transcription impossible. Merci d'écrire votre demande.")
                return jsonify({"status":"ok"}), 200
            wa_text(tel, f"J'ai entendu : \"{transcrit}\"")
            texte = transcrit

        # ---- IMAGE ----
        elif mtype == "image":
            wa_text(tel, "Photo reçue, analyse en cours...")
            mid  = msg.get("image",{}).get("id")
            mime = msg.get("image",{}).get("mime_type","image/jpeg")
            if not mid:
                wa_text(tel, "Impossible d'analyser. Merci pour votre confiance.")
                return jsonify({"status":"ok"}), 200
            h  = {"Authorization": f"Bearer {tok}"}
            ru = requests.get(f"https://graph.facebook.com/v20.0/{mid}", headers=h, timeout=10)
            ri = requests.get(ru.json().get("url"), headers=h, timeout=20)
            analyse = groq_vision(base64.b64encode(ri.content).decode(), mime)
            wa_text(tel, analyse)
            wa_btns(tel, "Souhaitez-vous un rendez-vous atelier ?",
                [{"id":"btn_rdv_sav","title":"Prendre RDV"},
                 {"id":"btn_autre_q","title":"Autre question"}])
            return jsonify({"status":"ok"}), 200

        # ---- TEXTE ----
        elif mtype == "text":
            texte = msg.get("text",{}).get("body","").strip()

        # ---- BOUTON INTERACTIF ----
        elif mtype == "interactive":
            br  = msg.get("interactive",{}).get("button_reply",{})
            bid = br.get("id","")
            texte = br.get("title","")

            sess = get_sess(tel)

            if bid == "btn_vehicules":
                wa_menu_veh(tel)
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_sav":
                reset_flow(sess)
                sess["flow"] = "sav"
                sess["step"] = 1
                wa_text(tel, "Pour planifier votre rendez-vous atelier :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\nSouhaitez-vous également laisser vos coordonnées pour qu'un conseiller vous rappelle ?")
                wa_btns(tel, "Laisser mes coordonnées ?",
                    [{"id":"btn_sav_oui","title":"Oui, me rappeler"},
                     {"id":"btn_sav_non","title":"Non, merci"}])
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_sav_oui":
                reset_flow(sess)
                sess["flow"] = "sav"
                sess["step"] = 1
                wa_text(tel, "Votre prénom, s'il vous plaît ?")
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_sav_non":
                reset_flow(sess)
                wa_text(tel, "Très bien. N'hésitez pas à revenir si vous avez besoin d'aide. Merci pour votre confiance.")
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_autre":
                wa_menu_autre(tel)
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_vn":
                reset_flow(sess)
                wa_text(tel, CATALOGUE + "\n\nPour obtenir un tarif personnalisé et vérifier la disponibilité, notre conseiller vous contactera.\nPuis-je noter votre prénom ?")
                sess["flow"] = "vn"
                sess["step"] = 1
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_vo":
                reset_flow(sess)
                wa_text(tel, "Consultez notre stock de véhicules d'occasion :\nhttps://top-auto.ma/Voitures_occasion\n\nPour une mise en relation avec notre conseiller VO, puis-je noter votre prénom ?")
                sess["flow"] = "vo"
                sess["step"] = 1
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_essai":
                reset_flow(sess)
                sess["flow"] = "essai"
                sess["step"] = 1
                wa_text(tel, "Votre prénom, s'il vous plaît ?")
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_facture":
                reset_flow(sess)
                sess["flow"] = "facture"
                sess["step"] = 1
                wa_text(tel, "Quel type de facture souhaitez-vous ?\n\n1. Achat véhicule (VN/VO)\n2. Atelier mécanique\n3. Carrosserie\n4. Pièces de rechange")
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_mainlevee":
                reset_flow(sess)
                wa_text(tel,
                    "Pour votre demande de mainlevée, présentez-vous en concession avec :\n\n"
                    "• Copie de la CIN\n"
                    "• Copie de la carte grise\n"
                    "• Relevé bancaire cacheté (dernier prélèvement RCI Finance)\n"
                    "• Justificatif de paiement de la valeur résiduelle (si applicable)\n\n"
                    "Souhaitez-vous qu'un conseiller vous contacte pour préparer votre dossier ?")
                wa_btns(tel, "Être rappelé par un conseiller ?",
                    [{"id":"btn_ml_oui","title":"Oui, me rappeler"},
                     {"id":"btn_ml_non","title":"Non, merci"}])
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_ml_oui":
                reset_flow(sess)
                sess["flow"] = "mainlevee"
                sess["step"] = 1
                wa_text(tel, "Votre prénom ?")
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_ml_non":
                reset_flow(sess)
                wa_text(tel, "D'accord. N'hésitez pas si vous avez des questions. Merci pour votre confiance.")
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_reclamation":
                reset_flow(sess)
                sess["flow"] = "reclamation"
                sess["step"] = 1
                wa_text(tel, "Je suis désolé d'apprendre ce problème. Votre satisfaction est notre priorité.\n\nVotre prénom, s'il vous plaît ?")
                return jsonify({"status":"ok"}), 200
            elif bid in ("btn_rdv_sav",):
                wa_text(tel, "Pour votre rendez-vous atelier :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\nMerci pour votre confiance.")
                return jsonify({"status":"ok"}), 200
            elif bid in ("btn_autre_q",):
                wa_text(tel, "Je suis à votre écoute. Comment puis-je vous aider ? Merci pour votre confiance.")
                return jsonify({"status":"ok"}), 200
        else:
            return jsonify({"status":"ok"}), 200

        if not texte:
            return jsonify({"status":"ok"}), 200

        print(f"\n[MSG] {tel} ({nom}): {texte[:60]}")
        sess = get_sess(tel)

        # Détecter langue
        tl = texte.lower().strip()
        if any('\u0600' <= c <= '\u06FF' for c in texte):
            sess["langue"] = "AR"
        elif any(w in tl for w in ["bghit","wach","safi","3afak","chokran","labas","mzyan","iyeh","wah","daba","3ndkm","mnin","fin"]):
            sess["langue"] = "DARIJA"

        # ---- FLUX ACTIF → machine à états ----
        if sess.get("flow"):
            rep, done = traiter_flow(sess, tel, nom, texte)
            if rep:
                sess["hist"].append({"role":"user","content":texte})
                sess["hist"].append({"role":"assistant","content":rep})
                if len(sess["hist"]) > 10:
                    sess["hist"] = sess["hist"][-10:]
                wa_text(tel, rep)
                return jsonify({"status":"ok"}), 200

        # ---- SALUTATION INITIALE ----
        saluts = ["bonjour","salam","salut","hi","hello","bonsoir","مرحبا","السلام",
                  "ahlan","bjr","bsr","coucou","sbah","msa","slm","labas","la bas"]
        mots = tl.split()
        if not sess["hist"] and len(mots) <= 4 and any(s in tl for s in saluts):
            wa_bienvenue(tel)
            return jsonify({"status":"ok"}), 200

        # ---- DÉTECTION DIRECTE (sans LLM) ----
        # Textes de boutons envoyés comme texte
        tl_strip = tl.strip()
        if tl_strip in ["véhicules","vehicules"]:
            wa_menu_veh(tel)
            return jsonify({"status":"ok"}), 200
        if tl_strip in ["autre demande","autre"]:
            wa_menu_autre(tel)
            return jsonify({"status":"ok"}), 200
        if tl_strip in ["sav & atelier","sav","sav &amp; atelier"]:
            wa_text(tel, "Pour votre RDV atelier :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\nMerci pour votre confiance.")
            return jsonify({"status":"ok"}), 200

        # Prix / tarifs → intercepter avant LLM
        intent = detecter_intent_direct(texte)

        if intent == "PRIX":
            wa_text(tel, "Pour vous communiquer le meilleur tarif personnalisé et vérifier la disponibilité en stock, je transmets votre demande à notre équipe commerciale. Un conseiller vous contactera très prochainement.\n\nPuis-je noter votre prénom et numéro de téléphone ?")
            reset_flow(sess)
            sess["flow"] = "vn"
            sess["step"] = 1
            return jsonify({"status":"ok"}), 200

        if intent == "FAQ_HORAIRE":
            wa_text(tel, "Nos horaires d'ouverture :\n\n• Lundi – Vendredi : 8h00 – 18h30\n• Samedi : 8h30 – 15h00\n• Dimanche : Fermé\n\nMerci pour votre confiance.")
            return jsonify({"status":"ok"}), 200

        if intent == "FAQ_ADRESSE":
            wa_text(tel, "Nous sommes situés au :\nQ.I Bd Sidi Mohamed Ben Abdellah, 208000 Mohammedia\n\nGPS : https://maps.google.com/?q=33.683384,-7.409769\n\nMerci pour votre confiance.")
            return jsonify({"status":"ok"}), 200

        if intent == "FAQ_TEL":
            wa_text(tel, "Nos numéros :\n• Renault : 0523303194\n• Dacia : 0523303195\n• Email : contact@top-auto.ma\n\nMerci pour votre confiance.")
            return jsonify({"status":"ok"}), 200

        if intent == "FAQ_SUIVI":
            wa_text(tel, "Pour toute information concernant l'avancement des travaux, le suivi de commande ou la réception des pièces, veuillez contacter notre service au 0523303194. Un conseiller vous répondra rapidement.\n\nMerci pour votre confiance.")
            return jsonify({"status":"ok"}), 200

        # Détecter intentions de démarrer un flux
        if any(w in tl for w in ["essai","test drive","tester","conduire","essayer"]):
            reset_flow(sess)
            sess["flow"] = "essai"
            sess["step"] = 1
            wa_text(tel, "Votre prénom, s'il vous plaît ?")
            return jsonify({"status":"ok"}), 200

        if any(w in tl for w in ["rdi","récépissé","recepisse","immatriculation","dépôt","depot"]):
            reset_flow(sess)
            sess["flow"] = "rdi"
            sess["step"] = 1
            wa_text(tel, "Votre véhicule a-t-il été livré il y a plus de 30 jours ? (Oui / Non)")
            return jsonify({"status":"ok"}), 200

        if any(w in tl for w in ["facture","reçu","recu","ticket"]):
            reset_flow(sess)
            sess["flow"] = "facture"
            sess["step"] = 1
            wa_text(tel, "Quel type de facture souhaitez-vous ?\n\n1. Achat véhicule (VN/VO)\n2. Atelier mécanique\n3. Carrosserie\n4. Pièces de rechange")
            return jsonify({"status":"ok"}), 200

        if any(w in tl for w in ["mainlevée","mainlevee","main levée","main levee"]):
            reset_flow(sess)
            wa_text(tel,
                "Pour votre demande de mainlevée, présentez-vous en concession avec :\n\n"
                "• Copie de la CIN\n"
                "• Copie de la carte grise\n"
                "• Relevé bancaire cacheté (dernier prélèvement RCI Finance)\n"
                "• Justificatif de paiement de la valeur résiduelle (si applicable)\n\n"
                "Souhaitez-vous qu'un conseiller vous contacte pour préparer votre dossier ?")
            wa_btns(tel, "Être rappelé par un conseiller ?",
                [{"id":"btn_ml_oui","title":"Oui, me rappeler"},
                 {"id":"btn_ml_non","title":"Non, merci"}])
            return jsonify({"status":"ok"}), 200

        if any(w in tl for w in ["réclamation","reclamation","plainte","problème","probleme","insatisfait"]):
            reset_flow(sess)
            sess["flow"] = "reclamation"
            sess["step"] = 1
            wa_text(tel, "Je suis désolé d'apprendre ce problème. Votre satisfaction est notre priorité absolue.\n\nVotre prénom, s'il vous plaît ?")
            return jsonify({"status":"ok"}), 200

        if any(w in tl for w in ["rdv","rendez-vous","rendezvous","rendez vous","atelier","réparation","reparation","entretien"]):
            wa_text(tel,
                "Pour planifier votre rendez-vous atelier :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\n"
                "Un conseiller vous contactera rapidement pour confirmer votre rendez-vous.\n\nMerci pour votre confiance.")
            return jsonify({"status":"ok"}), 200

        if any(w in tl for w in ["occasion","vo","d'occasion"]):
            reset_flow(sess)
            wa_text(tel, "Consultez notre stock de véhicules d'occasion :\nhttps://top-auto.ma/Voitures_occasion\n\nPour être mis en relation avec notre conseiller VO, puis-je noter votre prénom ?")
            sess["flow"] = "vo"
            sess["step"] = 1
            return jsonify({"status":"ok"}), 200

        # ---- APPEL GROQ pour questions générales ----
        try:
            rep = groq_general(sess["hist"], texte)
            # Nettoyage : éviter "Merci pour votre confiance" en doublon
            rep = rep.strip()
            if not rep:
                rep = "Je n'ai pas bien compris. Pouvez-vous reformuler ? Merci pour votre confiance."
        except Exception as e:
            print(f"[GROQ ERR] {e}")
            rep = "Désolée, une erreur technique est survenue. Contactez-nous au 0523303194. Merci pour votre confiance."

        sess["hist"].append({"role":"user","content":texte})
        sess["hist"].append({"role":"assistant","content":rep})
        if len(sess["hist"]) > 10:
            sess["hist"] = sess["hist"][-10:]

        wa_text(tel, rep)
        return jsonify({"status":"ok"}), 200

    except Exception as e:
        print(f"[ERREUR GLOBAL] {e}")
        return jsonify({"status":"error"}), 200

@app.route("/", methods=["GET"])
def home():
    return "TopAuto WhatsApp Bot - Online", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[START] TopAuto Bot port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
