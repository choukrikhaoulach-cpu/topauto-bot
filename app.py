# -*- coding: utf-8 -*-
"""
TopAuto Mohammedia — WhatsApp Bot v3.0
Architecture : Flask + Machines à états + Groq LLM + Google Sheets
Cahier des charges : PFE Khaoula Choukri
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
        print(f"[SHEET] {sn} id={'OK' if sid else 'VIDE'}")
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
        print(f"[SHEETS] ERR: {e}")
        return None

def enregistrer(tel, langue, data):
    try:
        svc = gsheets()
        if not svc:
            return False
        t = data.get("type", "vn").lower()
        sid, sn = get_sheet(t)
        if not sid:
            print(f"[SHEETS] ID vide type={t}")
            return False
        now = datetime.now()
        res = svc.spreadsheets().values().get(spreadsheetId=sid, range=f"{sn}!A:N").execute()
        rows = res.get("values", [])
        idx = next((i+1 for i, r in enumerate(rows) if len(r) > 11 and r[11] == tel), None)

        if t == "essai":
            # Schema Essais_VN: ID|Date|Prenom|Nom|Tel|Modele|Marque|Ville|DateRDV|Statut|Resultat|telWA|Langue
            row = [
                now.strftime("%Y%m%d%H%M%S"), now.strftime("%d/%m/%Y %H:%M"),
                data.get("prenom",""), data.get("nom",""), data.get("tel",""),
                data.get("modele",""), "", data.get("ville",""),
                data.get("date_essai",""), "NOUVEAU", "", tel, langue
            ]
        else:
            # Schema générique: ID|Date|Prenom|Nom|Tel|Chassis|TypeFacture|Motif|Statut|DateEnvoi|Agent|telWA|Langue|Type
            row = [
                now.strftime("%Y%m%d%H%M%S"), now.strftime("%d/%m/%Y %H:%M"),
                data.get("prenom",""), data.get("nom",""), data.get("tel",""),
                data.get("chassis",""),
                data.get("type_facture",""),
                data.get("description", data.get("reclamation", data.get("modele",""))),
                "NOUVEAU", "", "WhatsApp Bot",
                tel, langue, t,
            ]

        if idx:
            svc.spreadsheets().values().update(
                spreadsheetId=sid, range=f"{sn}!A{idx}:N{idx}",
                valueInputOption="USER_ENTERED", body={"values": [row]}).execute()
            print(f"[SHEETS] MAJ {sn} L{idx}")
        else:
            svc.spreadsheets().values().append(
                spreadsheetId=sid, range=f"{sn}!A:N",
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
        res = svc.spreadsheets().values().get(spreadsheetId=sid, range="RDI_Immatriculation!A:P").execute()
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
SESSION_TIMEOUT = 1800  # 30 min

def get_sess(tel):
    now = time.time()
    if tel in sessions and now - sessions[tel].get("last", 0) > SESSION_TIMEOUT:
        del sessions[tel]
    if tel not in sessions:
        sessions[tel] = {"hist": [], "langue": "FR", "flow": None, "step": 0, "infos": {}, "last": now}
    sessions[tel]["last"] = now
    return sessions[tel]

def reset_flow(sess):
    sess["flow"] = None
    sess["step"] = 0
    sess["infos"] = {}

# ============================================================
# UTILITAIRES
# ============================================================
def valider_tel(t):
    t = t.replace(" ","").replace("-","").replace(".","")
    return bool(re.match(r'^(212[567]\d{8}|0[567]\d{8})$', t))

def valider_chassis(ch):
    return len(ch.replace(" ","")) >= 11

def valider_cin(cin):
    return bool(re.match(r'^[A-Za-z]{1,2}[0-9]{4,8}$', cin.strip()))

def nettoyer(val):
    val = re.sub(r'[Mm]erci pour votre confiance\.?', '', val).strip()
    val = re.sub(r'[Cc]hokran.*', '', val).strip()
    return val.strip('. \n')

def is_refus(tl):
    mots = tl.lower().strip().split()
    return any(w in mots for w in ["non","no","la","pas"]) or \
           any(w in tl.lower() for w in ["pas besoin","non merci","bghit la","no thanks"])

def is_oui(tl):
    return any(w in tl.lower() for w in ["oui","yes","wah","iyeh","safi","ok","correct","parfait","confirme","d'accord","mzyan","ouai"])

# ============================================================
# CATALOGUE
# ============================================================
CATALOGUE = """GAMME DACIA — VEHICULES NEUFS
------------------------------
Spring electrique : Batterie 24,3kWh | 70/100ch | AC 7kW / DC 40kW | Coffre 308L | Essential/Extreme
Sandero Streetway 2026 : Ecran 10" | SCe65/TCe100/dCi102ch | Essential→Journey
Sandero Stepway : Garde au sol 17cm | TCe100/dCi102ch/CVT | Essential→Extreme
Logan : Coffre 528L | SCe65/TCe100/dCi102ch | Essential→Journey
Jogger 5/7pl : Coffre 1807L | TCe100/dCi102ch/HEV140ch auto | Essential→Extreme
Duster 2025 : Media Nav 8"| CarPlay | dCi115/TCe130ch | Essential→Extreme
Bigster 2025 : +23cm vs Duster | Toit pano | dCi115/HEV155ch auto | Essential→Journey

