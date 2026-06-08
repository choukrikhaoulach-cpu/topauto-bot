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
# SESSIONS
# ============================================================
sessions = {}
processed_ids = set()
SESSION_TIMEOUT = 1800

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
    t = tel.replace(" ","").replace("-","").replace(".","")
    return bool(re.match(r'^(212[567]\d{8}|0[567]\d{8})$', t))

def valider_chassis(ch):
    return len(ch.replace(" ","")) >= 11

def valider_cin(cin):
    return bool(re.match(r'^[A-Za-z]{1,2}[0-9]{4,8}$', cin.strip()))

def nettoyer(val):
    val = val.strip()
    val = re.sub(r'[Mm]erci pour votre confiance\.?', '', val).strip()
    val = re.sub(r'[Cc]hokran.*', '', val).strip()
    return val.strip('. \n')

# ============================================================
# CATALOGUE & ÉTABLISSEMENT
# ============================================================
CATALOGUE = """
GAMME DACIA — VEHICULES NEUFS
------------------------------
DACIA SPRING — Citadine electrique
  Batterie 24,3 kWh | 70 ou 100 ch | Recharge AC 7kW / DC 40kW
  V2L | Coffre 308L | Finitions : Essential / Extreme

DACIA SANDERO STREETWAY 2026 — Citadine
  Ecran 10 pouces | SCe 65ch / TCe 100ch / dCi 102ch
  Finitions : Essential → Journey

DACIA SANDERO STEPWAY — Crossover urbain
  Garde au sol 17 cm | TCe 100ch / dCi 102ch / CVT Extreme
  Finitions : Essential → Extreme

DACIA LOGAN — Berline familiale
  Coffre 528L | SCe 65ch / TCe 100ch / dCi 102ch
  Finitions : Essential → Journey

DACIA JOGGER — Break 5/7 places
  Coffre 1 807L | TCe 100ch / dCi 102ch / HEV 140ch auto
  Finitions : Essential → Extreme

DACIA DUSTER 2025 — SUV 3e generation
  Media Nav 8" | Camera recul | CarPlay | dCi 115ch / TCe 130ch
  Finitions : Essential → Extreme

DACIA BIGSTER 2025 — Grand SUV (NOUVEAU)
  +23 cm vs Duster | Toit panoramique | dCi 115ch / HEV 155ch auto
  Finitions : Essential → Journey


GAMME RENAULT VP — VEHICULES NEUFS
------------------------------------
RENAULT CLIO 5 Phase 2 — Citadine
  TCe 100ch / Blue dCi 115ch / E-Tech 145ch auto
  Finitions : Equilibre → Esprit Alpine

RENAULT CLIO 6 — Nouvelle generation
  Design repense | TCe 100ch / E-Tech 145ch auto
  Finitions : Equilibre → Esprit Alpine

RENAULT CAPTUR — SUV urbain
  OpenR Link | Google | Ecran 10" | TCe 100ch CVT / E-Tech 145ch auto
  Finitions : Equilibre → Esprit Alpine

RENAULT 5 E-TECH — 100% Electrique
  40 kWh 120ch ou 52 kWh 150ch | Autonomie 400 km | DC 100 kW
  Finitions : Evolution → Esprit Alpine

RENAULT EXPRESS — Berline economique
  Diesel 95ch ou 115ch

RENAULT MEGANE SEDAN — Berline familiale
  Coffre 475L | Blue dCi 115ch
  Finitions : Equilibre → Esprit Alpine

RENAULT MEGANE E-TECH — Compacte electrique
  60 kWh | 450 km WLTP | 130 kW DC | 220ch | Google | Ecran 12"
  Finitions : Equilibre → Iconic

RENAULT ARKANA — Coupe-SUV hybride
  E-Tech 145ch | 4,5L/100km
  Finitions : Techno / Esprit Alpine

RENAULT AUSTRAL — SUV familial
  E-Tech 200ch | OpenR Link | Google | Full digital | 4,5L/100km
  Finitions : Techno / Esprit Alpine

RENAULT KARDIAN — SUV compact (SOMACA Maroc)
  Camera 360 | TCe 100ch CVT / Blue dCi 102ch
  Finitions : Equilibre / Techno


GAMME RENAULT VU — UTILITAIRES
--------------------------------
EXPRESS VAN : 800 kg | 3,3 m3 | dCi 75ch
TRAFIC : 1 400 kg | L1/L2 H1/H2 | dCi 150ch | Combi 9 places
MASTER : 1 700 kg | 8 a 17 m3 | dCi 145/180ch
"""

ETABLISSEMENT = """
TopAuto Mohammedia — Concessionnaire agree Renault & Dacia
Adresse : Q.I Bd Sidi Mohamed Ben Abdellah, 208000 Mohammedia
Tel Renault : 0523303194 | Tel Dacia : 0523303195
Email : contact@top-auto.ma
GPS : 33.683384 N, 7.409769 W
Maps : https://maps.google.com/?q=33.683384,-7.409769
Horaires : Lun-Ven 8h00-18h30 | Sam 8h30-15h00 | Dim Ferme
"""

# ============================================================
# DETECTION RAPIDE
# ============================================================
PRIX_KEYWORDS = ["prix", "tarif", "combien", "coute", "coûte",
                 "remise", "promotion", "mensualite", "mensualité",
                 "thaman", "b7al", "bchhal"]

