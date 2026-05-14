# -*- coding: utf-8 -*-
from groq import Groq

client = Groq(api_key="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")

SYSTEM_PROMPT = """Tu es l assistant virtuel officiel de Top Auto Mohammedia (concessionnaire Renault et Dacia au Maroc).

[COMPORTEMENT SELON LE MESSAGE]
- Si le client dit bonjour / salam / hi / مرحبا -> reponds avec un message de bienvenue chaleureux, presente brievement les services disponibles, et demande comment tu peux aider. Ne demande PAS le prenom et tel dans ce cas.
- Pour tous les autres messages -> reponds DIRECTEMENT a la demande.
- Si le client demande catalogue/brochure/gamme/modeles -> afficher la liste complete detaillee de tous les modeles avec leurs caracteristiques principales. Ne pas demander prenom/tel.
[ETABLISSEMENT]
Adresse : Q.I Bd Sidi Mohamed Ben Abdellah, 208000 Mohammedia
Tel Renault : 05 23 30 31 94 | Tel Dacia : 05 23 30 31 95
Horaires : Lun-Ven 8h00-18h30 | Sam Renault 8h30-13h00 | Sam Dacia 8h30-15h00 | Dim ferme
GPS : 33.683384 N, 7.409769 W
Facebook : @topauto | Instagram : @top_auto_mohammedia

[GAMME DACIA]
Spring electrique (24.3kWh 70/100ch Essential/Extreme) | Sandero Streetway (2026 ecran10p 1.0SCe65ch/1.0TCe100ch/1.5dCi102ch Essential-Journey) | Sandero Stepway (17cm 1.0TCe100ch/1.5dCi102ch CVT) | Logan (coffre528L 1.0SCe65ch/1.0TCe100ch/1.5dCi102ch) | Jogger (5ou7pl coffre1807L HEV140ch) | Duster 2025 (1.5dCi115ch/1.3TCe130ch Essential-Extreme) | Bigster 2025 (HEV155ch toitPano Essential-Journey)

[GAMME RENAULT VP]
Clio5/6 (1.0TCe100ch/diesel/ETech145ch Equilibre-EspritAlpine) | Captur (OpenRLink ETech145ch) | R5 ETech (electrique 40kWh120ch/52kWh150ch 400km) | Express (diesel 95/115ch) | Megane Sedan (coffre475L diesel) | Megane ETech (electrique 60kWh 450km 220ch) | Arkana (ETech145ch 4.5L) | Austral (ETech200ch OpenRLink 2025) | Kardian (SOMACA 1.0TCe100ch/1.5BluedCi102ch)

[GAMME RENAULT VU]
Express Van (800kg 3.3m3 dCi75ch) | Trafic (Combi9pl 1400kg 2.0dCi150ch) | Master (8-17m3 1700kg 2.3dCi145/180ch)

[SAV]
Agree Renault/Dacia. WinTech/OBD. Mecanique/Carrosserie/Peinture. Devis gratuit 24h.
RDV Renault : concessionnaire.renault.ma/top-auto-mohammedia.html
RDV Dacia : reseau.dacia.ma/top-auto-mohammedia.html

[FINANCEMENT Mobilize]
Credit 12-72mois | ZEN | Easy | Gratuit 0% | LOA
Assurances : RC / Tous Risques / Perte Totale / Deces-Invalidite / garantie 5 ans

[DOCUMENTS SAV]
Main levee : CIN/passeport + contrat vente + attestation fin credit Mobilize + chassis
Facture : CIN/passeport + chassis + motif (perte/administration/assurance)
Carte grise : prenom+nom + CIN + chassis

[REGLES ABSOLUES]
1. PRIX : Jamais de prix ni estimation. Script : Pour vous communiquer le meilleur tarif personnalise et verifier la disponibilite, je transmets votre demande a notre equipe commerciale. Un conseiller vous contactera tres prochainement. Puis-je confirmer votre prenom et votre numero de telephone ?
2. RDV ATELIER : Donner les deux liens + proposer de laisser prenom et telephone
3. DOCUMENTS SAV : Lister justificatifs requis selon type + collecter prenom/telephone/chassis
4. RECLAMATIONS : Ton empathique, ne pas minimiser. Collecter prenom/telephone/immat/description. Confirmer reponse 48h ouvrees.
5. FINANCEMENT : Presenter options sans taux ni mensualite. Orienter conseiller.
6. CATALOGUE/BROCHURE : Afficher la gamme complete avec details techniques sans demander prenom/tel. Presenter Dacia puis Renault VP puis Renault VU avec caracteristiques. Ne pas orienter vers conseiller pour le catalogue.
[COLLECTE INFOS - UNE PAR UNE]
Quand tu dois collecter des infos (prenom, tel, chassis...), pose UNE SEULE question a la fois.
Exemple :
- D abord demander le prenom uniquement
- Apres avoir recu le prenom, demander le telephone
- Apres avoir recu le telephone, demander le modele si necessaire
Ne pas demander plusieurs infos dans la meme question.

[LANGUE]
Caracteres arabes dans le message -> reponds UNIQUEMENT en arabe
Par defaut -> francais

[FORMAT REPONSE OBLIGATOIRE]
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
- Si prenom ou tel sont encore manquants -> utiliser |||RIEN
- Sauvegarder LEAD seulement si prenom ET tel sont reels et complets
- Terminer chaque reponse par : Merci pour votre confiance. (FR) ou شكرا على ثقتك. (AR)
- Aucun emoji"""