GAMME RENAULT VP — VEHICULES NEUFS
------------------------------------
Clio 5 Ph2 : TCe100/dCi115/ETech145ch auto | Equilibre→Esprit Alpine
Clio 6 : Design repense | TCe100/ETech145ch | Equilibre→Esprit Alpine
Captur : OpenR Link | Google | Ecran10" | TCe100CVT/ETech145ch | Equilibre→Esprit Alpine
R5 ETech electrique : 40kWh120ch ou 52kWh150ch | 400km | DC100kW | Evolution→Esprit Alpine
Express : diesel 95/115ch
Megane Sedan : Coffre 475L | dCi115ch | Equilibre→Esprit Alpine
Megane ETech electrique : 60kWh | 450km | DC130kW | 220ch | Google | Ecran12" | Equilibre→Iconic
Arkana : ETech145ch | 4,5L/100km | Techno/Esprit Alpine
Austral : ETech200ch | OpenR Link | Google | 4,5L/100km | Techno/Esprit Alpine
Kardian SOMACA : Camera360 | TCe100CVT/dCi102ch | Equilibre/Techno

GAMME RENAULT VU
-----------------
Express Van : 800kg | 3,3m3 | dCi75ch
Trafic : 1400kg | L1/L2 H1/H2 | dCi150ch | Combi9pl
Master : 1700kg | 8-17m3 | dCi145/180ch"""

ETABLISSEMENT = """TopAuto Mohammedia — Concessionnaire agree Renault & Dacia
Adresse : Q.I Bd Sidi Mohamed Ben Abdellah, 208000 Mohammedia
Tel Renault : 0523303194 | Tel Dacia : 0523303195 | Email : contact@top-auto.ma
GPS : 33.683384 N, 7.409769 W | Maps : https://maps.google.com/?q=33.683384,-7.409769
Horaires : Lun-Ven 8h00-18h30 | Sam 8h30-15h00 | Dim Ferme
Facebook : @topauto | Instagram : @top_auto_mohammedia"""

# ============================================================
# GROQ
# ============================================================
SYSTEM_PROMPT = """Tu es l'Assistant Virtuel officiel de TopAuto Mohammedia, concessionnaire agree Renault et Dacia.

REGLES ABSOLUES :
1. JAMAIS de prix, tarifs, mensualites — orienter vers conseiller
2. Repondre DIRECTEMENT sans introduction
3. Aucun emoji
4. Terminer par : Merci pour votre confiance.
5. Repondre dans la langue du client (FR / AR / Darija)
6. Pour vehicules : infos techniques detaillees (moteurs, finitions, equipements)
7. Pour voiture familiale : recommander Logan, Jogger, Megane Sedan, Duster
8. Pour SUV : Duster, Bigster, Captur, Kardian, Arkana, Austral
9. IMPORTANT — Si le client demande RDI / recepisse / immatriculation / carte grise en attente → repondre UNIQUEMENT : ##RDI##
10. IMPORTANT — Si le client demande essai / test drive / tester un vehicule → repondre UNIQUEMENT : ##ESSAI##
11. IMPORTANT — Si le client demande facture / recu → repondre UNIQUEMENT : ##FACTURE##
12. IMPORTANT — Si le client demande reclamation / plainte / probleme → repondre UNIQUEMENT : ##RECLAMATION##
13. IMPORTANT — Si le client demande mainlevee → repondre UNIQUEMENT : ##MAINLEVEE##
14. IMPORTANT — Si le client demande prix / tarif / combien → repondre UNIQUEMENT : ##PRIX##

CATALOGUE :
""" + CATALOGUE + """