def detecter_intent_direct(texte):
    tl = texte.lower()
    vehicule_ctx = any(w in tl for w in [
        "voiture","véhicule","vehicule","modèle","modele",
        "dacia","renault","suv","berline","familiale","citadine","break"])
    for kw in PRIX_KEYWORDS:
        if kw in tl and not vehicule_ctx:
            return "PRIX"
    if any(w in tl for w in ["horaire","heure","ouvert","fermé","ferme","ouverture"]):
        return "FAQ_HORAIRE"
    if any(w in tl for w in ["adresse","localisation","où êtes","ou etes","situé","situe","comment venir","gps","maps","itinéraire","itineraire"]):
        return "FAQ_ADRESSE"
    if any(w in tl for w in ["téléphone de","telephone de","numéro de contact","numero de contact","appeler","joindre"]):
        return "FAQ_TEL"
    if any(w in tl for w in ["suivi","avancement travaux","suivi commande","réception pièces","reception pieces"]):
        return "FAQ_SUIVI"
    return None

# ============================================================
# GROQ
# ============================================================
SYSTEM_PROMPT_GENERAL = """Tu es l'Assistant Virtuel de TopAuto Mohammedia, concessionnaire agréé Renault et Dacia.

REGLES ABSOLUES :
1. JAMAIS de prix, tarifs, mensualités. Si on te demande un prix, réponds : "Pour le meilleur tarif personnalisé, notre conseiller vous contactera très prochainement."
2. Répondre DIRECTEMENT, sans introduction
3. Aucun emoji dans le texte
4. Terminer par : Merci pour votre confiance.
5. Répondre dans la langue du client (FR / AR / Darija)
6. Pour les véhicules : donner des infos techniques détaillées (moteurs, finitions, équipements, dimensions)
7. Pour voiture familiale : recommander Logan, Jogger, Mégane Sedan, Duster
8. Pour SUV : mentionner Duster, Bigster, Captur, Kardian, Arkana, Austral avec leurs caractéristiques

CATALOGUE :""" + CATALOGUE + """
ETABLISSEMENT :""" + ETABLISSEMENT

def groq_general(hist, texte):
    key = cfg("GROQ_API_KEY")
    msgs = [{"role": "system", "content": SYSTEM_PROMPT_GENERAL}] + hist[-8:] + [{"role": "user", "content": texte}]
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "llama-3.3-70b-versatile", "messages": msgs, "max_tokens": 600, "temperature": 0.2},
        timeout=30)
    print(f"[GROQ] {r.status_code}")
    if r.status_code != 200:
        raise Exception(f"Groq {r.status_code}: {r.text[:100]}")
    return r.json()["choices"][0]["message"]["content"]

def groq_vision(b64, mime):
    key = cfg("GROQ_API_KEY")
    prompt = "Expert automobile TopAuto. Analyse image: 1-Probleme visible 2-Classification(carrosserie/mecanique/electronique/pneu) 3-Gravite(faible/modere/urgent) 4-Recommandation. Francais concis. Termine: Merci pour votre confiance."
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "meta-llama/llama-4-scout-17b-16e-instruct",
              "messages": [{"role": "user", "content": [
                  {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                  {"type": "text", "text": prompt}]}],
              "max_tokens": 400}, timeout=30)
    if r.status_code != 200:
        return "Impossible d'analyser. Presentez-vous en atelier. Merci pour votre confiance."
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
def wa_token(): return cfg("WHATSAPP_TOKEN")
def wa_pid():   return cfg("PHONE_NUMBER_ID", PHONE_NUMBER_ID)
def wa_cons():  return cfg("CONSEILLER_WHATSAPP", CONSEILLER_TEL)

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
        "Bonjour et bienvenue chez TopAuto Mohammedia, concessionnaire agree Renault et Dacia.\n\n"
        "Je suis l'Assistant Virtuel, disponible 24/7 pour vous accompagner concernant :\n"
        "- Les vehicules Renault et Dacia (neufs et occasion)\n"
        "- L'entretien et les reparations\n"
        "- Les pieces de rechange et carrosserie\n"
        "- Les demandes administratives\n"
        "- Les rendez-vous apres-vente\n\n"
        "Comment puis-je vous aider aujourd'hui ?",
        [{"id": "btn_vehicules", "title": "Vehicules"},
         {"id": "btn_sav", "title": "SAV & Atelier"},
         {"id": "btn_autre", "title": "Autre demande"}])

def wa_menu_veh(tel):
    wa_btns(tel, "Quelle gamme vous interesse ?",
        [{"id": "btn_vn", "title": "Vehicules Neufs"},
         {"id": "btn_vo", "title": "Vehicules Occasion"},
         {"id": "btn_essai", "title": "Essai Gratuit"}])

def wa_menu_autre(tel):
    wa_btns(tel, "Quelle est votre demande ?",
        [{"id": "btn_facture", "title": "Demande Facture"},
         {"id": "btn_mainlevee", "title": "Mainlevee"},
         {"id": "btn_reclamation", "title": "Reclamation"}])

def notifier_conseiller(tel, nom_wa, data):
    t = data.get("type", "vn")
    _, sn = get_sheet(t)
    lignes = [f"--- NOUVEAU LEAD : {sn} ---", f"WA client : {tel}", f"Nom WA : {nom_wa}"]
    for k, l in [("prenom","Prenom"),("nom","Nom"),("tel","Tel"),("modele","Modele"),
                 ("ville","Ville"),("chassis","Chassis"),("cin","CIN"),("rc","RC"),
                 ("type_facture","Type facture"),("reclamation","Reclamation"),
                 ("description","Description"),("date_essai","Date essai")]:
        if data.get(k):
            lignes.append(f"{l} : {data[k]}")
    lignes.append(f"Statut : {'URGENT 48h' if t == 'reclamation' else 'A RAPPELER'}")
    wa_text(wa_cons(), "\n".join(lignes))

