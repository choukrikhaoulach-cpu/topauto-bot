# -*- coding: utf-8 -*-
"""
TopAuto Mohammedia — WhatsApp Bot v4.0
Architecture : Groq pour classification d'intention + Machines à états pour logique métier
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

def sh_v(): return "174O6ts5GPlkafbjXOpCdmVoY0KFKPsSYXxHgfBLozu4"
def sh_f(): return "1wxWy1nXvgUC2341XuL6jQmIiEDLTbcyzHuuVpXcYfPU"
def sh_s(): return "1RyZpVGw1nur_UqQZ0LqOGYvJ-eAwNpBFrQ-_cX_utWA"

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
            return False
        now = datetime.now()
        res = svc.spreadsheets().values().get(spreadsheetId=sid, range=f"{sn}!A:N").execute()
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
                data.get("chassis",""), data.get("type_facture",""),
                data.get("description", data.get("reclamation", data.get("modele",""))),
                "NOUVEAU", "", "WhatsApp Bot", tel, langue, t,
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
        print(f"[SHEETS] ERR: {e}")
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
SESSION_TIMEOUT = 1800

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
    return any(w in tl.lower() for w in ["oui","yes","wah","iyeh","safi","ok","correct","parfait","confirme","d'accord","mzyan","ouai","ewa","na3m","نعم","ايه"])

def detect_langue(texte):
    if any('\u0600' <= c <= '\u06FF' for c in texte):
        tl = texte.lower()
        if any(w in tl for w in ["bghit","wach","safi","3afak","chokran","labas","mzyan","iyeh","wah","daba","3ndkm","wash","fach","mnin","kifach","bzzaf"]):
            return "DARIJA"
        return "AR"
    return "FR"

# ============================================================
# CATALOGUE & INFOS
# ============================================================
CATALOGUE = """GAMME DACIA :
- Spring : electrique 70/100ch | batterie 24,3kWh | autonomie 220km
- Sandero Streetway 2026 : essence/diesel | 65-102ch | ecran 10"
- Sandero Stepway : crossover | garde au sol 17cm | 100-102ch
- Logan : berline familiale | coffre 528L | 65-102ch
- Jogger : break 5/7 places | coffre 1807L | HEV 140ch disponible
- Duster 2025 : SUV | CarPlay | camera recul | 115-130ch
- Bigster 2025 : grand SUV | toit panoramique | HEV 155ch

GAMME RENAULT :
- Clio 5 Ph2 / Clio 6 : citadine | 100-145ch | hybride disponible
- Captur : SUV urbain | Google integre | ecran 10" | 100-145ch hybride
- R5 E-Tech : 100% electrique | 120-150ch | 400km autonomie
- Megane Sedan : berline | coffre 475L | diesel 115ch
- Megane E-Tech : electrique | 220ch | 450km | ecran 12"
- Arkana : coupe-SUV hybride | 145ch | 4,5L/100km
- Austral : SUV familial | 200ch hybride | Google | full digital
- Kardian : SUV compact | fabrique au Maroc SOMACA | camera 360

UTILITAIRES : Express Van, Trafic, Master"""

INFOS_CONCESSION = """TopAuto Mohammedia — Concessionnaire agree Renault & Dacia
Adresse : Q.I Bd Sidi Mohamed Ben Abdellah, 208000 Mohammedia
Tel : 0523303194 (Renault) | 0523303195 (Dacia)
Email : contact@top-auto.ma
Horaires : Lun-Ven 8h-18h30 | Sam 8h30-15h | Dim ferme
GPS : https://maps.google.com/?q=33.683384,-7.409769"""

# ============================================================
# GROQ — CLASSIFICATION D'INTENTION (appel rapide, max_tokens=30)
# ============================================================
PROMPT_CLASSIFIER = """Tu es un classificateur d'intention pour un chatbot d'une concession automobile.
Analyse le message et reponds UNIQUEMENT avec UN SEUL tag parmi :

##ESSAI## — demande d'essai / test drive / tester / conduire un vehicule
##RDI## — RDI / recepisse / immatriculation / carte grise en attente / depot dossier immat
##FACTURE## — facture / recu / ticket / duplicata facture
##MAINLEVEE## — mainlevee / lever le gage / fin de credit / remboursement credit auto
##RECLAMATION## — reclamation / plainte / probleme / insatisfait / mauvais service
##SAV## — rendez-vous atelier / reparation / entretien / vidange / pneus / SAV
##VN## — acheter vehicule neuf / informations vehicule neuf / tarif vehicule neuf
##VO## — vehicule occasion / voiture d'occasion / acheter occasion
##PRIX## — question sur le prix / tarif / combien / mensualite (peu importe la formulation)
##HORAIRES## — horaires / heures d'ouverture / quand ouvert
##ADRESSE## — adresse / localisation / ou se trouve / comment venir / gps
##TEL## — numero de telephone / contact / appeler la concession
##SUIVI## — suivi travaux / ma commande / mes pieces / avancement reparation
##SALUTATION## — bonjour / salam / salut / bonsoir (message de salutation uniquement)
##INFO_VEH## — question generale sur un vehicule (caracteristiques / moteur / dimensions / equipements)
##GENERAL## — toute autre question ne correspondant a aucun tag ci-dessus

IMPORTANT :
- Comprends le sens meme avec des fautes d'orthographe ou du darija
- "bmlus cher" = plus cher = ##PRIX##
- "bghit ndire essai" = essai = ##ESSAI##
- "fin kayn lmutur" = informations vehicule = ##INFO_VEH##
- "wash 3ndkum kardian" = informations vehicule = ##INFO_VEH##
- Reponds UNIQUEMENT le tag, rien d'autre"""

def classifier_intention(texte, langue):
    key = cfg("GROQ_API_KEY")
    msgs = [
        {"role": "system", "content": PROMPT_CLASSIFIER},
        {"role": "user", "content": texte}
    ]
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "llama-3.3-70b-versatile", "messages": msgs, "max_tokens": 20, "temperature": 0},
        timeout=15)
    if r.status_code != 200:
        print(f"[CLASSIFIER] ERR {r.status_code}")
        return "##GENERAL##"
    rep = r.json()["choices"][0]["message"]["content"].strip()
    print(f"[INTENT] {rep} | lang={langue}")
    # Extraire le tag
    for tag in ["##ESSAI##","##RDI##","##FACTURE##","##MAINLEVEE##","##RECLAMATION##",
                "##SAV##","##VN##","##VO##","##PRIX##","##HORAIRES##","##ADRESSE##",
                "##TEL##","##SUIVI##","##SALUTATION##","##INFO_VEH##","##GENERAL##"]:
        if tag in rep:
            return tag
    return "##GENERAL##"