ETABLISSEMENT :
""" + ETABLISSEMENT

def groq_chat(hist, texte):
    key = cfg("GROQ_API_KEY")
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + hist[-6:] + [{"role": "user", "content": texte}]
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "llama-3.3-70b-versatile", "messages": msgs, "max_tokens": 600, "temperature": 0.15},
        timeout=30)
    print(f"[GROQ] {r.status_code}")
    if r.status_code != 200:
        raise Exception(f"Groq {r.status_code}: {r.text[:100]}")
    return r.json()["choices"][0]["message"]["content"]

def groq_vision(b64, mime):
    key = cfg("GROQ_API_KEY")
    prompt = "Expert auto TopAuto Mohammedia. Analyse image: 1-Probleme visible 2-Classification(carrosserie/mecanique/electronique/pneu/autre) 3-Gravite(faible/modere/urgent) 4-Recommandation. Francais concis. Termine: Merci pour votre confiance."
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "meta-llama/llama-4-scout-17b-16e-instruct",
              "messages": [{"role": "user", "content": [
                  {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                  {"type": "text", "text": prompt}]}],
              "max_tokens": 400}, timeout=30)
    if r.status_code != 200:
        return "Impossible d'analyser cette image. Presentez-vous en atelier pour un diagnostic. Merci pour votre confiance."
    return r.json()["choices"][0]["message"]["content"]

def groq_whisper(audio):
    key = cfg("GROQ_API_KEY")
    r = requests.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {key}"},
        files={"file": ("a.ogg", audio, "audio/ogg")},
        data={"model": "whisper-large-v3", "language": "fr", "response_format": "text"},
        timeout=30)
    if r.status_code != 200 or not r.text.strip():
        return None
    return r.text.strip()

# ============================================================
# WHATSAPP
# ============================================================
def wa_tok(): return cfg("WHATSAPP_TOKEN")
def wa_pid(): return cfg("PHONE_NUMBER_ID", PHONE_NUMBER_ID)
def wa_con(): return cfg("CONSEILLER_WHATSAPP", CONSEILLER_TEL)

def wa_text(tel, msg):
    r = requests.post(
        f"https://graph.facebook.com/v20.0/{wa_pid()}/messages",
        headers={"Authorization": f"Bearer {wa_tok()}", "Content-Type": "application/json"},
        json={"messaging_product": "whatsapp", "to": tel, "type": "text", "text": {"body": msg}},
        timeout=10)
    print(f"[WA] text {r.status_code}")
    return r.status_code == 200

def wa_btns(tel, body, btns):
    r = requests.post(
        f"https://graph.facebook.com/v20.0/{wa_pid()}/messages",
        headers={"Authorization": f"Bearer {wa_tok()}", "Content-Type": "application/json"},
        json={"messaging_product": "whatsapp", "to": tel, "type": "interactive",
              "interactive": {"type": "button", "body": {"text": body},
                "action": {"buttons": [{"type": "reply", "reply": {"id": b["id"], "title": b["title"]}} for b in btns[:3]]}}},
        timeout=10)
    print(f"[WA] btns {r.status_code}")
    return r.status_code == 200

def wa_bienvenue(tel):
    wa_btns(tel,
        "Bonjour et bienvenue chez TopAuto Mohammedia, concessionnaire agree Renault et Dacia.\n\n"
        "Je suis l'Assistant Virtuel, disponible 24/7 pour vous accompagner :\n"
        "- Vehicules Renault et Dacia (neufs et occasion)\n"
        "- Entretien et reparations\n"
        "- Pieces de rechange et carrosserie\n"
        "- Demandes administratives\n"
        "- Rendez-vous apres-vente\n\n"
        "Comment puis-je vous aider aujourd'hui ?",
        [{"id":"btn_vehicules","title":"Vehicules"},
         {"id":"btn_sav","title":"SAV & Atelier"},
         {"id":"btn_autre","title":"Autre demande"}])

def wa_menu_veh(tel):
    wa_btns(tel, "Quelle gamme vous interesse ?",
        [{"id":"btn_vn","title":"Vehicules Neufs"},
         {"id":"btn_vo","title":"Vehicules Occasion"},
         {"id":"btn_essai","title":"Essai Gratuit"}])

def wa_menu_autre(tel):
    wa_btns(tel, "Quelle est votre demande ?",
        [{"id":"btn_facture","title":"Demande Facture"},
         {"id":"btn_mainlevee","title":"Mainlevee"},
         {"id":"btn_reclamation","title":"Reclamation"}])

def notifier(tel, nom_wa, data):
    t = data.get("type","vn")
    _, sn = get_sheet(t)
    lignes = [f"--- NOUVEAU : {sn} ---", f"WA : {tel}", f"Nom WA : {nom_wa}"]
    for k,l in [("prenom","Prenom"),("nom","Nom"),("tel","Tel"),("modele","Modele"),
                ("ville","Ville"),("chassis","Chassis"),("cin","CIN"),("rc","RC"),
                ("type_facture","Type facture"),("reclamation","Reclamation"),
                ("description","Desc"),("date_essai","Date essai")]:
        if data.get(k): lignes.append(f"{l} : {data[k]}")
    lignes.append(f"Statut : {'URGENT 48h' if t=='reclamation' else 'A RAPPELER'}")
    wa_text(wa_con(), "\n".join(lignes))

def recap(data):
    t = "Recapitulatif de votre demande :\n"
    for k,l in [("prenom","Prenom"),("nom","Nom"),("tel","Telephone"),
                ("modele","Modele"),("ville","Ville"),("date_essai","Date souhaitee"),
                ("chassis","Chassis"),("cin","CIN"),("rc","RC"),
                ("type_facture","Type facture"),("reclamation","Reclamation")]:
        v = data.get(k,"")
        if v and v not in ["X","","null","?"]:
            t += f"- {l} : {v}\n"
    t += "\nCes informations sont-elles correctes ? (Oui / Non)"
    return t

# ============================================================
# MACHINES A ETATS — logique métier pure
# ============================================================
def demarrer_flux(sess, flow, question_initiale):
    reset_flow(sess)
    sess["flow"] = flow
    sess["step"] = 1
    return question_initiale

def traiter_flow(sess, tel, nom, texte):
    flow = sess["flow"]
    step = sess["step"]
    infos = sess["infos"]
    tl = texte.strip()
    print(f"[FLOW] {flow} step={step}")

    # ==== ESSAI VN ====
    if flow == "essai":
        if step == 1:
            if is_refus(tl): reset_flow(sess); return "Tres bien. Merci pour votre confiance.", True
            infos["prenom"] = nettoyer(tl); sess["step"] = 2
            return "Votre nom ?", False
        elif step == 2:
            infos["nom"] = nettoyer(tl); sess["step"] = 3
            return "Votre numero de telephone ?", False
        elif step == 3:
            if not valider_tel(tl): return "Numero invalide (ex: 0612345678).", False
            infos["tel"] = nettoyer(tl); sess["step"] = 4
            return "Quel modele souhaitez-vous essayer ?", False
        elif step == 4:
            infos["modele"] = nettoyer(tl); sess["step"] = 5
            return "Dans quelle ville ?", False
        elif step == 5:
            infos["ville"] = nettoyer(tl); sess["step"] = 6
            return "Date souhaitee pour l'essai ? (ex: 15/06/2026 ou 'des que possible')", False
        elif step == 6:
            infos["date_essai"] = nettoyer(tl) if tl.lower() not in ["non","no","la","pas"] else "Des que possible"
            sess["step"] = 7
            return recap(infos), False
        elif step == 7:
            if is_oui(tl):
                ok = enregistrer(tel, sess["langue"], {**infos, "type":"essai"})
                notifier(tel, nom, {**infos, "type":"essai"})
                reset_flow(sess)
                msg = "Votre demande d'essai a bien ete enregistree. Notre equipe vous contactera tres prochainement pour confirmer."
                if not ok: msg += "\n(Note: incident technique lors de l'enregistrement)"
                return msg + "\n\nMerci pour votre confiance.", True
            elif is_refus(tl):
                sess["step"] = 8
                return "Quelle information modifier ? (prenom/nom/telephone/modele/ville/date)", False
            else:
                return "Repondez Oui ou Non.\n\n" + recap(infos), False
        elif step == 8:
            tll = tl.lower()
            if "prenom" in tll: infos.pop("prenom",None); sess["step"]=1; return "Votre prenom ?", False
            elif "nom" in tll: infos.pop("nom",None); sess["step"]=2; return "Votre nom ?", False
            elif "tel" in tll or "telephone" in tll: infos.pop("tel",None); sess["step"]=3; return "Votre telephone ?", False
            elif "modele" in tll: infos.pop("modele",None); sess["step"]=4; return "Quel modele ?", False
            elif "ville" in tll: infos.pop("ville",None); sess["step"]=5; return "Quelle ville ?", False
            elif "date" in tll: infos.pop("date_essai",None); sess["step"]=6; return "Quelle date ?", False
            else: return "Precisez : prenom, nom, telephone, modele, ville ou date.", False

    # ==== RDI ====
    elif flow == "rdi":
        if step == 1:
            if is_oui(tl): sess["step"]=2; return "Etes-vous un particulier ou une societe ?", False
            elif is_refus(tl):
                reset_flow(sess)
                return "Le delai de 30 jours n'est pas encore ecoule. Vous pourrez faire la demande RDI apres ce delai. Merci pour votre confiance.", True
            else: return "Votre vehicule a-t-il ete livre il y a plus de 30 jours ? (Oui / Non)", False
        elif step == 2:
            if any(w in tl.lower() for w in ["particulier","prive","individuel","personne"]):
                infos["type_client"]="particulier"; sess["step"]=3
            elif any(w in tl.lower() for w in ["societe","entreprise","ste","commerce"]):
                infos["type_client"]="societe"; sess["step"]=3
            else: return "Particulier ou societe ?", False
            return "Votre prenom ?", False
        elif step == 3:
            infos["prenom"]=nettoyer(tl); sess["step"]=4
            return "Votre numero de chassis (VIN) ?", False
        elif step == 4:
            ch=tl.replace(" ","")
            if not valider_chassis(ch): return "Chassis incomplet (min 11 caracteres).", False
            infos["chassis"]=ch.upper(); sess["step"]=5
            return ("Votre numero RC ?" if infos.get("type_client")=="societe" else "Votre numero de CIN ?"), False
        elif step == 5:
            if infos.get("type_client")=="societe":
                infos["rc"]=nettoyer(tl).upper()
            else:
                cin=nettoyer(tl).upper()
                if not valider_cin(cin): return "Format CIN invalide (ex: BE123456).", False
                infos["cin"]=cin
            sess["step"]=6; return "Votre numero de telephone ?", False
        elif step == 6:
            if not valider_tel(tl): return "Numero invalide (ex: 0612345678).", False
            infos["tel"]=nettoyer(tl); sess["step"]=7
            return recap(infos), False
        elif step == 7:
            if is_oui(tl):
                info_rdi = verifier_rdi(infos.get("chassis",""))
                if info_rdi is None:
                    rep = "Impossible d'acceder au systeme. Notre equipe vous contactera."
                    notifier(tel, nom, {**infos, "type":"rdi"})
                elif info_rdi.get("trouve"):
                    statut = info_rdi.get("statut","En cours")
                    date_d = info_rdi.get("date_dispo","")
                    rep = f"Resultat verification :\n- Chassis : {infos['chassis']}\n- Statut : {statut}"
                    if date_d: rep += f"\n- Date disponibilite : {date_d}"
                    rep += "\n\nPour info : 0523303194."
                else:
                    rep = f"Dossier chassis {infos['chassis']} pas encore enregistre. Notre equipe va verifier et vous contactera."
                    notifier(tel, nom, {**infos, "type":"rdi"})
                reset_flow(sess)
                return rep + "\n\nMerci pour votre confiance.", True
            elif is_refus(tl):
                sess["step"]=8; return "Quelle info modifier ? (prenom/chassis/cin/rc/telephone)", False
            else: return "Repondez Oui ou Non.\n\n" + recap(infos), False
        elif step == 8:
            tll=tl.lower()
            if "prenom" in tll: sess["step"]=3; return "Votre prenom ?", False
            elif "chassis" in tll: infos.pop("chassis",None); sess["step"]=4; return "Votre chassis ?", False
            elif "cin" in tll: infos.pop("cin",None); sess["step"]=5; return "Votre CIN ?", False
            elif "rc" in tll: infos.pop("rc",None); sess["step"]=5; return "Votre RC ?", False
            elif "tel" in tll or "telephone" in tll: infos.pop("tel",None); sess["step"]=6; return "Votre telephone ?", False
            else: return "Precisez : prenom, chassis, CIN, RC ou telephone.", False

    # ==== FACTURE ====
    elif flow == "facture":
        if step == 1:
            tll=tl.lower()
            if any(w in tll for w in ["vente","achat","neuf","occasion","vn","vo","1"]):
                infos["type_facture"]="Vente VN/VO"; infos["type"]="facture_vente"
            elif any(w in tll for w in ["mecanique","atelier","entretien","reparation","2"]):
                infos["type_facture"]="Mecanique"; infos["type"]="facture_mecanique"
            elif any(w in tll for w in ["carrosserie","peinture","3"]):
                infos["type_facture"]="Carrosserie"; infos["type"]="facture_carrosserie"
            elif any(w in tll for w in ["piece","rechange","accessoire","4"]):
                infos["type_facture"]="Pieces de rechange"; infos["type"]="facture_pieces"
            else:
                return "Quel type de facture ?\n1. Achat vehicule (VN/VO)\n2. Mecanique\n3. Carrosserie\n4. Pieces de rechange", False
            sess["step"]=2; return "Numero de chassis ou matricule ?", False
        elif step == 2:
            infos["chassis"]=nettoyer(tl).upper(); sess["step"]=3
            return "Prenom du titulaire ?", False
        elif step == 3:
            infos["prenom"]=nettoyer(tl); sess["step"]=4
            return "Nom du titulaire ?", False
        elif step == 4:
            infos["nom"]=nettoyer(tl); sess["step"]=5
            return "Votre numero de telephone ?", False
        elif step == 5:
            if not valider_tel(tl): return "Numero invalide (ex: 0612345678).", False
            infos["tel"]=nettoyer(tl); sess["step"]=6
            return recap(infos), False
        elif step == 6:
            if is_oui(tl):
                ok = enregistrer(tel, sess["langue"], infos)
                notifier(tel, nom, infos)
                reset_flow(sess)
                msg = f"Demande facture ({infos.get('type_facture','')}) enregistree. Notre equipe vous contactera."
                if not ok: msg += " (incident technique, un conseiller vous contactera)"
                return msg + "\n\nMerci pour votre confiance.", True
            elif is_refus(tl):
                sess["step"]=7; return "Quelle info modifier ? (type/chassis/prenom/nom/telephone)", False
            else: return "Oui ou Non ?\n\n" + recap(infos), False
        elif step == 7:
            tll=tl.lower()
            if "type" in tll: infos.pop("type_facture",None); infos.pop("type",None); sess["step"]=1; return "Quel type ?\n1.Vente\n2.Mecanique\n3.Carrosserie\n4.Pieces", False
            elif "chassis" in tll: sess["step"]=2; return "Chassis ?", False
            elif "prenom" in tll: sess["step"]=3; return "Prenom ?", False
            elif "nom" in tll: sess["step"]=4; return "Nom ?", False
            elif "tel" in tll or "telephone" in tll: sess["step"]=5; return "Telephone ?", False
            else: return "Precisez : type, chassis, prenom, nom ou telephone.", False

    # ==== RECLAMATION ====
    elif flow == "reclamation":
        if step == 1:
            infos["prenom"]=nettoyer(tl); sess["step"]=2; return "Votre nom ?", False
        elif step == 2:
            infos["nom"]=nettoyer(tl); sess["step"]=3; return "Votre telephone ?", False
        elif step == 3:
            if not valider_tel(tl): return "Numero invalide (ex: 0612345678).", False
            infos["tel"]=nettoyer(tl); sess["step"]=4
            return "Numero de chassis ou plaque (tapez 'non' si pas applicable) ?", False
        elif step == 4:
            if tl.lower() not in ["non","no","la","pas","n/a"]:
                infos["chassis"]=nettoyer(tl).upper()
            sess["step"]=5; return "Decrivez votre reclamation :", False
        elif step == 5:
            infos["reclamation"]=nettoyer(tl); infos["type"]="reclamation"; sess["step"]=6
            return recap(infos), False
        elif step == 6:
            if is_oui(tl):
                ok = enregistrer(tel, sess["langue"], infos)
                notifier(tel, nom, infos)
                reset_flow(sess)
                msg = "Reclamation enregistree et transmise au responsable qualite. Reponse sous 48h ouvrees."
                if not ok: msg += " (incident technique, un conseiller vous contactera)"
                return msg + "\n\nMerci pour votre confiance.", True
            elif is_refus(tl):
                sess["step"]=7; return "Quelle info modifier ? (prenom/nom/telephone/chassis/description)", False
            else: return "Oui ou Non ?\n\n" + recap(infos), False
        elif step == 7:
            tll=tl.lower()
            if "prenom" in tll: sess["step"]=1; return "Votre prenom ?", False
            elif "nom" in tll: sess["step"]=2; return "Votre nom ?", False
            elif "tel" in tll or "telephone" in tll: sess["step"]=3; return "Votre telephone ?", False
            elif "chassis" in tll: sess["step"]=4; return "Chassis ?", False
            elif "description" in tll or "reclamation" in tll: sess["step"]=5; return "Decrivez votre reclamation :", False
            else: return "Precisez l'info a modifier.", False

    # ==== SAV ====
    elif flow == "sav":
        if step == 1:
            if is_refus(tl): reset_flow(sess); return "Tres bien. RDV atelier : https://top-auto.ma/Entretienr%C3%A9paration\n\nMerci pour votre confiance.", True
            infos["prenom"]=nettoyer(tl); sess["step"]=2; return "Votre nom ?", False
        elif step == 2:
            infos["nom"]=nettoyer(tl); sess["step"]=3; return "Votre telephone ?", False
        elif step == 3:
            if not valider_tel(tl): return "Numero invalide.", False
            infos["tel"]=nettoyer(tl); infos["type"]="sav_atelier"; sess["step"]=4
            return recap(infos), False
        elif step == 4:
            if is_oui(tl):
                enregistrer(tel, sess["langue"], infos)
                notifier(tel, nom, infos)
                reset_flow(sess)
                return "RDV atelier : https://top-auto.ma/Entretienr%C3%A9paration\n\nVotre demande a ete transmise. Notre equipe vous contactera.\n\nMerci pour votre confiance.", True
            else: return recap(infos), False

    # ==== VN ====
    elif flow == "vn":
        if step == 1:
            if is_refus(tl): reset_flow(sess); return "Tres bien. Contactez-nous au 0523303194. Merci pour votre confiance.", True
            infos["prenom"]=nettoyer(tl); sess["step"]=2; return "Votre telephone ?", False
        elif step == 2:
            if not valider_tel(tl): return "Numero invalide.", False
            infos["tel"]=nettoyer(tl); infos["type"]="vn"
            enregistrer(tel, sess["langue"], infos)
            notifier(tel, nom, infos)
            reset_flow(sess)
            return "Merci ! Notre conseiller vous contactera avec le meilleur tarif personnalise.\n\nMerci pour votre confiance.", True

    # ==== VO ====
    elif flow == "vo":
        if step == 1:
            if is_refus(tl): reset_flow(sess); return "Tres bien. Stock occasion : https://top-auto.ma/Voitures_occasion\n\nMerci pour votre confiance.", True
            infos["prenom"]=nettoyer(tl); sess["step"]=2; return "Votre telephone ?", False
        elif step == 2:
            if not valider_tel(tl): return "Numero invalide.", False
            infos["tel"]=nettoyer(tl); infos["type"]="vo"
            enregistrer(tel, sess["langue"], infos)
            notifier(tel, nom, infos)
            reset_flow(sess)
            return "Merci ! Notre conseiller VO vous contactera.\nStock : https://top-auto.ma/Voitures_occasion\n\nMerci pour votre confiance.", True

    # ==== MAINLEVEE ====
    elif flow == "mainlevee":
        if step == 1:
            if is_refus(tl): reset_flow(sess); return "D'accord. Merci pour votre confiance.", True
            infos["prenom"]=nettoyer(tl); sess["step"]=2; return "Votre nom ?", False
        elif step == 2:
            infos["nom"]=nettoyer(tl); sess["step"]=3; return "Votre telephone ?", False
        elif step == 3:
            if not valider_tel(tl): return "Numero invalide.", False
            infos["tel"]=nettoyer(tl); sess["step"]=4; return "Votre numero de chassis ?", False
        elif step == 4:
            infos["chassis"]=nettoyer(tl).upper(); infos["type"]="mainlevee"; sess["step"]=5
            return recap(infos), False
        elif step == 5:
            if is_oui(tl):
                enregistrer(tel, sess["langue"], infos)
                notifier(tel, nom, infos)
                reset_flow(sess)
                return "Demande de mainlevee enregistree. Notre equipe SAV vous contactera sous 24-48h.\n\nMerci pour votre confiance.", True
            else: return recap(infos), False

    return None, False

# ============================================================
# DETECTION INTENTIONS
# ============================================================
def detecter_flux(tl):
    """Détecte l'intention du client par mots-clés — retourne le flux ou None"""
    # RDI — mots entiers uniquement pour eviter faux positifs (kardian, etc.)
    mots = tl.split()
    if any(w == "rdi" for w in mots) or \
       any(w in tl for w in ["recepisse","récépissé","depot immatriculation","carte grise en attente","autorisation provisoire"]):
        return "rdi"
    if any(w in tl for w in ["essai","test drive","tester un vehicule","essayer le","essayer la"]):
        return "essai"
    if any(w in tl for w in ["facture","reçu","recu"]):
        return "facture"
    if any(w in tl for w in ["mainlevee","mainlevée","main levee","main-levee"]):
        return "mainlevee"
    if any(w in tl for w in ["reclamation","réclamation","plainte","insatisfait"]):
        return "reclamation"
    if any(w in tl for w in ["rdv","rendez-vous","rendez vous"]) and \
       any(w in tl for w in ["atelier","reparation","entretien","mecanique"]):
        return "sav"
    if any(w in tl for w in ["occasion","d'occasion","vo"]) and \
       not any(w in tl for w in ["neuf","nouveau","vn"]):
        return "vo_info"
    return None

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
                wa_text(tel, "Impossible de traiter ce vocal. Merci d'ecrire.")
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
            h = {"Authorization": f"Bearer {tok}"}
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

            # Routing boutons par ID — priorité absolue
            btn_actions = {
                "btn_vehicules": lambda: (wa_menu_veh(tel), None),
                "btn_sav": lambda: (_sav_menu(tel, sess), None),
                "btn_sav_oui": lambda: (_start_flow(sess, tel, "sav"), None),
                "btn_sav_non": lambda: (wa_text(tel, "Tres bien. Merci pour votre confiance."), None),
                "btn_autre": lambda: (wa_menu_autre(tel), None),
                "btn_vn": lambda: (_start_vn(sess, tel), None),
                "btn_vo": lambda: (_start_vo(sess, tel), None),
                "btn_essai": lambda: (_start_flow(sess, tel, "essai"), None),
                "btn_facture": lambda: (_start_facture(sess, tel), None),
                "btn_mainlevee": lambda: (_mainlevee_menu(tel, sess), None),
                "btn_ml_oui": lambda: (_start_flow(sess, tel, "mainlevee"), None),
                "btn_ml_non": lambda: (wa_text(tel, "D'accord. Merci pour votre confiance."), None),
                "btn_reclamation": lambda: (_start_flow(sess, tel, "reclamation"), None),
                "btn_rdv_sav": lambda: (wa_text(tel, "RDV atelier :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\nMerci pour votre confiance."), None),
                "btn_autre_q": lambda: (wa_text(tel, "Je suis a votre ecoute. Merci pour votre confiance."), None),
            }
            if bid in btn_actions:
                btn_actions[bid]()
                return jsonify({"status":"ok"}), 200
        else:
            return jsonify({"status":"ok"}), 200

        if not texte:
            return jsonify({"status":"ok"}), 200

        print(f"\n[MSG] {tel} ({nom}): {texte[:60]}")
        sess = get_sess(tel)
        tl = texte.lower().strip()
        mots = tl.split()

        # Langue
        if any('\u0600' <= c <= '\u06FF' for c in texte):
            sess["langue"] = "AR"
        elif any(w in tl for w in ["bghit","wach","safi","3afak","chokran","labas","mzyan","iyeh","wah","daba","3ndkm"]):
            sess["langue"] = "DARIJA"

        # 1. FLUX ACTIF
        if sess.get("flow"):
            rep, done = traiter_flow(sess, tel, nom, texte)
            if rep:
                sess["hist"].append({"role":"user","content":texte})
                sess["hist"].append({"role":"assistant","content":rep})
                if len(sess["hist"]) > 10: sess["hist"] = sess["hist"][-10:]
                wa_text(tel, rep)
                return jsonify({"status":"ok"}), 200

        # 2. SALUTATION
        saluts = ["bonjour","salam","salut","hi","hello","bonsoir","مرحبا","السلام",
                  "ahlan","bjr","bsr","coucou","sbah","msa","slm","labas","la bas"]
        if not sess["hist"] and len(mots) <= 4 and any(s in tl for s in saluts):
            wa_bienvenue(tel)
            return jsonify({"status":"ok"}), 200

        # 3. TEXTES DE BOUTONS
        if tl in ["vehicules","véhicules"]: wa_menu_veh(tel); return jsonify({"status":"ok"}), 200
        if tl in ["autre demande","autre"]: wa_menu_autre(tel); return jsonify({"status":"ok"}), 200
        if tl in ["sav & atelier","sav"]:
            wa_text(tel, "RDV atelier :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\nMerci pour votre confiance.")
            return jsonify({"status":"ok"}), 200

        # 4. FAQ DIRECTES (sans LLM)
        if any(w in tl for w in ["horaire","heure","ouvert","ferme","ouverture"]):
            wa_text(tel, "Horaires :\n• Lun-Ven : 8h00-18h30\n• Samedi : 8h30-15h00\n• Dimanche : Ferme\n\nMerci pour votre confiance.")
            return jsonify({"status":"ok"}), 200
        if any(w in tl for w in ["adresse","localisation","situe","comment venir","gps"]):
            wa_text(tel, "Adresse : Q.I Bd Sidi Mohamed Ben Abdellah, 208000 Mohammedia\nGPS : https://maps.google.com/?q=33.683384,-7.409769\n\nMerci pour votre confiance.")
            return jsonify({"status":"ok"}), 200
        if any(w in tl for w in ["suivi","avancement","mes pieces","mes travaux","ma commande"]):
            wa_text(tel, "Pour le suivi travaux/commandes/pieces, contactez le 0523303194.\n\nMerci pour votre confiance.")
            return jsonify({"status":"ok"}), 200
        if any(w in tl for w in ["financement","credit","leasing","loa","mensualite"]) and \
           not any(w in tl for w in ["prix","tarif","combien"]):
            wa_text(tel, "Solutions de financement disponibles : Credit classique (12-72 mois), Financement ZEN, Easy Lease (LOA), Financement 0%.\n\nPour une simulation personnalisee, notre conseiller vous contactera.\nPuis-je noter votre prenom ?")
            reset_flow(sess); sess["flow"]="vn"; sess["step"]=1
            return jsonify({"status":"ok"}), 200

        # 5. DETECTION FLUX PAR MOTS-CLES
        flux = detecter_flux(tl)
        if flux == "rdi":
            reset_flow(sess); sess["flow"]="rdi"; sess["step"]=1
            wa_text(tel, "Votre vehicule a-t-il ete livre il y a plus de 30 jours ? (Oui / Non)")
            return jsonify({"status":"ok"}), 200
        elif flux == "essai":
            reset_flow(sess); sess["flow"]="essai"; sess["step"]=1
            wa_text(tel, "Votre prenom, s'il vous plait ?"); return jsonify({"status":"ok"}), 200
        elif flux == "facture":
            _start_facture(sess, tel); return jsonify({"status":"ok"}), 200
        elif flux == "mainlevee":
            _mainlevee_menu(tel, sess); return jsonify({"status":"ok"}), 200
        elif flux == "reclamation":
            _start_flow(sess, tel, "reclamation"); return jsonify({"status":"ok"}), 200
        elif flux == "sav":
            _sav_menu(tel, sess); return jsonify({"status":"ok"}), 200
        elif flux == "vo_info":
            _start_vo(sess, tel); return jsonify({"status":"ok"}), 200

        if any(w in tl for w in ["moins cher","pas cher","abordable","accessible","budget"]):
            wa_text(tel,
                "Nos modeles les plus accessibles :\n"
                "• Dacia Spring (electrique)\n"
                "• Dacia Sandero Streetway\n"
                "• Dacia Logan\n"
                "• Renault Express\n\n"
                "Pour les tarifs, notre conseiller vous contactera.\nPuis-je noter votre prenom ?")
            reset_flow(sess); sess["flow"]="vn"; sess["step"]=1
            return jsonify({"status":"ok"}), 200

        if any(w in tl for w in ["prix","tarif","combien","coute","coûte","thaman"]):
            wa_text(tel, "Pour le meilleur tarif personnalise, notre equipe commerciale vous contactera.\n\nPuis-je noter votre prenom ?")
            reset_flow(sess); sess["flow"]="vn"; sess["step"]=1
            return jsonify({"status":"ok"}), 200

        # 6. Texte court sans historique = possible prenom perdu
        if not sess["hist"] and len(mots) <= 2 and tl.replace(" ","").isalpha():
            wa_bienvenue(tel)
            return jsonify({"status":"ok"}), 200

        # 7. GROQ pour questions generales
        try:
            rep = groq_chat(sess["hist"], texte)
            rep = rep.strip()
            if not rep:
                rep = "Je n'ai pas bien compris. Pouvez-vous reformuler ? Merci pour votre confiance."
        except Exception as e:
            print(f"[GROQ ERR] {e}")
            rep = "Erreur technique. Contactez-nous au 0523303194. Merci pour votre confiance."

        # Intercepter tags Groq
        if "##RDI##" in rep:
            reset_flow(sess); sess["flow"]="rdi"; sess["step"]=1
            wa_text(tel, "Votre vehicule a-t-il ete livre il y a plus de 30 jours ? (Oui / Non)")
            return jsonify({"status":"ok"}), 200
        if "##ESSAI##" in rep:
            reset_flow(sess); sess["flow"]="essai"; sess["step"]=1
            wa_text(tel, "Votre prenom, s'il vous plait ?"); return jsonify({"status":"ok"}), 200
        if "##FACTURE##" in rep:
            _start_facture(sess, tel); return jsonify({"status":"ok"}), 200
        if "##RECLAMATION##" in rep:
            _start_flow(sess, tel, "reclamation"); return jsonify({"status":"ok"}), 200
        if "##MAINLEVEE##" in rep:
            _mainlevee_menu(tel, sess); return jsonify({"status":"ok"}), 200
        if "##PRIX##" in rep:
            wa_text(tel, "Pour le meilleur tarif personnalise, notre equipe commerciale vous contactera.\n\nPuis-je noter votre prenom ?")
            reset_flow(sess); sess["flow"]="vn"; sess["step"]=1
            return jsonify({"status":"ok"}), 200

        sess["hist"].append({"role":"user","content":texte})
        sess["hist"].append({"role":"assistant","content":rep})
        if len(sess["hist"]) > 10: sess["hist"] = sess["hist"][-10:]
        wa_text(tel, rep)
        return jsonify({"status":"ok"}), 200

    except Exception as e:
        print(f"[ERREUR] {e}")
        return jsonify({"status":"error"}), 200

