$content = @'
"""
Configuration centrale du dashboard.
Adapte surtout la section COLUMN_MAP en fonction des vrais noms de questions
de ton formulaire Kobo (lance `python kobo_client.py --inspect` pour les lister).
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()  # charge automatiquement le fichier .env s'il existe, peu importe l'OS/terminal
except ImportError:
    pass  # python-dotenv pas installé -> on retombe sur les vraies variables d'environnement

# ---------------------------------------------------------------------------
# Connexion KoboToolbox
# ---------------------------------------------------------------------------
KOBO_BASE_URL = os.getenv("KOBO_BASE_URL", "https://eu.kobotoolbox.org")
ASSET_UID = os.getenv("KOBO_ASSET_UID", "aX2Y4fgZQ8uZRsQepPaREw")  # Activation client
SUPERVISOR_ASSET_UID = os.getenv("KOBO_SUPERVISOR_ASSET_UID", "aZhf8DGjCMArhCRPDUGmn9")  # Supervision / résumés
ENROLLMENT_ASSET_UID = os.getenv("KOBO_ENROLLMENT_ASSET_UID", "aQdfRomjDdvSCME8Ty8UmH")  # Enrôlement agents
KOBO_TOKEN = os.getenv("KOBO_TOKEN", "")  # Ton token API Kobo (obligatoire)

# Fréquence de rafraîchissement automatique des données (en secondes)
REFRESH_INTERVAL_SECONDS = int(os.getenv("REFRESH_INTERVAL_SECONDS", 2 * 60 * 60))  # 2h

# Rafraîchissement automatique de la page dans le navigateur (en millisecondes)
# Permet un affichage "vraiment live" sans avoir à cliquer sur un bouton.
AUTO_RELOAD_MS = int(os.getenv("AUTO_RELOAD_MS", 5 * 60 * 1000))  # vérifie toutes les 5 min

# Au-delà de ce délai sans nouvelle soumission, on affiche une alerte de fraîcheur
STALE_DATA_HOURS = int(os.getenv("STALE_DATA_HOURS", 24))

# Dossier de cache local (parquet) pour ne pas re-télécharger inutilement
CACHE_DIR = os.getenv("KOBO_CACHE_DIR", os.path.join(os.path.dirname(__file__), "cache"))
CACHE_FILE = os.path.join(CACHE_DIR, "activations.parquet")
LAST_FETCH_FILE = os.path.join(CACHE_DIR, "last_fetch.txt")
SUPERVISOR_CACHE_FILE = os.path.join(CACHE_DIR, "supervisions.parquet")
SUPERVISOR_LAST_FETCH_FILE = os.path.join(CACHE_DIR, "supervisions_last_fetch.txt")
ENROLLMENT_CACHE_FILE = os.path.join(CACHE_DIR, "enrollment.parquet")
ENROLLMENT_LAST_FETCH_FILE = os.path.join(CACHE_DIR, "enrollment_last_fetch.txt")

# ---------------------------------------------------------------------------
# Mapping des colonnes — Formulaire 1 : AGENT TERRAIN - RAPPORT D'ACTIVATION CLIENT
# Noms confirmés via `python kobo_client.py --schema`
# ---------------------------------------------------------------------------
COLUMN_MAP = {
    "date": "_submission_time",
    "code_parrainage": "username",                                    # identifiant agent (proxy)
    "client_telephone": "telephone",                                  # Q1 : Numéro du client (clé de dédoublonnage)
    "operateur": "nom_operateur",
    "genre": "_2_Genre",
    "categorie_socio_pro": "_3_Categorie_Socio_Professionne",
    "ville": "_8_Ville_et_quartier_ex_Bouak_Commerce",                 # Q8 : Ville et quartier du client
    "deplafonnement": "_5_deplafonnement_compte_client",               # Q5 : Oui/Non
    "transaction_effectuee": "_6_transaction_avec_le_client",          # Q6 : Oui/Non
    "montant_transaction": "_6_1_Si_Oui_Combien",                      # Q6.1 : montant si transaction
    "incident_signale": "_7_probleme_avec_le_client",                  # Q7 : Oui/Non
    "incident_detail": "_7_1_Si_oui_lequel_probleme_av",               # Q7.1 : détail texte
    "geopoint_activation": "_9_la_zone_d_activation",                  # Q9 : geopoint réel de l'activation
    "nom_agent": "username",
}

# ---------------------------------------------------------------------------
# Mapping des colonnes — Formulaire 2 : QUESTIONNAIRE DE COLLECTE - SUPERVISION
# UID : aZhf8DGjCMArhCRPDUGmn9
# ---------------------------------------------------------------------------
SUPERVISOR_COLUMN_MAP = {
    "date": "_submission_time",
    "code_parrainage_agent": "Code_de_parrainage_ex_DSA_001",
    "nom_superviseur": "Nom_du_Superviseur",
    "region": "regions",
    "localite_region": "localite_region",
    "localites_couvertes": "localites_couvertes",
    "commune_quartier": "Commune_Quartier_d_intervention",
    "nb_prospects": "Nombre_de_prospects_contact_s",
    "nb_demos": "Nombre_de_pr_sentations_d_mos_effectu_es",
    "nb_activations_confirmees": "Nombre_d_activations_compte_cr_actif",
    "nb_refus": "Nombre_de_refus_ou_d_checs",
    "type_incident": "Type_d_incident",
    "action_corrective": "Action_corrective",
}

# ---------------------------------------------------------------------------
# Mapping des colonnes — Formulaire 3 : ENROLLEMENT AGENT ACTIVATEUR DATA SURVEY
# UID : aQdfRomjDdvSCME8Ty8UmH — base de référence des agents (rôle, superviseur, équipe)
# ---------------------------------------------------------------------------
ENROLLMENT_COLUMN_MAP = {
    "date": "_submission_time",
    "code_parrainage": "CODE_PARRAINAGE",
    "numero_the_code": "NUM_RO_THE_CODE",
    "nom_prenoms": "NOM_PRENOMS",
    "role": "ROLE",
    "nom_superviseur": "NOM_DU_SUPERVISEUR",
    "region": "regions",
    "localite_region": "localite_region",
    "ville": "Ville",
    "equipe": "EQUIPE",
}

# Valeurs possibles pour la normalisation du genre (au cas où le form a des variantes)
GENRE_ALIASES = {
    "homme": "Homme", "h": "Homme", "male": "Homme", "m": "Homme",
    "femme": "Femme", "f": "Femme", "female": "Femme",
}

# Normalisation Oui/Non (déplafonnement, etc.)
OUI_NON_ALIASES = {
    "oui": "Oui", "yes": "Oui", "true": "Oui", "1": "Oui",
    "non": "Non", "no": "Non", "false": "Non", "0": "Non",
}

# ---------------------------------------------------------------------------
# Regroupement de la catégorie socio-professionnelle en 4 grands groupes.
# ⚠️ Basé sur des mots-clés (on n'a pas encore la liste exacte des choix Kobo) :
# le dashboard affiche un tableau de vérification "valeur brute -> groupe" pour
# que tu puisses valider/corriger visuellement sans repasser par le code.
# ---------------------------------------------------------------------------
# 7 grandes villes de référence — le filtre "Ville" et le graph "Activations par
# ville" se limitent à celles-ci (le reste est regroupé sous "Autres villes").
# Noms normalisés : MAJUSCULES, sans accents, tirets remplacés par des espaces.
MAJOR_CITIES = ["ABIDJAN", "BOUAKE", "DALOA", "SAN PEDRO", "YAMOUSSOUKRO", "KORHOGO", "MAN"]

SOCIO_PRO_GROUPS = {
    "Fonctionnaire": ["fonctionnaire", "agent de l'etat", "agent de l'état", "secteur public", "salarie public", "salarié public"],
    "Étudiant(e)": ["etudiant", "étudiant", "eleve", "élève", "scolaire"],
    "Secteur informel": ["informel", "commerc", "artisan", "sans emploi", "chomeur", "chômeur", "menagere", "ménagère", "agriculteur", "auto-entrepreneur", "auto entrepreneur"],
    "Secteur privé": [],  # groupe par défaut (salarié privé, employé, entrepreneur formel, autre)
}


def bucket_socio_pro(val):
    if not isinstance(val, str) or not val.strip() or val.lower() in ["nan", "none", "nat", ""]:
        return "Secteur privé"
    
    val_clean = val.strip().lower()
    
    # 1. Étudiant
    if "tudiant" in val_clean:
        return "Étudiant"
    
    # 2. Fonctionnaire
    elif "fonctionnaire" in val_clean:
        return "Fonctionnaire"
    
    # 3. Secteur informel (agriculteur, artisan, etc.)
    elif any(k in val_clean for k in ["agriculteur", "artisan", "informel"]):
        return "Secteur informel"
    
    # 4. Secteur privé (par défaut pour le reste)
    else:
        return "Secteur privé"

# Thème visuel du dashboard
THEME = {
    "primary": "#0E3B43",      # vert bancaire foncé
    "accent": "#D4AF37",       # or / gold
    "bg": "#0B0F14",
    "card_bg": "#141B22",
    "text": "#EAEAEA",
    "muted": "#9AA5B1",
    "success": "#3DDC97",
    "danger": "#FF5C5C",
}

'@
[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot "config.py"), $content, [System.Text.UTF8Encoding]::new($true))
$firstLine = Get-Content (Join-Path $PSScriptRoot "config.py") -TotalCount 1
if ($firstLine -like "*content = @*") { Write-Host "ERREUR : config.py mal ecrit !" -ForegroundColor Red } else { Write-Host "OK : config.py ecrit correctement" -ForegroundColor Green }