# ============================================================
# GROQ — REPONSE GENERALE
# ============================================================
PROMPT_GENERAL = """Tu es l'Assistant Virtuel officiel de TopAuto Mohammedia, concessionnaire agree Renault et Dacia.

REGLES ABSOLUES :
1. JAMAIS de prix, tarifs, mensualites — si demande de prix dire : "Pour le meilleur tarif personnalise, notre conseiller vous contactera."
2. Repondre DIRECTEMENT sans introduction ni formule d'accueil
3. Pas d'emoji
4. Terminer par : Merci pour votre confiance.
5. Repondre dans la MEME langue que le client (FR=francais, AR=arabe, DARIJA=darija marocain)
6. Pour les vehicules : donner infos techniques completes (moteurs, finitions, dimensions, equipements)
7. Etre professionnel et chaleureux

CATALOGUE VEHICULES :
""" + CATALOGUE + """

INFOS CONCESSION :
""" + INFOS_CONCESSION

def groq_reponse(hist, texte, langue):
    key = cfg("GROQ_API_KEY")
    lang_rules = {
        "FR":     "OBLIGATOIRE : Reponds uniquement en francais.",
        "AR":     "إلزامي: أجب باللغة العربية الفصحى فقط.",
        "DARIJA": "مهم: خاصك تجاوب بالدارجة المغربية فقط.",
    }
    system = PROMPT_GENERAL + "\n\n" + lang_rules.get(langue, lang_rules["FR"])
    msgs = [{"role": "system", "content": system}] + hist[-6:] + [{"role": "user", "content": texte}]
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "llama-3.3-70b-versatile", "messages": msgs, "max_tokens": 600, "temperature": 0.2},
        timeout=30)
    print(f"[GROQ] {r.status_code} [{langue}]")
    if r.status_code != 200:
        raise Exception(f"Groq {r.status_code}")
    return r.json()["choices"][0]["message"]["content"]

def groq_vision(b64, mime):
    key = cfg("GROQ_API_KEY")
    prompt = "Expert auto TopAuto Mohammedia. Analyse cette image: 1-Probleme visible 2-Classification(carrosserie/mecanique/electronique/pneu) 3-Gravite(faible/modere/urgent) 4-Recommandation. Concis. Termine: Merci pour votre confiance."
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

def groq_whisper(audio):
    key = cfg("GROQ_API_KEY")
    r = requests.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {key}"},
        files={"file": ("a.ogg", audio, "audio/ogg")},
        data={"model": "whisper-large-v3", "response_format": "text"},
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
    print(f"[WA] text {r.status_code} | {r.text[:200]}")
    return r.status_code == 200

def wa_btns(tel, body, btns):
    payload = {"messaging_product": "whatsapp", "to": tel, "type": "interactive",
               "interactive": {"type": "button", "body": {"text": body},
                 "action": {"buttons": [{"type": "reply", "reply": {"id": b["id"], "title": b["title"]}} for b in btns[:3]]}}}
    r = requests.post(
        f"https://graph.facebook.com/v20.0/{wa_pid()}/messages",
        headers={"Authorization": f"Bearer {wa_tok()}", "Content-Type": "application/json"},
        json=payload, timeout=10)
    print(f"[WA] btns {r.status_code} | {r.text[:200]}")
    return r.status_code == 200

def wa_bienvenue(tel, langue="FR"):
    if langue in ["AR","DARIJA"]:
        body = ("مرحباً بك في TopAuto المحمدية، الوكيل المعتمد لرينو وداسيا.\n\n"
                "أنا المساعد الذكي، متاح 24/7 لمساعدتك في :\n"
                "- سيارات رينو وداسيا (جديدة ومستعملة)\n"
                "- الصيانة والإصلاحات\n"
                "- قطع الغيار والكاروسري\n"
                "- الطلبات الإدارية\n"
                "- مواعيد ما بعد البيع\n\nكيف يمكنني مساعدتك اليوم ؟")
        btns = [{"id":"btn_vehicules","title":"السيارات"},
                {"id":"btn_sav","title":"الورشة"},
                {"id":"btn_autre","title":"طلب آخر"}]
    else:
        body = ("Bonjour et bienvenue chez TopAuto Mohammedia, concessionnaire agree Renault et Dacia.\n\n"
                "Je suis l'Assistant Virtuel, disponible 24/7 pour vous accompagner :\n"
                "- Vehicules Renault et Dacia (neufs et occasion)\n"
                "- Entretien et reparations\n"
                "- Pieces de rechange et carrosserie\n"
                "- Demandes administratives\n"
                "- Rendez-vous apres-vente\n\nComment puis-je vous aider aujourd'hui ?")
        btns = [{"id":"btn_vehicules","title":"Vehicules"},
                {"id":"btn_sav","title":"SAV Atelier"},
                {"id":"btn_autre","title":"Autre demande"}]
    wa_btns(tel, body, btns)

def wa_menu_veh(tel, langue="FR"):
    if langue in ["AR","DARIJA"]:
        wa_btns(tel, "ما نوع السيارة التي تهمك ؟",
            [{"id":"btn_vn","title":"سيارات جديدة"},
             {"id":"btn_vo","title":"سيارات مستعملة"},
             {"id":"btn_essai","title":"تجربة مجانية"}])
    else:
        wa_btns(tel, "Quelle gamme vous interesse ?",
            [{"id":"btn_vn","title":"Vehicules Neufs"},
             {"id":"btn_vo","title":"Vehicules Occasion"},
             {"id":"btn_essai","title":"Essai Gratuit"}])

def wa_menu_autre(tel, langue="FR"):
    if langue in ["AR","DARIJA"]:
        wa_btns(tel, "ما هو طلبك ؟",
            [{"id":"btn_facture","title":"طلب فاتورة"},
             {"id":"btn_mainlevee","title":"رفع اليد"},
             {"id":"btn_reclamation","title":"شكاية"}])
    else:
        wa_btns(tel, "Quelle est votre demande ?",
            [{"id":"btn_facture","title":"Demande Facture"},
             {"id":"btn_mainlevee","title":"Mainlevee"},
             {"id":"btn_reclamation","title":"Reclamation"}])

def notifier(tel, nom_wa, data):
    t = data.get("type","vn")
    _, sn = get_sheet(t)
    lignes = [f"--- NOUVEAU : {sn} ---", f"WA : {tel}", f"Nom : {nom_wa}"]
    for k,l in [("prenom","Prenom"),("nom","Nom"),("tel","Tel"),("modele","Modele"),
                ("ville","Ville"),("chassis","Chassis"),("cin","CIN"),("rc","RC"),
                ("type_facture","Type facture"),("reclamation","Reclamation"),
                ("date_essai","Date essai")]:
        if data.get(k): lignes.append(f"{l} : {data[k]}")
    lignes.append(f"Statut : {'URGENT 48h' if t=='reclamation' else 'A RAPPELER'}")
    wa_text(wa_con(), "\n".join(lignes))