# ============================================================
# HELPERS BOUTONS
# ============================================================
def _start_flow(sess, tel, flow):
    reset_flow(sess); sess["flow"]=flow; sess["step"]=1
    msgs = {
        "sav": "Votre prenom, s'il vous plait ?",
        "essai": "Votre prenom, s'il vous plait ?",
        "reclamation": "Je suis desole d'apprendre ce probleme. Votre satisfaction est notre priorite.\n\nVotre prenom ?",
        "mainlevee": "Votre prenom ?",
        "vn": "Votre prenom ?",
        "vo": "Votre prenom ?",
    }
    wa_text(tel, msgs.get(flow, "Votre prenom ?"))

def _start_vn(sess, tel):
    reset_flow(sess)
    wa_text(tel, CATALOGUE + "\n\nPour un tarif personnalise, notre conseiller vous contactera.\nPuis-je noter votre prenom ?")
    sess["flow"]="vn"; sess["step"]=1

def _start_vo(sess, tel):
    reset_flow(sess)
    wa_text(tel, "Stock occasion : https://top-auto.ma/Voitures_occasion\n\nPour une mise en relation avec un conseiller VO, puis-je noter votre prenom ?")
    sess["flow"]="vo"; sess["step"]=1

def _start_facture(sess, tel):
    reset_flow(sess); sess["flow"]="facture"; sess["step"]=1
    wa_text(tel, "Quel type de facture ?\n\n1. Achat vehicule (VN/VO)\n2. Atelier mecanique\n3. Carrosserie\n4. Pieces de rechange")