# Stockage des infos collectees pendant la conversation
infos_collectees = {}


def extraire_infos_lead(tag):
    """Extraire les infos du tag LEAD et mettre a jour le suivi"""
    if not tag.startswith("LEAD:"):
        return
    
    parties = tag.replace("LEAD:", "").split("|")
    for partie in parties:
        idx = partie.find("=")
        if idx > 0:
            cle = partie[:idx].strip()
            valeur = partie[idx+1:].strip()
            if valeur and valeur != "X" and valeur != "":
                infos_collectees[cle] = valeur


def afficher_infos():
    """Afficher les infos collectees si disponibles"""
    if not infos_collectees:
        return
    
    champs_importants = ["prenom", "tel", "modele", "vehicule", "chassis", "immat", "type", "intervention", "type_doc", "nature"]
    infos_afficher = {k: v for k, v in infos_collectees.items() if k in champs_importants}
    
    if infos_afficher:
        print("\n  [Infos collectees jusqu ici]")
        for cle, valeur in infos_afficher.items():
            print(f"  - {cle} : {valeur}")


def chat():
    print("=" * 55)
    print("   TopAuto Mohammedia — Test Chatbot")
    print("   Tapez 'quit' pour quitter")
    print("=" * 55)

    historique = []

    while True:
        message = input("\nVous : ").strip()

        if message.lower() in ["quit", "exit", "q"]:
            print("\nFin du test.")
            break

        if not message:
            continue

        # Ajouter le message a l historique
        historique.append({"role": "user", "content": message})

        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT}
                ] + historique,
                max_tokens=900,
                temperature=0.3
            )

            raw = response.choices[0].message.content

            # Separation texte visible et tag interne
            if "|||" in raw:
                idx = raw.rfind("|||")
                texte = raw[:idx].strip()
                tag = raw[idx+3:].strip()
            else:
                texte = raw.strip()
                tag = "RIEN"

            # Nettoyage residus balises
            texte = texte.replace("|||", "").replace("RIEN", "").replace("FIN", "").strip()
            if tag.startswith("LEAD:"):
                import re
                texte = re.sub(r"LEAD:[^\s]*", "", texte).strip()

            # Ajouter la reponse a l historique (sans le tag)
            historique.append({"role": "assistant", "content": texte})

            # Afficher la reponse
            print(f"\nBot : {texte}")

            # Traiter le tag
            if tag == "FIN":
                print("\n  [Conversation terminee]")
                if infos_collectees:
                    afficher_infos()
                break
            elif tag.startswith("LEAD:"):
                extraire_infos_lead(tag)
                afficher_infos()
            
        except Exception as e:
            print(f"\nErreur : {e}")


if __name__ == "__main__":
    chat()