def recap(data, langue="FR"):
    if langue in ["AR","DARIJA"]:
        intro = "ملخص طلبك :\n"
        labels = {"prenom":"الاسم","nom":"اسم العائلة","tel":"الهاتف",
                  "modele":"الموديل","ville":"المدينة","date_essai":"التاريخ",
                  "chassis":"رقم الهيكل","cin":"رقم ب.و","rc":"السجل التجاري",
                  "type_facture":"نوع الفاتورة","reclamation":"الشكاية"}
        fin = "\nهل هذه المعلومات صحيحة ؟ (نعم / لا)"
    else:
        intro = "Recapitulatif de votre demande :\n"
        labels = {"prenom":"Prenom","nom":"Nom","tel":"Telephone",
                  "modele":"Modele","ville":"Ville","date_essai":"Date souhaitee",
                  "chassis":"Chassis","cin":"CIN","rc":"RC",
                  "type_facture":"Type facture","reclamation":"Reclamation"}
        fin = "\nCes informations sont-elles correctes ? (Oui / Non)"
    t = intro
    for k,l in labels.items():
        v = data.get(k,"")
        if v and v not in ["X","","null","?"]:
            t += f"- {l} : {v}\n"
    t += fin
    return t

def q(fr_text, ar_text, langue):
    """Retourne la question dans la bonne langue"""
    if langue in ["AR","DARIJA"]:
        return ar_text
    return fr_text