def recap_texte(data, flow):
    t = "Recapitulatif de votre demande :\n"
    for k, l in [("prenom","Prenom"), ("nom","Nom"), ("tel","Telephone"),
                 ("modele","Modele souhaite"), ("ville","Ville"),
                 ("date_essai","Date souhaitee"), ("chassis","Numero de chassis"),
                 ("cin","CIN"), ("rc","RC societe"), ("type_facture","Type de facture"),
                 ("reclamation","Reclamation"), ("description","Description")]:
        v = data.get(k, "")
        if v and v not in ["X", "", "null", "?"]:
            t += f"- {l} : {v}\n"
    t += "\nCes informations sont-elles correctes ? (Repondez Oui ou Non)"
    return t

# ============================================================
# MACHINES A ETATS
# ============================================================
def traiter_flow(sess, tel, nom, texte):
    flow = sess["flow"]
    step = sess["step"]
    infos = sess["infos"]
    tl = texte.strip()
    print(f"[FLOW] {flow} | STEP {step} | msg={tl[:30]}")

    # ESSAI VN
    if flow == "essai":
        if step == 1:
            infos["prenom"] = nettoyer(tl)
            sess["step"] = 2
            return "Votre nom, s'il vous plait ?", False
        elif step == 2:
            infos["nom"] = nettoyer(tl)
            sess["step"] = 3
            return "Votre numero de telephone ?", False
        elif step == 3:
            if not valider_tel(tl):
                return "Numero invalide. Format valide : 0612345678 ou 212612345678.", False
            infos["tel"] = nettoyer(tl)
            sess["step"] = 4
            return "Quel modele souhaitez-vous essayer ? (ex: Dacia Duster, Renault Clio...)", False
        elif step == 4:
            infos["modele"] = nettoyer(tl)
            sess["step"] = 5
            return "Dans quelle ville souhaitez-vous effectuer l'essai ?", False
        elif step == 5:
            infos["ville"] = nettoyer(tl)
            sess["step"] = 6
            return "Avez-vous une date souhaitee pour l'essai ? (ex: 15/06/2026 ou 'des que possible')", False
        elif step == 6:
            infos["date_essai"] = nettoyer(tl) if tl.lower() not in ["non","no","la","pas"] else "Des que possible"
            sess["step"] = 7
            return recap_texte(infos, flow), False
        elif step == 7:
            if any(w in tl.lower() for w in ["oui","yes","wah","iyeh","safi","ok","correct","parfait","confirme","d'accord","mzyan"]):
                ok = enregistrer(tel, sess["langue"], {**infos, "type": "essai"})
                notifier_conseiller(tel, nom, {**infos, "type": "essai"})
                reset_flow(sess)
                msg = "Votre demande d'essai a bien ete enregistree. Notre service commercial vous contactera tres prochainement pour confirmer la date."
                if not ok:
                    msg += "\n\nNote : incident technique lors de l'enregistrement. Un conseiller vous contactera."
                return msg + "\n\nMerci pour votre confiance.", True
            elif any(w in tl.lower() for w in ["non","no","la","modifier","changer","corriger","faux"]):
                sess["step"] = 8
                return "Quelle information souhaitez-vous modifier ? (prenom / nom / telephone / modele / ville / date)", False
            else:
                return "Veuillez repondre par Oui ou Non.\n\n" + recap_texte(infos, flow), False
        elif step == 8:
            tll = tl.lower()
            if "prenom" in tll:
                infos.pop("prenom", None); sess["step"] = 1; return "Votre prenom ?", False
            elif "nom" in tll:
                infos.pop("nom", None); sess["step"] = 2; return "Votre nom ?", False
            elif "telephone" in tll or "tel" in tll:
                infos.pop("tel", None); sess["step"] = 3; return "Votre telephone ?", False
            elif "modele" in tll or "vehicule" in tll:
                infos.pop("modele", None); sess["step"] = 4; return "Quel modele ?", False
            elif "ville" in tll:
                infos.pop("ville", None); sess["step"] = 5; return "Quelle ville ?", False
            elif "date" in tll:
                infos.pop("date_essai", None); sess["step"] = 6; return "Quelle date ?", False
            else:
                return "Precisez : prenom, nom, telephone, modele, ville ou date.", False

    # RDI
    elif flow == "rdi":
        if step == 1:
            oui = any(w in tl.lower() for w in ["oui","yes","wah","iyeh","safi","ok","ouai","si"])
            non = any(w in tl.lower() for w in ["non","no","la","pas encore","pas"])
            if oui:
                sess["step"] = 2
                return "Etes-vous un particulier ou une societe ?", False
            elif non:
                reset_flow(sess)
                return "Le delai reglementaire de 30 jours n'est pas encore ecoule. Vous pourrez faire votre demande de RDI passe ce delai. Merci pour votre confiance.", True
            else:
                return "Votre vehicule a-t-il ete livre il y a plus de 30 jours ? (Oui / Non)", False
        elif step == 2:
            if any(w in tl.lower() for w in ["particulier","prive","individuel","personne"]):
                infos["type_client"] = "particulier"; sess["step"] = 3
            elif any(w in tl.lower() for w in ["societe","entreprise","ste","rc","commerce"]):
                infos["type_client"] = "societe"; sess["step"] = 3
            else:
                return "Etes-vous un particulier ou une societe ?", False
            return "Votre prenom, s'il vous plait ?", False
        elif step == 3:
            infos["prenom"] = nettoyer(tl); sess["step"] = 4
            return "Votre numero de chassis (VIN) ?", False
        elif step == 4:
            ch = tl.replace(" ","")
            if not valider_chassis(ch):
                return "Numero de chassis incomplet (minimum 11 caracteres). Merci de le verifier.", False
            infos["chassis"] = ch.upper(); sess["step"] = 5
            return ("Votre numero de Registre de Commerce (RC) ?" if infos.get("type_client") == "societe"
                    else "Votre numero de CIN ?"), False
        elif step == 5:
            if infos.get("type_client") == "societe":
                infos["rc"] = nettoyer(tl).upper()
            else:
                cin = nettoyer(tl).upper()
                if not valider_cin(cin):
                    return "Format CIN invalide (ex: BE123456). Merci de verifier.", False
                infos["cin"] = cin
            sess["step"] = 6
            return "Votre numero de telephone ?", False
        elif step == 6:
            if not valider_tel(tl):
                return "Numero invalide. Format : 0612345678 ou 212612345678.", False
            infos["tel"] = nettoyer(tl); sess["step"] = 7
            return recap_texte(infos, flow), False
        elif step == 7:
            if any(w in tl.lower() for w in ["oui","yes","wah","iyeh","safi","ok","correct","parfait","confirme","d'accord","mzyan"]):
                info_rdi = verifier_rdi(infos.get("chassis",""))
                if info_rdi is None:
                    rep = "Impossible d'acceder au systeme. Notre equipe vous contactera tres prochainement."
                    notifier_conseiller(tel, nom, {**infos, "type": "rdi"})
                elif info_rdi.get("trouve"):
                    statut = info_rdi.get("statut","En cours")
                    date_d = info_rdi.get("date_dispo","")
                    rep = f"Verification de votre dossier :\n- Chassis : {infos['chassis']}\n- Statut : {statut}"
                    if date_d:
                        rep += f"\n- Date de disponibilite : {date_d}"
                    rep += "\n\nPour toute question : 0523303194."
                else:
                    rep = f"Le dossier pour le chassis {infos['chassis']} n'est pas encore enregistre. Notre equipe va verifier et vous contactera."
                    notifier_conseiller(tel, nom, {**infos, "type": "rdi"})
                reset_flow(sess)
                return rep + "\n\nMerci pour votre confiance.", True
            elif any(w in tl.lower() for w in ["non","no","la","modifier","changer"]):
                sess["step"] = 8
                return "Quelle information modifier ? (prenom / chassis / cin / rc / telephone)", False
            else:
                return "Repondez Oui ou Non.\n\n" + recap_texte(infos, flow), False
        elif step == 8:
            tll = tl.lower()
            if "prenom" in tll: sess["step"] = 3; return "Votre prenom ?", False
            elif "chassis" in tll or "vin" in tll: infos.pop("chassis",None); sess["step"] = 4; return "Votre chassis ?", False
            elif "cin" in tll: infos.pop("cin",None); sess["step"] = 5; return "Votre CIN ?", False
            elif "rc" in tll: infos.pop("rc",None); sess["step"] = 5; return "Votre RC ?", False
            elif "telephone" in tll or "tel" in tll: infos.pop("tel",None); sess["step"] = 6; return "Votre telephone ?", False
            else: return "Precisez : prenom, chassis, CIN, RC ou telephone.", False

    # FACTURE
    elif flow == "facture":
        if step == 1:
            tll = tl.lower()
            if any(w in tll for w in ["vente","achat","neuf","occasion","vn","vo","1"]):
                infos["type_facture"] = "Vente VN/VO"; infos["type"] = "facture_vente"
            elif any(w in tll for w in ["mecanique","atelier","entretien","reparation","2"]):
                infos["type_facture"] = "Mecanique"; infos["type"] = "facture_mecanique"
            elif any(w in tll for w in ["carrosserie","peinture","bosselure","rayure","3"]):
                infos["type_facture"] = "Carrosserie"; infos["type"] = "facture_carrosserie"
            elif any(w in tll for w in ["piece","rechange","accessoire","4"]):
                infos["type_facture"] = "Pieces de rechange"; infos["type"] = "facture_pieces"
            else:
                return "Quel type de facture ?\n\n1. Achat vehicule (VN/VO)\n2. Atelier mecanique\n3. Carrosserie\n4. Pieces de rechange", False
            sess["step"] = 2
            return "Votre numero de chassis ou matricule du vehicule ?", False
        elif step == 2:
            infos["chassis"] = nettoyer(tl).upper(); sess["step"] = 3
            return "Nom du titulaire de la facture ?", False
        elif step == 3:
            infos["nom"] = nettoyer(tl); sess["step"] = 4
            return "Votre numero de telephone ?", False
        elif step == 4:
            if not valider_tel(tl):
                return "Numero invalide. Format : 0612345678.", False
            infos["tel"] = nettoyer(tl); sess["step"] = 5
            return recap_texte(infos, flow), False
        elif step == 5:
            if any(w in tl.lower() for w in ["oui","yes","wah","iyeh","safi","ok","correct","parfait","confirme","d'accord","mzyan"]):
                ok = enregistrer(tel, sess["langue"], infos)
                notifier_conseiller(tel, nom, infos)
                reset_flow(sess)
                msg = f"Votre demande de facture ({infos.get('type_facture','')}) a ete enregistree. Notre equipe vous contactera rapidement."
                if not ok: msg += "\n\nNote : incident technique. Un conseiller vous contactera."
                return msg + "\n\nMerci pour votre confiance.", True
            elif any(w in tl.lower() for w in ["non","no","la","modifier","changer"]):
                sess["step"] = 6
                return "Quelle information modifier ? (type / chassis / nom / telephone)", False
            else:
                return "Repondez Oui ou Non.\n\n" + recap_texte(infos, flow), False
        elif step == 6:
            tll = tl.lower()
            if "type" in tll or "facture" in tll:
                infos.pop("type_facture",None); infos.pop("type",None); sess["step"] = 1
                return "Quel type de facture ?\n\n1. Achat vehicule\n2. Mecanique\n3. Carrosserie\n4. Pieces", False
            elif "chassis" in tll or "matricule" in tll: sess["step"] = 2; return "Chassis ou matricule ?", False
            elif "nom" in tll: sess["step"] = 3; return "Nom du titulaire ?", False
            elif "telephone" in tll or "tel" in tll: sess["step"] = 4; return "Telephone ?", False
            else: return "Precisez : type, chassis, nom ou telephone.", False

    # RECLAMATION
    elif flow == "reclamation":
        if step == 1:
            infos["prenom"] = nettoyer(tl); sess["step"] = 2
            return "Votre nom ?", False
        elif step == 2:
            infos["nom"] = nettoyer(tl); sess["step"] = 3
            return "Votre numero de telephone ?", False
        elif step == 3:
            if not valider_tel(tl):
                return "Numero invalide. Format : 0612345678.", False
            infos["tel"] = nettoyer(tl); sess["step"] = 4
            return "Numero de chassis ou plaque (si applicable, sinon tapez 'non') ?", False
        elif step == 4:
            if tl.lower() not in ["non","no","la","pas","n/a"]:
                infos["chassis"] = nettoyer(tl).upper()
            sess["step"] = 5
            return "Decrivez votre reclamation en detail :", False
        elif step == 5:
            infos["reclamation"] = nettoyer(tl); infos["type"] = "reclamation"; sess["step"] = 6
            return recap_texte(infos, flow), False
        elif step == 6:
            if any(w in tl.lower() for w in ["oui","yes","wah","iyeh","safi","ok","correct","confirme","d'accord","mzyan"]):
                ok = enregistrer(tel, sess["langue"], infos)
                notifier_conseiller(tel, nom, infos)
                reset_flow(sess)
                msg = "Votre reclamation a ete enregistree et transmise a notre responsable qualite. Reponse sous 48 heures ouvrees."
                if not ok: msg += "\n\nNote : incident technique. Un conseiller vous contactera."
                return msg + "\n\nMerci pour votre confiance.", True
            elif any(w in tl.lower() for w in ["non","no","la","modifier","changer"]):
                sess["step"] = 7
                return "Quelle information modifier ? (prenom / nom / telephone / chassis / description)", False
            else:
                return "Repondez Oui ou Non.\n\n" + recap_texte(infos, flow), False
        elif step == 7:
            tll = tl.lower()
            if "prenom" in tll: sess["step"] = 1; return "Votre prenom ?", False
            elif "nom" in tll: sess["step"] = 2; return "Votre nom ?", False
            elif "telephone" in tll or "tel" in tll: sess["step"] = 3; return "Votre telephone ?", False
            elif "chassis" in tll: sess["step"] = 4; return "Numero de chassis ?", False
            elif "description" in tll or "reclamation" in tll: sess["step"] = 5; return "Decrivez votre reclamation :", False
            else: return "Precisez : prenom, nom, telephone, chassis ou description.", False

    # SAV
    elif flow == "sav":
        if step == 1:
            _tll = tl.lower().strip().split()
            if any(w in _tll for w in ["non","no","la","pas"]) or any(w in tl.lower() for w in ["pas besoin","non merci","bghit la"]):
                reset_flow(sess)
                lien = "https://top-auto.ma/Entretienr%C3%A9paration"
                return f"Tres bien. Pour votre RDV atelier : {lien}\n\nMerci pour votre confiance.", True
            infos["prenom"] = nettoyer(tl); sess["step"] = 2
            return "Votre nom ?", False
        elif step == 2:
            infos["nom"] = nettoyer(tl); sess["step"] = 3
            return "Votre numero de telephone ?", False
        elif step == 3:
            if not valider_tel(tl):
                return "Numero invalide. Format : 0612345678.", False
            infos["tel"] = nettoyer(tl); infos["type"] = "sav_atelier"; sess["step"] = 4
            return recap_texte(infos, flow), False
        elif step == 4:
            if any(w in tl.lower() for w in ["oui","yes","wah","iyeh","safi","ok","correct","confirme","d'accord","mzyan"]):
                ok = enregistrer(tel, sess["langue"], infos)
                notifier_conseiller(tel, nom, infos)
                reset_flow(sess)
                return ("Pour votre rendez-vous atelier :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\n"
                        "Votre demande a ete transmise. Notre equipe vous contactera pour confirmer.\n\nMerci pour votre confiance."), True
            else:
                return recap_texte(infos, flow), False

    # VN
    elif flow == "vn":
        if step == 1:
            _tll = tl.lower().strip().split()
            if any(w in _tll for w in ["non","no","la","pas"]) or any(w in tl.lower() for w in ["pas besoin","non merci","bghit la"]):
                reset_flow(sess)
                return "Tres bien. N'hesitez pas a nous contacter si vous avez besoin d'aide. Merci pour votre confiance.", True
            infos["prenom"] = nettoyer(tl); sess["step"] = 2
            return "Votre numero de telephone ?", False
        elif step == 2:
            if not valider_tel(tl):
                return "Numero invalide. Format : 0612345678.", False
            infos["tel"] = nettoyer(tl); infos["type"] = "vn"
            enregistrer(tel, sess["langue"], infos)
            notifier_conseiller(tel, nom, infos)
            reset_flow(sess)
            return "Merci ! Notre conseiller vous contactera tres prochainement avec le meilleur tarif personnalise. Merci pour votre confiance.", True

    # VO
    elif flow == "vo":
        if step == 1:
            _tll = tl.lower().strip().split()
            if any(w in _tll for w in ["non","no","la","pas"]) or any(w in tl.lower() for w in ["pas besoin","non merci","bghit la"]):
                reset_flow(sess)
                return "Tres bien. Consultez notre stock : https://top-auto.ma/Voitures_occasion\n\nMerci pour votre confiance.", True
            infos["prenom"] = nettoyer(tl); sess["step"] = 2
            return "Votre numero de telephone ?", False
        elif step == 2:
            if not valider_tel(tl):
                return "Numero invalide. Format : 0612345678.", False
            infos["tel"] = nettoyer(tl); infos["type"] = "vo"
            enregistrer(tel, sess["langue"], infos)
            notifier_conseiller(tel, nom, infos)
            reset_flow(sess)
            return "Merci ! Notre conseiller VO vous contactera rapidement.\nStock occasion : https://top-auto.ma/Voitures_occasion\n\nMerci pour votre confiance.", True

    # MAINLEVEE
    elif flow == "mainlevee":
        if step == 1:
            infos["prenom"] = nettoyer(tl); sess["step"] = 2
            return "Votre nom ?", False
        elif step == 2:
            infos["nom"] = nettoyer(tl); sess["step"] = 3
            return "Votre numero de telephone ?", False
        elif step == 3:
            if not valider_tel(tl):
                return "Numero invalide. Format : 0612345678.", False
            infos["tel"] = nettoyer(tl); sess["step"] = 4
            return "Votre numero de chassis ?", False
        elif step == 4:
            infos["chassis"] = nettoyer(tl).upper(); infos["type"] = "mainlevee"; sess["step"] = 5
            return recap_texte(infos, flow), False
        elif step == 5:
            if any(w in tl.lower() for w in ["oui","yes","wah","iyeh","safi","ok","correct","confirme","d'accord","mzyan"]):
                ok = enregistrer(tel, sess["langue"], infos)
                notifier_conseiller(tel, nom, infos)
                reset_flow(sess)
                return "Votre demande de mainlevee a ete enregistree. Notre equipe SAV vous contactera sous 24-48h.\n\nMerci pour votre confiance.", True
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

        # Déduplication
        msg_id = msgs[0].get("id","")
        if msg_id and msg_id in processed_ids:
            print(f"[DUP] {msg_id}")
            return jsonify({"status":"ok"}), 200
        if msg_id:
            processed_ids.add(msg_id)
            if len(processed_ids) > 500:
                processed_ids.clear()

        msg   = msgs[0]
        tel   = msg.get("from")
        nom   = value.get("contacts",[{}])[0].get("profile",{}).get("name","Client")
        mtype = msg.get("type")
        tok   = cfg("WHATSAPP_TOKEN")

        # ---- AUDIO ----
        if mtype == "audio":
            wa_text(tel, "Message vocal recu, transcription en cours...")
            mid = msg.get("audio",{}).get("id")
            if not mid:
                wa_text(tel, "Impossible de traiter ce vocal. Merci d'ecrire votre demande.")
                return jsonify({"status":"ok"}), 200
            h = {"Authorization": f"Bearer {tok}"}
            ru = requests.get(f"https://graph.facebook.com/v20.0/{mid}", headers=h, timeout=10)
            if ru.status_code != 200:
                wa_text(tel, "Erreur audio. Appelez le 0523303194.")
                return jsonify({"status":"ok"}), 200
            ra = requests.get(ru.json().get("url"), headers=h, timeout=20)
            transcrit = groq_whisper(ra.content)
            if not transcrit:
                wa_text(tel, "Transcription impossible. Merci d'ecrire votre demande.")
                return jsonify({"status":"ok"}), 200
            wa_text(tel, f"J'ai entendu : \"{transcrit}\"")
            texte = transcrit

        # ---- IMAGE ----
        elif mtype == "image":
            wa_text(tel, "Photo recue, analyse en cours...")
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

        # ---- BOUTON ----
        elif mtype == "interactive":
            br  = msg.get("interactive",{}).get("button_reply",{})
            bid = br.get("id","")
            texte = br.get("title","")
            sess = get_sess(tel)

            if bid == "btn_vehicules":
                wa_menu_veh(tel); return jsonify({"status":"ok"}), 200
            elif bid == "btn_sav":
                reset_flow(sess)
                wa_text(tel, "Pour votre rendez-vous atelier :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\nSouhaitez-vous egalement laisser vos coordonnees pour qu'un conseiller vous rappelle ?")
                wa_btns(tel, "Laisser mes coordonnees ?",
                    [{"id":"btn_sav_oui","title":"Oui, me rappeler"},
                     {"id":"btn_sav_non","title":"Non, merci"}])
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_sav_oui":
                reset_flow(sess); sess["flow"] = "sav"; sess["step"] = 1
                wa_text(tel, "Votre prenom, s'il vous plait ?"); return jsonify({"status":"ok"}), 200
            elif bid == "btn_sav_non":
                reset_flow(sess)
                wa_text(tel, "Tres bien. N'hesitez pas si vous avez besoin d'aide. Merci pour votre confiance.")
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_autre":
                wa_menu_autre(tel); return jsonify({"status":"ok"}), 200
            elif bid == "btn_vn":
                reset_flow(sess)
                wa_text(tel, CATALOGUE + "\n\nPour un tarif personnalise, notre conseiller vous contactera.\nPuis-je noter votre prenom ?")
                sess["flow"] = "vn"; sess["step"] = 1; return jsonify({"status":"ok"}), 200
            elif bid == "btn_vo":
                reset_flow(sess)
                wa_text(tel, "Stock occasion : https://top-auto.ma/Voitures_occasion\n\nPour une mise en relation conseiller VO, puis-je noter votre prenom ?")
                sess["flow"] = "vo"; sess["step"] = 1; return jsonify({"status":"ok"}), 200
            elif bid == "btn_essai":
                reset_flow(sess); sess["flow"] = "essai"; sess["step"] = 1
                wa_text(tel, "Votre prenom, s'il vous plait ?"); return jsonify({"status":"ok"}), 200
            elif bid == "btn_facture":
                reset_flow(sess); sess["flow"] = "facture"; sess["step"] = 1
                wa_text(tel, "Quel type de facture ?\n\n1. Achat vehicule (VN/VO)\n2. Atelier mecanique\n3. Carrosserie\n4. Pieces de rechange")
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_mainlevee":
                reset_flow(sess)
                wa_text(tel,
                    "Pour votre demande de mainlevee, presentez-vous en concession avec :\n\n"
                    "• Copie de la CIN\n"
                    "• Copie de la carte grise\n"
                    "• Releve bancaire cachete (dernier prelevement RCI Finance)\n"
                    "• Justificatif de paiement de la valeur residuelle (si applicable)\n\n"
                    "Souhaitez-vous qu'un conseiller vous contacte pour preparer votre dossier ?")
                wa_btns(tel, "Etre rappele par un conseiller ?",
                    [{"id":"btn_ml_oui","title":"Oui, me rappeler"},
                     {"id":"btn_ml_non","title":"Non, merci"}])
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_ml_oui":
                reset_flow(sess); sess["flow"] = "mainlevee"; sess["step"] = 1
                wa_text(tel, "Votre prenom ?"); return jsonify({"status":"ok"}), 200
            elif bid == "btn_ml_non":
                reset_flow(sess)
                wa_text(tel, "D'accord. N'hesitez pas si vous avez des questions. Merci pour votre confiance.")
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_reclamation":
                reset_flow(sess); sess["flow"] = "reclamation"; sess["step"] = 1
                wa_text(tel, "Je suis desole d'apprendre ce probleme. Votre satisfaction est notre priorite.\n\nVotre prenom, s'il vous plait ?")
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_rdv_sav":
                wa_text(tel, "Pour votre rendez-vous :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\nMerci pour votre confiance.")
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_autre_q":
                wa_text(tel, "Je suis a votre ecoute. Comment puis-je vous aider ? Merci pour votre confiance.")
                return jsonify({"status":"ok"}), 200
        else:
            return jsonify({"status":"ok"}), 200

        if not texte:
            return jsonify({"status":"ok"}), 200

        print(f"\n[MSG] {tel} ({nom}): {texte[:60]}")
        sess = get_sess(tel)

        tl = texte.lower().strip()
        if any('\u0600' <= c <= '\u06FF' for c in texte):
            sess["langue"] = "AR"
        elif any(w in tl for w in ["bghit","wach","safi","3afak","chokran","labas","mzyan","iyeh","wah","daba","3ndkm"]):
            sess["langue"] = "DARIJA"

        # FLUX ACTIF
        if sess.get("flow"):
            rep, done = traiter_flow(sess, tel, nom, texte)
            if rep:
                sess["hist"].append({"role":"user","content":texte})
                sess["hist"].append({"role":"assistant","content":rep})
                if len(sess["hist"]) > 10:
                    sess["hist"] = sess["hist"][-10:]
                wa_text(tel, rep)
                return jsonify({"status":"ok"}), 200

        # SALUTATION INITIALE
        saluts = ["bonjour","salam","salut","hi","hello","bonsoir","مرحبا","السلام",
                  "ahlan","bjr","bsr","coucou","sbah","msa","slm","labas","la bas"]
        mots = tl.split()
        if not sess["hist"] and len(mots) <= 4 and any(s in tl for s in saluts):
            wa_bienvenue(tel)
            return jsonify({"status":"ok"}), 200

        # TEXTES DE BOUTONS
        if tl in ["vehicules","véhicules"]:
            wa_menu_veh(tel); return jsonify({"status":"ok"}), 200
        if tl in ["autre demande","autre"]:
            wa_menu_autre(tel); return jsonify({"status":"ok"}), 200
        if tl in ["sav & atelier","sav","sav &amp; atelier"]:
            wa_text(tel, "Pour votre RDV atelier :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\nMerci pour votre confiance.")
            return jsonify({"status":"ok"}), 200

        # DETECTION DIRECTE
        intent = detecter_intent_direct(texte)
        if intent == "PRIX":
            wa_text(tel, "Pour le meilleur tarif personnalise et verifier la disponibilite, notre equipe commerciale vous contactera.\n\nPuis-je noter votre prenom et telephone ?")
            reset_flow(sess); sess["flow"] = "vn"; sess["step"] = 1
            return jsonify({"status":"ok"}), 200
        if intent == "FAQ_HORAIRE":
            wa_text(tel, "Horaires d'ouverture :\n\n• Lundi - Vendredi : 8h00 - 18h30\n• Samedi : 8h30 - 15h00\n• Dimanche : Ferme\n\nMerci pour votre confiance.")
            return jsonify({"status":"ok"}), 200
        if intent == "FAQ_ADRESSE":
            wa_text(tel, "Nous sommes situes au :\nQ.I Bd Sidi Mohamed Ben Abdellah, 208000 Mohammedia\n\nGPS : https://maps.google.com/?q=33.683384,-7.409769\n\nMerci pour votre confiance.")
            return jsonify({"status":"ok"}), 200
        if intent == "FAQ_TEL":
            wa_text(tel, "Nos numeros :\n• Renault : 0523303194\n• Dacia : 0523303195\n• Email : contact@top-auto.ma\n\nMerci pour votre confiance.")
            return jsonify({"status":"ok"}), 200
        if intent == "FAQ_SUIVI":
            wa_text(tel, "Pour l'avancement des travaux, suivi commande ou reception pieces, contactez le 0523303194. Un conseiller vous repondra rapidement.\n\nMerci pour votre confiance.")
            return jsonify({"status":"ok"}), 200

        # DETECTION FLUX PAR MOTS-CLES
        if any(w in tl for w in ["essai","test drive","tester","conduire","essayer"]):
            reset_flow(sess); sess["flow"] = "essai"; sess["step"] = 1
            wa_text(tel, "Votre prenom, s'il vous plait ?"); return jsonify({"status":"ok"}), 200

        if any(w == "rdi" for w in tl.split()) or any(w in tl for w in ["recepisse","récépissé","recepisse de depot","depot immatriculation"]):
            reset_flow(sess); sess["flow"] = "rdi"; sess["step"] = 1
            wa_text(tel, "Votre vehicule a-t-il ete livre il y a plus de 30 jours ? (Oui / Non)")
            return jsonify({"status":"ok"}), 200

        if any(w in tl for w in ["facture","reçu","recu"]):
            reset_flow(sess); sess["flow"] = "facture"; sess["step"] = 1
            wa_text(tel, "Quel type de facture ?\n\n1. Achat vehicule (VN/VO)\n2. Atelier mecanique\n3. Carrosserie\n4. Pieces de rechange")
            return jsonify({"status":"ok"}), 200

        if any(w in tl for w in ["mainlevee","mainlevée","main levee"]):
            reset_flow(sess)
            wa_text(tel,
                "Pour votre demande de mainlevee, presentez-vous en concession avec :\n\n"
                "• Copie de la CIN\n• Copie de la carte grise\n"
                "• Releve bancaire cachete (dernier prelevement RCI Finance)\n"
                "• Justificatif valeur residuelle (si applicable)\n\n"
                "Souhaitez-vous etre rappele par un conseiller ?")
            wa_btns(tel, "Etre rappele ?",
                [{"id":"btn_ml_oui","title":"Oui, me rappeler"},
                 {"id":"btn_ml_non","title":"Non, merci"}])
            return jsonify({"status":"ok"}), 200

        if any(w in tl for w in ["reclamation","réclamation","plainte","probleme","insatisfait"]):
            reset_flow(sess); sess["flow"] = "reclamation"; sess["step"] = 1
            wa_text(tel, "Je suis desole d'apprendre ce probleme. Votre satisfaction est notre priorite.\n\nVotre prenom, s'il vous plait ?")
            return jsonify({"status":"ok"}), 200

        if any(w in tl for w in ["rdv","rendez-vous","rendez vous","atelier","reparation","entretien"]):
            wa_text(tel, "Pour votre rendez-vous atelier :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\nUn conseiller vous confirmera rapidement.\n\nMerci pour votre confiance.")
            return jsonify({"status":"ok"}), 200

        if any(w in tl for w in ["occasion","d'occasion"]) and "vehicule" not in tl and "voiture" not in tl:
            reset_flow(sess)
            wa_text(tel, "Stock occasion : https://top-auto.ma/Voitures_occasion\n\nPour un conseiller VO, puis-je noter votre prenom ?")
            sess["flow"] = "vo"; sess["step"] = 1; return jsonify({"status":"ok"}), 200

        # TEXTE COURT SANS FLUX (prenom probable apres redemarrage)
        if not sess.get("flow") and len(mots) <= 2 and tl.replace(" ","").isalpha() and not sess["hist"]:
            wa_bienvenue(tel)
            return jsonify({"status":"ok"}), 200

        # APPEL GROQ pour questions generales
        try:
            rep = groq_general(sess["hist"], texte)
            rep = rep.strip()
            if not rep:
                rep = "Je n'ai pas bien compris. Pouvez-vous reformuler ? Merci pour votre confiance."
        except Exception as e:
            print(f"[GROQ ERR] {e}")
            rep = "Une erreur technique est survenue. Contactez-nous au 0523303194. Merci pour votre confiance."

        sess["hist"].append({"role":"user","content":texte})
        sess["hist"].append({"role":"assistant","content":rep})
        if len(sess["hist"]) > 10:
            sess["hist"] = sess["hist"][-10:]

        # Si Groq suggere un rappel conseiller → demarrer flux vn pour collecter prenom/tel
        if any(w in rep.lower() for w in ["tapez votre prenom","souhaitez-vous etre rappele"]) and not sess.get("flow"):
            sess["flow"] = "vn"
            sess["step"] = 1

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