def _sav_menu(tel, sess):
    reset_flow(sess)
    wa_text(tel, "Pour votre rendez-vous atelier :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\nSouhaitez-vous aussi laisser vos coordonnees pour etre rappele ?")
    wa_btns(tel, "Laisser mes coordonnees ?",
        [{"id":"btn_sav_oui","title":"Oui, me rappeler"},
         {"id":"btn_sav_non","title":"Non, merci"}])

def _mainlevee_menu(tel, sess):
    reset_flow(sess)
    wa_text(tel,
        "Pour votre mainlevee, presentez-vous en concession avec :\n\n"
        "• Copie de la CIN\n"
        "• Copie de la carte grise\n"
        "• Releve bancaire cachete (dernier prelevement RCI Finance)\n"
        "• Justificatif paiement valeur residuelle (si applicable)\n\n"
        "Pour payer la valeur residuelle :\n"
        "RIB RCI Finance Maroc : 007 780 00000 054111 70005 29\n\n"
        "Souhaitez-vous etre rappele par un conseiller ?")
    wa_btns(tel, "Etre rappele ?",
        [{"id":"btn_ml_oui","title":"Oui, me rappeler"},
         {"id":"btn_ml_non","title":"Non, merci"}])

@app.route("/", methods=["GET"])
def home():
    return "TopAuto WhatsApp Bot v3.0 - Online", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[START] TopAuto Bot port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