# ============================================================
# MACHINES A ETATS — logique métier pure
# ============================================================
def traiter_flow(sess, tel, nom, texte):
    flow = sess["flow"]
    step = sess["step"]
    infos = sess["infos"]
    tl = texte.strip()
    lg = sess.get("langue","FR")
    print(f"[FLOW] {flow} step={step} lang={lg}")

    # ==== ESSAI VN ====
    if flow == "essai":
        if step == 1:
            if is_refus(tl): reset_flow(sess); return q("Tres bien. Merci pour votre confiance.","حسناً. شكراً لثقتك بنا.",lg), True
            infos["prenom"]=nettoyer(tl); sess["step"]=2
            return q("Votre nom ?","اسم العائلة ؟",lg), False
        elif step == 2:
            infos["nom"]=nettoyer(tl); sess["step"]=3
            return q("Votre numero de telephone ?","رقم هاتفك ؟",lg), False
        elif step == 3:
            if not valider_tel(tl): return q("Numero invalide (ex: 0612345678).","رقم غير صحيح (مثال: 0612345678).",lg), False
            infos["tel"]=nettoyer(tl); sess["step"]=4
            return q("Quel modele souhaitez-vous essayer ?","ما الموديل الذي تريد تجربته ؟",lg), False
        elif step == 4:
            infos["modele"]=nettoyer(tl); sess["step"]=5
            return q("Dans quelle ville ?","في أي مدينة ؟",lg), False
        elif step == 5:
            infos["ville"]=nettoyer(tl); sess["step"]=6
            return q("Date souhaitee pour l'essai ? (ex: 15/06/2026 ou 'des que possible')","التاريخ المناسب للتجربة ؟ (مثال: 15/06/2026 أو 'في أقرب وقت')",lg), False
        elif step == 6:
            infos["date_essai"]=nettoyer(tl) if not is_refus(tl) else q("Des que possible","في أقرب وقت",lg)
            sess["step"]=7
            return recap(infos, lg), False
        elif step == 7:
            if is_oui(tl):
                ok=enregistrer(tel, lg, {**infos,"type":"essai"})
                notifier(tel, nom, {**infos,"type":"essai"})
                reset_flow(sess)
                msg = q("Votre demande d'essai a ete enregistree. Notre equipe vous contactera pour confirmer la date.\n\nMerci pour votre confiance.",
                        "تم تسجيل طلب التجربة. سيتصل بك فريقنا لتأكيد الموعد.\n\nشكراً لثقتك بنا.",lg)
                if not ok: msg += q("\n(Note: incident technique, un conseiller vous contactera)","\n(ملاحظة: مشكل تقني، سيتصل بك مستشارنا)",lg)
                return msg, True
            elif is_refus(tl):
                sess["step"]=8
                return q("Quelle information modifier ? (prenom/nom/telephone/modele/ville/date)","ما المعلومة التي تريد تغييرها ؟ (الاسم/الهاتف/الموديل/المدينة/التاريخ)",lg), False
            else:
                return q("Repondez Oui ou Non.","الرجاء الاجابة بنعم أو لا.",lg)+"\n\n"+recap(infos,lg), False
        elif step == 8:
            tll=tl.lower()
            if any(w in tll for w in ["prenom","smit","اسم"]): infos.pop("prenom",None); sess["step"]=1; return q("Votre prenom ?","اسمك الأول ؟",lg), False
            elif any(w in tll for w in ["nom","nsab","عائلة"]): infos.pop("nom",None); sess["step"]=2; return q("Votre nom ?","اسم العائلة ؟",lg), False
            elif any(w in tll for w in ["tel","telephone","هاتف"]): infos.pop("tel",None); sess["step"]=3; return q("Votre telephone ?","رقم هاتفك ؟",lg), False
            elif any(w in tll for w in ["modele","موديل"]): infos.pop("modele",None); sess["step"]=4; return q("Quel modele ?","الموديل ؟",lg), False
            elif any(w in tll for w in ["ville","مدينة"]): infos.pop("ville",None); sess["step"]=5; return q("Quelle ville ?","المدينة ؟",lg), False
            elif any(w in tll for w in ["date","تاريخ"]): infos.pop("date_essai",None); sess["step"]=6; return q("Quelle date ?","التاريخ ؟",lg), False
            else: return q("Precisez l'info a modifier.","حدد المعلومة التي تريد تغييرها.",lg), False

    # ==== RDI ====
    elif flow == "rdi":
        if step == 1:
            if is_oui(tl): sess["step"]=2; return q("Etes-vous un particulier ou une societe ?","هل أنت شخص عادي أم شركة ؟",lg), False
            elif is_refus(tl):
                reset_flow(sess)
                return q("Le delai de 30 jours n'est pas encore ecoule. Vous pourrez faire la demande apres. Merci pour votre confiance.",
                         "لم تمض بعد 30 يوماً من تاريخ التسليم. يمكنك تقديم الطلب بعد هذا الأجل. شكراً لثقتك بنا.",lg), True
            else: return q("Votre vehicule a-t-il ete livre il y a plus de 30 jours ? (Oui / Non)",
                           "هل تم تسليم سيارتك منذ أكثر من 30 يوماً ؟ (نعم / لا)",lg), False
        elif step == 2:
            if any(w in tl.lower() for w in ["particulier","prive","individuel","personne","شخص","خاص"]):
                infos["type_client"]="particulier"; sess["step"]=3
            elif any(w in tl.lower() for w in ["societe","entreprise","ste","commerce","شركة","مقاولة"]):
                infos["type_client"]="societe"; sess["step"]=3
            else: return q("Particulier ou societe ?","شخص عادي أم شركة ؟",lg), False
            return q("Votre prenom ?","اسمك الأول ؟",lg), False
        elif step == 3:
            infos["prenom"]=nettoyer(tl); sess["step"]=4
            return q("Votre nom (nom de famille) ?","اسم العائلة ؟",lg), False
        elif step == 4:
            infos["nom"]=nettoyer(tl); sess["step"]=5
            return q("Votre numero de chassis (VIN) ?","رقم الهيكل (VIN) ؟",lg), False
        elif step == 5:
            ch=tl.replace(" ","")
            if not valider_chassis(ch): return q("Chassis incomplet (min 11 caracteres).","رقم الهيكل ناقص (11 حرف على الأقل).",lg), False
            infos["chassis"]=ch.upper(); sess["step"]=6
            return (q("Votre numero RC ?","رقم السجل التجاري ؟",lg) if infos.get("type_client")=="societe"
                    else q("Votre numero de CIN ?","رقم بطاقة التعريف الوطنية ؟",lg)), False
        elif step == 6:
            if infos.get("type_client")=="societe":
                infos["rc"]=nettoyer(tl).upper()
            else:
                cin=nettoyer(tl).upper()
                if not valider_cin(cin): return q("Format CIN invalide (ex: BE123456).","صيغة البطاقة الوطنية غير صحيحة (مثال: BE123456).",lg), False
                infos["cin"]=cin
            sess["step"]=7; return q("Votre telephone ?","رقم هاتفك ؟",lg), False
        elif step == 7:
            if not valider_tel(tl): return q("Numero invalide.","رقم غير صحيح.",lg), False
            infos["tel"]=nettoyer(tl); sess["step"]=8
            return recap(infos,lg), False
        elif step == 8:
            if is_oui(tl):
                info_rdi=verifier_rdi(infos.get("chassis",""))
                if info_rdi is None:
                    rep=q("Impossible d'acceder au systeme. Notre equipe vous contactera.",
                          "تعذر الوصول للنظام. سيتصل بك فريقنا.",lg)
                    notifier(tel, nom, {**infos,"type":"rdi"})
                elif info_rdi.get("trouve"):
                    statut=info_rdi.get("statut","En cours")
                    date_d=info_rdi.get("date_dispo","")
                    statut_lower = statut.lower()
                    # Cas A : Disponible
                    if any(w in statut_lower for w in ["disponible","pret","termine","traite","traité"]):
                        rep=q(
                            f"Verification dossier :\n\n"
                            f"- Chassis : {infos['chassis']}\n"
                            f"- Statut : {statut}\n",
                            f"نتيجة الملف :\n\n"
                            f"- رقم الهيكل : {infos['chassis']}\n"
                            f"- الحالة : {statut}\n",lg)
                        if date_d:
                            rep+=q(f"- Date de disponibilite : {date_d}\n",
                                   f"- تاريخ الاستعداد : {date_d}\n",lg)
                        rep+=q("\nVotre RDI est disponible. Vous pouvez vous presenter a la concession.\n\nPour plus d\'informations : 0523303194.",
                               "\nوصلك RDI متاح. يمكنك التوجه إلى الوكالة.\n\nللاستفسار : 0523303194.",lg)
                    # Cas B : En cours
                    else:
                        rep=q(
                            f"Verification dossier :\n\n"
                            f"- Chassis : {infos['chassis']}\n"
                            f"- Statut : {statut}\n",
                            f"نتيجة الملف :\n\n"
                            f"- رقم الهيكل : {infos['chassis']}\n"
                            f"- الحالة : {statut}\n",lg)
                        if date_d:
                            rep+=q(f"- Date de disponibilite estimee : {date_d}\n",
                                   f"- التاريخ المتوقع : {date_d}\n",lg)
                        rep+=q("\nVotre dossier est en cours de traitement. Pour plus d\'informations : 0523303194.",
                               "\nملفك قيد المعالجة. للاستفسار : 0523303194.",lg)
                else:
                    rep=q(f"Le dossier pour le chassis {infos['chassis']} n'est pas encore enregistre dans notre systeme. Notre equipe va verifier et vous contactera tres prochainement.",
                          f"ملف الهيكل {infos['chassis']} غير مسجل بعد في نظامنا. سيتحقق فريقنا ويتصل بك قريباً.",lg)
                    notifier(tel, nom, {**infos,"type":"rdi"})
                reset_flow(sess)
                return rep+q("\n\nMerci pour votre confiance.","\n\nشكراً لثقتك بنا.",lg), True
            elif is_refus(tl):
                sess["step"]=9; return q("Quelle info modifier ? (prenom/nom/chassis/cin/rc/telephone)",
                                         "ما المعلومة التي تريد تغييرها ؟ (الاسم/اسم العائلة/الهيكل/البطاقة/السجل/الهاتف)",lg), False
            else: return q("Oui ou Non ?","نعم أو لا ؟",lg)+"\n\n"+recap(infos,lg), False
        elif step == 9:
            tll=tl.lower()
            if any(w in tll for w in ["prenom","smit","اسم الأول"]): sess["step"]=3; return q("Votre prenom ?","اسمك الأول ؟",lg), False
            elif any(w in tll for w in ["nom","nsab","عائلة"]): infos.pop("nom",None); sess["step"]=4; return q("Votre nom ?","اسم العائلة ؟",lg), False
            elif any(w in tll for w in ["chassis","هيكل"]): infos.pop("chassis",None); sess["step"]=5; return q("Chassis ?","رقم الهيكل ؟",lg), False
            elif any(w in tll for w in ["cin","بطاقة"]): infos.pop("cin",None); sess["step"]=6; return q("CIN ?","رقم البطاقة ؟",lg), False
            elif any(w in tll for w in ["rc","سجل"]): infos.pop("rc",None); sess["step"]=6; return q("RC ?","السجل التجاري ؟",lg), False
            elif any(w in tll for w in ["tel","telephone","هاتف"]): infos.pop("tel",None); sess["step"]=7; return q("Telephone ?","الهاتف ؟",lg), False
            else: return q("Precisez : prenom, nom, chassis, CIN, RC ou telephone.","حدد : الاسم، اسم العائلة، الهيكل، البطاقة، السجل أو الهاتف.",lg), False

    # ==== FACTURE ====
    elif flow == "facture":
        if step == 1:
            tll=tl.lower()
            if any(w in tll for w in ["vente","achat","neuf","occasion","vn","vo","1","شراء","سيارة"]):
                infos["type_facture"]="Vente VN/VO"; infos["type"]="facture_vente"
            elif any(w in tll for w in ["mecanique","atelier","entretien","reparation","2","ميكانيك","صيانة"]):
                infos["type_facture"]="Mecanique"; infos["type"]="facture_mecanique"
            elif any(w in tll for w in ["carrosserie","peinture","3","كاروسري"]):
                infos["type_facture"]="Carrosserie"; infos["type"]="facture_carrosserie"
            elif any(w in tll for w in ["piece","rechange","accessoire","4","قطع","غيار"]):
                infos["type_facture"]="Pieces de rechange"; infos["type"]="facture_pieces"
            else:
                return q("Quel type de facture ?\n1. Achat vehicule (VN/VO)\n2. Mecanique\n3. Carrosserie\n4. Pieces de rechange",
                         "نوع الفاتورة ؟\n1. شراء سيارة\n2. ميكانيك\n3. كاروسري\n4. قطع غيار",lg), False
            sess["step"]=2; return q("Numero de chassis ou matricule ?","رقم الهيكل أو اللوحة ؟",lg), False
        elif step == 2:
            infos["chassis"]=nettoyer(tl).upper(); sess["step"]=3
            return q("Prenom du titulaire ?","الاسم الأول للمالك ؟",lg), False
        elif step == 3:
            infos["prenom"]=nettoyer(tl); sess["step"]=4
            return q("Nom du titulaire ?","اسم العائلة للمالك ؟",lg), False
        elif step == 4:
            infos["nom"]=nettoyer(tl); sess["step"]=5
            return q("Votre telephone ?","رقم هاتفك ؟",lg), False
        elif step == 5:
            if not valider_tel(tl): return q("Numero invalide.","رقم غير صحيح.",lg), False
            infos["tel"]=nettoyer(tl); sess["step"]=6
            return recap(infos,lg), False
        elif step == 6:
            if is_oui(tl):
                ok=enregistrer(tel, lg, infos)
                notifier(tel, nom, infos)
                reset_flow(sess)
                msg=q(f"Demande facture ({infos.get('type_facture','')}) enregistree. Notre equipe vous contactera.\n\nMerci pour votre confiance.",
                      f"تم تسجيل طلب الفاتورة ({infos.get('type_facture','')}). سيتصل بك فريقنا.\n\nشكراً لثقتك بنا.",lg)
                return msg, True
            elif is_refus(tl):
                sess["step"]=7; return q("Quelle info modifier ?","ما الذي تريد تغييره ؟",lg), False
            else: return q("Oui ou Non ?","نعم أو لا ؟",lg)+"\n\n"+recap(infos,lg), False
        elif step == 7:
            tll=tl.lower()
            if any(w in tll for w in ["type","facture","نوع"]): infos.pop("type_facture",None); infos.pop("type",None); sess["step"]=1; return q("Quel type ?","نوع ؟",lg), False
            elif any(w in tll for w in ["chassis","matricule","هيكل"]): sess["step"]=2; return q("Chassis ?","الهيكل ؟",lg), False
            elif any(w in tll for w in ["prenom","اسم الأول"]): sess["step"]=3; return q("Prenom ?","الاسم ؟",lg), False
            elif any(w in tll for w in ["nom","عائلة"]): sess["step"]=4; return q("Nom ?","اسم العائلة ؟",lg), False
            elif any(w in tll for w in ["tel","telephone","هاتف"]): sess["step"]=5; return q("Telephone ?","الهاتف ؟",lg), False
            else: return q("Precisez.","حدد.",lg), False

    # ==== RECLAMATION ====
    elif flow == "reclamation":
        if step == 1:
            infos["prenom"]=nettoyer(tl); sess["step"]=2; return q("Votre nom ?","اسم العائلة ؟",lg), False
        elif step == 2:
            infos["nom"]=nettoyer(tl); sess["step"]=3; return q("Votre telephone ?","رقم هاتفك ؟",lg), False
        elif step == 3:
            if not valider_tel(tl): return q("Numero invalide.","رقم غير صحيح.",lg), False
            infos["tel"]=nettoyer(tl); sess["step"]=4
            return q("Numero de chassis ou plaque (tapez 'non' si pas applicable) ?",
                     "رقم الهيكل أو اللوحة (اكتب 'لا' إن لم ينطبق) ؟",lg), False
        elif step == 4:
            if not is_refus(tl): infos["chassis"]=nettoyer(tl).upper()
            sess["step"]=5; return q("Decrivez votre reclamation :","صف شكواك بالتفصيل :",lg), False
        elif step == 5:
            infos["reclamation"]=nettoyer(tl); infos["type"]="reclamation"; sess["step"]=6
            return recap(infos,lg), False
        elif step == 6:
            if is_oui(tl):
                ok=enregistrer(tel, lg, infos)
                notifier(tel, nom, infos)
                reset_flow(sess)
                return q("Reclamation enregistree et transmise au responsable qualite. Reponse sous 48h ouvrees.\n\nMerci pour votre confiance.",
                         "تم تسجيل شكواك وإرسالها لمسؤول الجودة. ستتلقى رداً في 48 ساعة عمل.\n\nشكراً لثقتك بنا.",lg), True
            elif is_refus(tl):
                sess["step"]=7; return q("Quelle info modifier ?","ما الذي تريد تغييره ؟",lg), False
            else: return q("Oui ou Non ?","نعم أو لا ؟",lg)+"\n\n"+recap(infos,lg), False
        elif step == 7:
            tll=tl.lower()
            if any(w in tll for w in ["prenom","اسم"]): sess["step"]=1; return q("Prenom ?","الاسم ؟",lg), False
            elif any(w in tll for w in ["nom","عائلة"]): sess["step"]=2; return q("Nom ?","اسم العائلة ؟",lg), False
            elif any(w in tll for w in ["tel","telephone","هاتف"]): sess["step"]=3; return q("Telephone ?","الهاتف ؟",lg), False
            elif any(w in tll for w in ["chassis","هيكل"]): sess["step"]=4; return q("Chassis ?","الهيكل ؟",lg), False
            elif any(w in tll for w in ["description","reclamation","شكاية"]): sess["step"]=5; return q("Decrivez :","صف :",lg), False
            else: return q("Precisez.","حدد.",lg), False

    # ==== SAV ====
    elif flow == "sav":
        if step == 1:
            if is_refus(tl): reset_flow(sess); return q("Tres bien. RDV atelier : https://top-auto.ma/Entretienr%C3%A9paration\n\nMerci pour votre confiance.",
                                                         "حسناً. موعد الورشة : https://top-auto.ma/Entretienr%C3%A9paration\n\nشكراً لثقتك بنا.",lg), True
            infos["prenom"]=nettoyer(tl); sess["step"]=2; return q("Votre nom ?","اسم العائلة ؟",lg), False
        elif step == 2:
            infos["nom"]=nettoyer(tl); sess["step"]=3; return q("Votre telephone ?","رقم هاتفك ؟",lg), False
        elif step == 3:
            if not valider_tel(tl): return q("Numero invalide.","رقم غير صحيح.",lg), False
            infos["tel"]=nettoyer(tl); infos["type"]="sav_atelier"; sess["step"]=4
            return recap(infos,lg), False
        elif step == 4:
            if is_oui(tl):
                enregistrer(tel, lg, infos); notifier(tel, nom, infos); reset_flow(sess)
                return q("RDV atelier : https://top-auto.ma/Entretienr%C3%A9paration\n\nVotre demande a ete transmise. Notre equipe vous contactera.\n\nMerci pour votre confiance.",
                         "موعد الورشة : https://top-auto.ma/Entretienr%C3%A9paration\n\nتم إرسال طلبك. سيتصل بك فريقنا.\n\nشكراً لثقتك بنا.",lg), True
            else: return recap(infos,lg), False

    # ==== VN ====
    elif flow == "vn":
        if step == 1:
            if is_refus(tl): reset_flow(sess); return q("Tres bien. Contactez-nous au 0523303194.\n\nMerci pour votre confiance.",
                                                         "حسناً. اتصل بنا على 0523303194.\n\nشكراً لثقتك بنا.",lg), True
            # Si le client envoie un numero de tel au lieu du prenom
            if valider_tel(tl.replace(" ","")):
                infos["prenom"]=""; infos["tel"]=nettoyer(tl); infos["type"]="vn"
                enregistrer(tel, lg, infos); notifier(tel, nom, infos); reset_flow(sess)
                return q("Merci ! Notre conseiller vous contactera avec le meilleur tarif personnalise.\n\nMerci pour votre confiance.",
                         "شكراً ! سيتصل بك مستشارنا بأفضل سعر مخصص لك.\n\nشكراً لثقتك بنا.",lg), True
            infos["prenom"]=nettoyer(tl); sess["step"]=2; return q("Votre telephone ?","رقم هاتفك ؟",lg), False
        elif step == 2:
            if not valider_tel(tl): return q("Numero invalide.","رقم غير صحيح.",lg), False
            infos["tel"]=nettoyer(tl); infos["type"]="vn"
            enregistrer(tel, lg, infos); notifier(tel, nom, infos); reset_flow(sess)
            return q("Merci ! Notre conseiller vous contactera avec le meilleur tarif personnalise.\n\nMerci pour votre confiance.",
                     "شكراً ! سيتصل بك مستشارنا بأفضل سعر مخصص لك.\n\nشكراً لثقتك بنا.",lg), True

    # ==== VO ====
    elif flow == "vo":
        if step == 1:
            if is_refus(tl): reset_flow(sess); return q("Tres bien. Stock : https://top-auto.ma/Voitures_occasion\n\nMerci pour votre confiance.",
                                                         "حسناً. المخزون : https://top-auto.ma/Voitures_occasion\n\nشكراً لثقتك بنا.",lg), True
            if valider_tel(tl.replace(" ","")):
                infos["prenom"]=""; infos["tel"]=nettoyer(tl); infos["type"]="vo"
                enregistrer(tel, lg, infos); notifier(tel, nom, infos); reset_flow(sess)
                return q("Merci ! Notre conseiller VO vous contactera.\nStock : https://top-auto.ma/Voitures_occasion\n\nMerci pour votre confiance.",
                         "شكراً ! سيتصل بك مستشار السيارات المستعملة.\nالمخزون : https://top-auto.ma/Voitures_occasion\n\nشكراً لثقتك بنا.",lg), True
            infos["prenom"]=nettoyer(tl); sess["step"]=2; return q("Votre telephone ?","رقم هاتفك ؟",lg), False
        elif step == 2:
            if not valider_tel(tl): return q("Numero invalide.","رقم غير صحيح.",lg), False
            infos["tel"]=nettoyer(tl); infos["type"]="vo"
            enregistrer(tel, lg, infos); notifier(tel, nom, infos); reset_flow(sess)
            return q("Merci ! Notre conseiller VO vous contactera.\nStock : https://top-auto.ma/Voitures_occasion\n\nMerci pour votre confiance.",
                     "شكراً ! سيتصل بك مستشار السيارات المستعملة.\nالمخزون : https://top-auto.ma/Voitures_occasion\n\nشكراً لثقتك بنا.",lg), True

    # ==== MAINLEVEE ====
    elif flow == "mainlevee":
        if step == 1:
            if is_refus(tl): reset_flow(sess); return q("D'accord. Merci pour votre confiance.","حسناً. شكراً لثقتك بنا.",lg), True
            infos["prenom"]=nettoyer(tl); sess["step"]=2; return q("Votre nom ?","اسم العائلة ؟",lg), False
        elif step == 2:
            infos["nom"]=nettoyer(tl); sess["step"]=3; return q("Votre telephone ?","رقم هاتفك ؟",lg), False
        elif step == 3:
            if not valider_tel(tl): return q("Numero invalide.","رقم غير صحيح.",lg), False
            infos["tel"]=nettoyer(tl); sess["step"]=4; return q("Votre numero de chassis ?","رقم الهيكل ؟",lg), False
        elif step == 4:
            infos["chassis"]=nettoyer(tl).upper(); infos["type"]="mainlevee"; sess["step"]=5
            return recap(infos,lg), False
        elif step == 5:
            if is_oui(tl):
                enregistrer(tel, lg, infos); notifier(tel, nom, infos); reset_flow(sess)
                return q("Demande de mainlevee enregistree. Notre equipe SAV vous contactera sous 24-48h.\n\nMerci pour votre confiance.",
                         "تم تسجيل طلب رفع اليد. سيتصل بك فريق SAV في 24-48 ساعة.\n\nشكراً لثقتك بنا.",lg), True
            else: return recap(infos,lg), False

    return None, False

# ============================================================
# DEMARRAGE FLUX
# ============================================================
def demarrer(sess, tel, flow, langue):
    reset_flow(sess)
    sess["flow"] = flow
    sess["step"] = 1
    msgs = {
        "essai":      q("Votre prenom, s'il vous plait ?","اسمك الأول، من فضلك ؟",langue),
        "rdi":        q("Votre vehicule a-t-il ete livre il y a plus de 30 jours ? (Oui / Non)",
                        "هل تم تسليم سيارتك منذ أكثر من 30 يوماً ؟ (نعم / لا)",langue),
        "facture":    q("Quel type de facture ?\n1. Achat vehicule (VN/VO)\n2. Mecanique\n3. Carrosserie\n4. Pieces de rechange",
                        "نوع الفاتورة ؟\n1. شراء سيارة\n2. ميكانيك\n3. كاروسري\n4. قطع غيار",langue),
        "reclamation":q("Je suis desole d'apprendre ce probleme. Votre satisfaction est notre priorite.\n\nVotre prenom ?",
                        "أنا آسف لسماع هذا. رضاك هو أولويتنا.\n\nاسمك الأول ؟",langue),
        "mainlevee":  q("Votre prenom ?","اسمك الأول ؟",langue),
        "vn":         q("Votre prenom ?","اسمك الأول ؟",langue),
        "vo":         q("Votre prenom ?","اسمك الأول ؟",langue),
        "sav":        q("Votre prenom, s'il vous plait ?","اسمك الأول، من فضلك ؟",langue),
    }
    return msgs.get(flow, q("Votre prenom ?","اسمك الأول ؟",langue))

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
                wa_text(tel, "Transcription impossible. Merci d'ecrire.")
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
            sess_img = get_sess(tel)
            wa_text(tel, analyse)
            wa_btns(tel, q("Souhaitez-vous un rendez-vous atelier ?","هل تريد موعداً في الورشة ؟",sess_img.get("langue","FR")),
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
            sess = get_sess(tel)
            lg  = sess.get("langue","FR")

            if bid == "btn_vehicules":
                wa_menu_veh(tel, lg); return jsonify({"status":"ok"}), 200
            elif bid == "btn_sav":
                reset_flow(sess)
                wa_text(tel, q("RDV atelier : https://top-auto.ma/Entretienr%C3%A9paration\n\nSouhaitez-vous laisser vos coordonnees ?",
                               "موعد الورشة : https://top-auto.ma/Entretienr%C3%A9paration\n\nهل تريد ترك معلوماتك للتواصل ؟",lg))
                wa_btns(tel, q("Laisser mes coordonnees ?","ترك معلوماتك ؟",lg),
                    [{"id":"btn_sav_oui","title":"Oui, me rappeler" if lg=="FR" else "Oui"},
                     {"id":"btn_sav_non","title":"Non, merci" if lg=="FR" else "La"}])
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_sav_oui":
                msg_d = demarrer(sess, tel, "sav", lg); wa_text(tel, msg_d)
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_sav_non":
                reset_flow(sess); wa_text(tel, q("Tres bien. Merci pour votre confiance.","حسناً. شكراً لثقتك بنا.",lg))
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_autre":
                wa_menu_autre(tel, lg); return jsonify({"status":"ok"}), 200
            elif bid == "btn_vn":
                reset_flow(sess)
                wa_text(tel, CATALOGUE + q("\n\nPour un tarif personnalise, notre conseiller vous contactera.\nVotre prenom ?",
                                            "\n\nللحصول على أفضل سعر، سيتصل بك مستشارنا.\nاسمك الأول ؟",lg))
                sess["flow"]="vn"; sess["step"]=1; return jsonify({"status":"ok"}), 200
            elif bid == "btn_vo":
                reset_flow(sess)
                wa_text(tel, q("Stock occasion : https://top-auto.ma/Voitures_occasion\n\nVotre prenom pour mise en relation ?",
                               "المخزون : https://top-auto.ma/Voitures_occasion\n\nاسمك الأول للتواصل ؟",lg))
                sess["flow"]="vo"; sess["step"]=1; return jsonify({"status":"ok"}), 200
            elif bid == "btn_essai":
                msg_d = demarrer(sess, tel, "essai", lg); wa_text(tel, msg_d)
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_facture":
                msg_d = demarrer(sess, tel, "facture", lg); wa_text(tel, msg_d)
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_mainlevee":
                reset_flow(sess)
                wa_text(tel, q(
                    "Pour votre mainlevee, presentez-vous avec :\n\n"
                    "• Copie de la CIN\n• Copie de la carte grise\n"
                    "• Releve bancaire cachete (dernier prelevement RCI Finance)\n"
                    "• Justificatif paiement valeur residuelle (si applicable)\n\n"
                    "RIB RCI Finance Maroc : 007 780 00000 054111 70005 29\n\n"
                    "Souhaitez-vous etre rappele par un conseiller ?",
                    "للحصول على رفع اليد، احضر معك :\n\n"
                    "• نسخة من البطاقة الوطنية\n• نسخة من بطاقة السيارة\n"
                    "• كشف حساب مختوم (آخر سحب RCI Finance)\n"
                    "• إثبات دفع القيمة المتبقية (إن وجدت)\n\n"
                    "RIB RCI Finance Maroc : 007 780 00000 054111 70005 29\n\n"
                    "هل تريد أن يتصل بك مستشار ؟",lg))
                wa_btns(tel, q("Etre rappele ?","أن يتصل بك مستشار ؟",lg),
                    [{"id":"btn_ml_oui","title":"Oui, me rappeler" if lg=="FR" else "Oui"},
                     {"id":"btn_ml_non","title":"Non, merci" if lg=="FR" else "La"}])
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_ml_oui":
                msg_d = demarrer(sess, tel, "mainlevee", lg); wa_text(tel, msg_d)
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_ml_non":
                reset_flow(sess); wa_text(tel, q("D'accord. Merci pour votre confiance.","حسناً. شكراً لثقتك بنا.",lg))
                return jsonify({"status":"ok"}), 200
            elif bid == "btn_reclamation":
                msg_d = demarrer(sess, tel, "reclamation", lg); wa_text(tel, msg_d)
                return jsonify({"status":"ok"}), 200
            elif bid in ("btn_rdv_sav",):
                wa_text(tel, q("RDV atelier : https://top-auto.ma/Entretienr%C3%A9paration\n\nMerci pour votre confiance.",
                               "موعد الورشة : https://top-auto.ma/Entretienr%C3%A9paration\n\nشكراً لثقتك بنا.",lg))
                return jsonify({"status":"ok"}), 200
            elif bid in ("btn_autre_q",):
                wa_text(tel, q("Je suis a votre ecoute. Merci pour votre confiance.","أنا في خدمتك. شكراً لثقتك بنا.",lg))
                return jsonify({"status":"ok"}), 200
            return jsonify({"status":"ok"}), 200
        else:
            return jsonify({"status":"ok"}), 200

        if not texte:
            return jsonify({"status":"ok"}), 200

        print(f"\n[MSG] {tel} ({nom}): {texte[:60]}")
        sess = get_sess(tel)

        # Détecter la langue
        lg = detect_langue(texte)
        if lg != sess.get("langue","FR"):
            sess["langue"] = lg

        # 1. FLUX ACTIF — traitement direct sans passer par le classifier
        if sess.get("flow"):
            rep, done = traiter_flow(sess, tel, nom, texte)
            if rep:
                sess["hist"].append({"role":"user","content":texte})
                sess["hist"].append({"role":"assistant","content":rep})
                if len(sess["hist"]) > 10: sess["hist"] = sess["hist"][-10:]
                wa_text(tel, rep)
                return jsonify({"status":"ok"}), 200

        # 2. CLASSIFIER GROQ — comprend le sens même avec fautes
        try:
            intention = classifier_intention(texte, lg)
        except Exception as e:
            print(f"[CLASSIFIER ERR] {e}")
            intention = "##GENERAL##"

        # 3. ROUTING PAR INTENTION
        if intention == "##SALUTATION##":
            wa_bienvenue(tel, lg)
            return jsonify({"status":"ok"}), 200

        elif intention == "##ESSAI##":
            msg_d = demarrer(sess, tel, "essai", lg)
            wa_text(tel, msg_d)
            return jsonify({"status":"ok"}), 200

        elif intention == "##RDI##":
            msg_d = demarrer(sess, tel, "rdi", lg)
            wa_text(tel, msg_d)
            return jsonify({"status":"ok"}), 200

        elif intention == "##FACTURE##":
            msg_d = demarrer(sess, tel, "facture", lg)
            wa_text(tel, msg_d)
            return jsonify({"status":"ok"}), 200

        elif intention == "##MAINLEVEE##":
            reset_flow(sess)
            wa_text(tel, q(
                "Pour votre mainlevee, presentez-vous avec :\n\n"
                "• Copie de la CIN\n• Copie de la carte grise\n"
                "• Releve bancaire cachete (dernier prelevement RCI Finance)\n"
                "• Justificatif paiement valeur residuelle (si applicable)\n\n"
                "RIB RCI Finance Maroc : 007 780 00000 054111 70005 29\n\n"
                "Souhaitez-vous etre rappele par un conseiller ?",
                "للحصول على رفع اليد، احضر معك :\n\n"
                "• نسخة من البطاقة الوطنية\n• نسخة من بطاقة السيارة\n"
                "• كشف حساب مختوم (آخر سحب RCI Finance)\n"
                "• إثبات دفع القيمة المتبقية (إن وجدت)\n\n"
                "RIB RCI Finance Maroc : 007 780 00000 054111 70005 29\n\n"
                "هل تريد أن يتصل بك مستشار ؟",lg))
            wa_btns(tel, q("Etre rappele ?","أن يتصل بك مستشار ؟",lg),
                [{"id":"btn_ml_oui","title":"Oui, me rappeler" if lg=="FR" else "Oui"},
                 {"id":"btn_ml_non","title":"Non, merci" if lg=="FR" else "La"}])
            return jsonify({"status":"ok"}), 200

        elif intention == "##RECLAMATION##":
            msg_d = demarrer(sess, tel, "reclamation", lg)
            wa_text(tel, msg_d)
            return jsonify({"status":"ok"}), 200

        elif intention == "##SAV##":
            reset_flow(sess)
            wa_text(tel, q("Pour votre rendez-vous atelier :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\nSouhaitez-vous laisser vos coordonnees pour etre rappele ?",
                           "موعد الورشة :\nhttps://top-auto.ma/Entretienr%C3%A9paration\n\nهل تريد ترك معلوماتك للتواصل ؟",lg))
            wa_btns(tel, q("Laisser mes coordonnees ?","ترك معلوماتك ؟",lg),
                [{"id":"btn_sav_oui","title":"Oui, me rappeler" if lg=="FR" else "Oui"},
                 {"id":"btn_sav_non","title":"Non, merci" if lg=="FR" else "La"}])
            return jsonify({"status":"ok"}), 200

        elif intention == "##VO##":
            reset_flow(sess)
            wa_text(tel, q("Stock occasion : https://top-auto.ma/Voitures_occasion\n\nPour une mise en relation avec un conseiller VO, votre prenom ?",
                           "المخزون : https://top-auto.ma/Voitures_occasion\n\nللتواصل مع مستشار السيارات المستعملة، اسمك الأول ؟",lg))
            sess["flow"]="vo"; sess["step"]=1
            return jsonify({"status":"ok"}), 200

        elif intention == "##VN##":
            reset_flow(sess)
            wa_text(tel, q("Pour vous accompagner dans votre achat, notre conseiller vous contactera avec le meilleur tarif.\n\nVotre prenom ?",
                           "لمرافقتك في عملية الشراء، سيتصل بك مستشارنا بأفضل سعر.\n\nاسمك الأول ؟",lg))
            sess["flow"]="vn"; sess["step"]=1
            return jsonify({"status":"ok"}), 200

        elif intention == "##PRIX##":
            wa_text(tel, q("Pour vous communiquer le meilleur tarif personnalise et verifier la disponibilite, notre equipe commerciale vous contactera tres prochainement.\n\nVotre prenom ?",
                           "لإطلاعك على أفضل سعر مخصص والتحقق من التوفر، سيتصل بك فريقنا التجاري قريباً.\n\nاسمك الأول ؟",lg))
            sess["flow"]="vn"; sess["step"]=1
            return jsonify({"status":"ok"}), 200

        elif intention == "##HORAIRES##":
            wa_text(tel, q("Horaires d'ouverture :\n\n• Lundi-Vendredi : 8h00-18h30\n• Samedi : 8h30-15h00\n• Dimanche : Ferme\n\nMerci pour votre confiance.",
                           "أوقات العمل :\n\n• الاثنين-الجمعة : 8:00-18:30\n• السبت : 8:30-15:00\n• الأحد : مغلق\n\nشكراً لثقتك بنا.",lg))
            return jsonify({"status":"ok"}), 200

        elif intention == "##ADRESSE##":
            wa_text(tel, q("Adresse : Q.I Bd Sidi Mohamed Ben Abdellah, 208000 Mohammedia\nGPS : https://maps.google.com/?q=33.683384,-7.409769\n\nMerci pour votre confiance.",
                           "العنوان : ق.ص شارع سيدي محمد بن عبدالله، 208000 المحمدية\nGPS : https://maps.google.com/?q=33.683384,-7.409769\n\nشكراً لثقتك بنا.",lg))
            return jsonify({"status":"ok"}), 200

        elif intention == "##TEL##":
            wa_text(tel, q("Nos numeros :\n• Renault : 0523303194\n• Dacia : 0523303195\n• Email : contact@top-auto.ma\n\nMerci pour votre confiance.",
                           "أرقامنا :\n• رينو : 0523303194\n• داسيا : 0523303195\n• البريد : contact@top-auto.ma\n\nشكراً لثقتك بنا.",lg))
            return jsonify({"status":"ok"}), 200

        elif intention == "##SUIVI##":
            wa_text(tel, q("Pour le suivi travaux, commandes ou pieces, contactez le 0523303194. Un conseiller vous repondra rapidement.\n\nMerci pour votre confiance.",
                           "لمتابعة الأشغال أو الطلبيات أو القطع، اتصل على 0523303194.\n\nشكراً لثقتك بنا.",lg))
            return jsonify({"status":"ok"}), 200

        else:
            # ##INFO_VEH## ou ##GENERAL## → réponse Groq complète
            try:
                rep = groq_reponse(sess["hist"], texte, lg)
                rep = rep.strip()
                if not rep:
                    rep = q("Je n'ai pas bien compris. Pouvez-vous reformuler ?","لم أفهم جيداً. هل يمكنك إعادة الصياغة ؟",lg)
            except Exception as e:
                print(f"[GROQ ERR] {e}")
                rep = q("Erreur technique. Contactez-nous au 0523303194. Merci pour votre confiance.",
                        "خطأ تقني. اتصل على 0523303194. شكراً لثقتك بنا.",lg)

            sess["hist"].append({"role":"user","content":texte})
            sess["hist"].append({"role":"assistant","content":rep})
            if len(sess["hist"]) > 10: sess["hist"] = sess["hist"][-10:]
            wa_text(tel, rep)
            return jsonify({"status":"ok"}), 200

    except Exception as e:
        print(f"[ERREUR] {e}")
        return jsonify({"status":"error"}), 200

@app.route("/", methods=["GET"])
def home():
    return "TopAuto WhatsApp Bot v4.0 - Online", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[START] TopAuto Bot v4.0 port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
