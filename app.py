"""
Dashboard temps réel — Activations Mansa Bank
Sources : KoboToolbox (3 formulaires)
  1. AGENT TERRAIN - RAPPORT D'ACTIVATION CLIENT   (aX2Y4fgZQ8uZRsQepPaREw)
  2. QUESTIONNAIRE DE COLLECTE - SUPERVISION        (aZhf8DGjCMArhCRPDUGmn9)
  3. ENROLLEMENT AGENT ACTIVATEUR DATA SURVEY       (aQdfRomjDdvSCME8Ty8UmH)

Lancer avec : streamlit run app.py
"""

import io
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

import config
from kobo_client import load_data, load_supervisor_data, load_enrollment_data

# =============================================================================
# CONFIGURATION DE LA PAGE + THÈME VISUEL
# =============================================================================
st.set_page_config(
    page_title="Activations Mansa Bank — Live",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

T = {
    "bg": "#F6F7FB",
    "card_bg": "#FFFFFF",
    "text": "#111827",
    "muted": "#6B7280",
    "border": "#E5E7EB",
    "accent": "#C9A227",       # or, plus profond/premium que le jaune standard
    "accent_soft": "#F4E9C8",
    "primary": "#0B1E33",      # bleu marine profond (identité bancaire)
    "secondary": "#1E3A5F",
    "success": "#0E9F6E",
    "danger": "#E02424",
    "info": "#2563EB",
}

COLOR_SEQ = [T["primary"], T["accent"], T["secondary"], T["success"], T["info"], "#8B5CF6", T["danger"]]

st.markdown(
    f"""
    <style>
    .stApp {{ background-color: {T['bg']}; color: {T['text']}; }}
    html, body, [class*="css"] {{ font-family: 'Segoe UI', 'Inter', sans-serif; }}

    [data-testid="stMetric"] {{
        background: {T['card_bg']};
        border: 1px solid {T['border']};
        border-radius: 16px;
        padding: 18px 18px 14px 18px;
        box-shadow: 0 1px 2px rgba(16,24,40,0.04), 0 1px 3px rgba(16,24,40,0.06);
    }}
    [data-testid="stMetricLabel"] {{
        color: {T['muted']} !important;
        font-weight: 600;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        font-size: 0.72rem !important;
    }}
    [data-testid="stMetricValue"] {{
        color: {T['primary']} !important;
        font-weight: 800;
        font-size: 1.5rem !important;
    }}
    h1, h2, h3, h4 {{ color: {T['text']} !important; font-weight: 700; }}

    .live-badge {{
        display: inline-block; background: rgba(14,159,110,0.1); color: {T['success']};
        border: 1px solid {T['success']}; border-radius: 999px; padding: 3px 14px;
        font-size: 0.78rem; font-weight: 700; margin-left: 10px; vertical-align: middle;
    }}
    .stale-badge {{
        display: inline-block; background: rgba(224,36,36,0.1); color: {T['danger']};
        border: 1px solid {T['danger']}; border-radius: 999px; padding: 3px 14px;
        font-size: 0.78rem; font-weight: 700; margin-left: 10px; vertical-align: middle;
    }}
    .section-title {{
        border-left: 5px solid {T['accent']}; padding: 2px 0 2px 12px;
        margin-top: 34px; margin-bottom: 10px; font-size: 1.15rem;
    }}
    .sub-title {{
        border-left: 3px solid {T['secondary']}; padding: 1px 0 1px 10px;
        margin-top: 18px; margin-bottom: 8px; font-size: 0.98rem; color: {T['muted']};
    }}
    .medal-row {{
        display: flex; justify-content: space-between; align-items: center;
        padding: 12px 16px; margin-bottom: 6px; background: {T['card_bg']};
        border-radius: 12px; border: 1px solid {T['border']};
        box-shadow: 0 1px 2px rgba(16,24,40,0.04);
    }}
    .insight-box {{
        background: linear-gradient(135deg, {T['primary']} 0%, {T['secondary']} 100%);
        color: white; border-radius: 16px; padding: 20px 24px; margin: 8px 0 24px 0;
        box-shadow: 0 4px 12px rgba(11,30,51,0.15);
    }}
    .insight-box b {{ color: {T['accent_soft']}; }}
    .team-header {{
        background: {T['primary']}; color: white; border-radius: 12px 12px 0 0;
        padding: 12px 18px; font-weight: 700; font-size: 1.02rem;
    }}
    .alert-box {{
        background: #FEF3C7; border: 1px solid #F59E0B; border-radius: 12px;
        padding: 14px 18px; margin: 10px 0; color: #78350F;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

PLOTLY_TEMPLATE = go.layout.Template()
PLOTLY_TEMPLATE.layout.paper_bgcolor = T["card_bg"]
PLOTLY_TEMPLATE.layout.plot_bgcolor = T["card_bg"]
PLOTLY_TEMPLATE.layout.font = dict(color=T["text"], family="Segoe UI, sans-serif", size=13)
PLOTLY_TEMPLATE.layout.margin = dict(t=20, b=20, l=20, r=20)
PLOTLY_TEMPLATE.layout.colorway = COLOR_SEQ


def style_fig(fig, height=360, showlegend=None):
    fig.update_layout(template=PLOTLY_TEMPLATE, height=height, margin=dict(t=20, b=20, l=10, r=10))
    if showlegend is not None:
        fig.update_layout(showlegend=showlegend)
    return fig


def plot(fig):
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, theme=None)


# Fuseau horaire local, calculé une seule fois (évite le bug de compatibilité
# pandas/Python où .astimezone() sans argument échoue sur certaines versions)
_LOCAL_TZ = datetime.now().astimezone().tzinfo


def to_local(ts):
    """Convertit un Timestamp (tz-aware ou naïf) vers l'heure locale, de façon robuste."""
    if ts is None or (hasattr(pd, "isna") and pd.isna(ts)):
        return None
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert(_LOCAL_TZ)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(_LOCAL_TZ)


# =============================================================================
# AUTO-REFRESH
# =============================================================================
st_autorefresh(interval=config.AUTO_RELOAD_MS, key="auto_reload")

# =============================================================================
# SIDEBAR — CONTRÔLES
# =============================================================================
with st.sidebar:
    st.markdown("### ⚡ Contrôles")
    if st.button("🔄 Forcer le rafraîchissement", use_container_width=True):
        st.cache_data.clear()
        st.session_state["force_refresh"] = True
    else:
        st.session_state.setdefault("force_refresh", False)
    st.caption(f"Sync auto toutes les {config.REFRESH_INTERVAL_SECONDS // 3600} h")
    st.divider()
    st.markdown("### 🔎 Filtres")

FORCE = st.session_state.get("force_refresh", False)


# =============================================================================
# CHARGEMENT DES 3 SOURCES DE DONNÉES
# =============================================================================
@st.cache_data(ttl=config.REFRESH_INTERVAL_SECONDS, show_spinner="Synchronisation des activations...")
def get_data(force: bool):
    return load_data(force_refresh=force)


@st.cache_data(ttl=config.REFRESH_INTERVAL_SECONDS, show_spinner="Synchronisation de la base d'enrôlement...")
def get_enrollment_data(force: bool):
    return load_enrollment_data(force_refresh=force)


@st.cache_data(ttl=config.REFRESH_INTERVAL_SECONDS, show_spinner="Synchronisation des données de supervision...")
def get_supervisor_data(force: bool):
    return load_supervisor_data(force_refresh=force)


df_raw, last_fetch = get_data(FORCE)
enr_df, enr_last_fetch = get_enrollment_data(FORCE)
sup_df, sup_last_fetch = get_supervisor_data(FORCE)
st.session_state["force_refresh"] = False

if df_raw.empty:
    st.warning("Aucune donnée disponible. Vérifie ta configuration Kobo.")
    st.stop()

nb_total_kobo = len(df_raw)  # nombre brut de soumissions dans Kobo, avant tout filtre/traitement

# --- Règle métier : activité comptabilisée à partir du 15 août 2026 ---
# Comparaison sur la DATE seule (pas le timestamp complet) pour éviter tout
# souci de fuseau horaire qui pourrait exclure des activations du 1er jour.
DATE_DEBUT = pd.Timestamp("2026-08-15").date()
if "date" in df_raw.columns:
    df_raw["date"] = pd.to_datetime(df_raw["date"], errors="coerce")
    df = df_raw[df_raw["date"].dt.date >= DATE_DEBUT].copy()
    if df.empty:
        df = df_raw.copy()
else:
    df = df_raw.copy()

nb_apres_debut = len(df)

# =============================================================================
# NETTOYAGE — VILLE DU CLIENT (Question 8)
# =============================================================================
target_col = None
for col in df.columns:
    if "ville" in col.lower() or "quartier" in col.lower():
        target_col = col
        break
if not target_col:
    text_cols = [c for c in df.columns if df[c].dtype == "object"]
    target_col = text_cols[0] if text_cols else df.columns[0]


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def clean_city(val):
    if pd.isna(val):
        return "Non renseigné"
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ["nan", "none", "", "nat"]:
        return "Non renseigné"
    city = val_str.split(",")[0].strip().split("/")[0].strip().upper()
    city = strip_accents(city).replace("-", " ").strip()
    return city if city else "Non renseigné"


def to_major_city(city):
    """Vcherche si l'une des 7 grandes villes est contenue dans le texte de l'agent."""
    if not isinstance(city, str):
        return "Autres villes"
    c_upper = city.upper()
    for major in config.MAJOR_CITIES:
        if major in c_upper:
            return major
    return "Autres villes"


df["ville_propre"] = df[target_col].apply(clean_city)
df["ville_groupe"] = df["ville_propre"].apply(to_major_city)
loc_col = "ville_propre"        # utilisé pour la carte GPS (précision géographique réelle)
loc_col_group = "ville_groupe"  # utilisé pour le filtre, le KPI et le graph "par ville"

df["date_only"] = df["date"].dt.date if "date" in df.columns else pd.NaT
df["hour"] = df["date"].dt.hour if "date" in df.columns else 0
df["weekday"] = df["date"].dt.day_name() if "date" in df.columns else ""

agent_col = next(
    (c for c in df.columns if c in ["_submitted_by", "username"] or "agent" in c.lower() or "user" in c.lower()),
    None,
)

# =============================================================================
# JOINTURE AVEC LA BASE D'ENRÔLEMENT — faite AVANT le dédoublonnage, pour que le
# rapport de doublons/fraude puisse afficher le nom de l'agent, sa ville, son équipe.
#
# Le code parrainage = partie du username APRÈS le "/" (ex: "David/79FE16" -> "79FE16"),
# UNIQUEMENT si cette partie ressemble vraiment à un code (6 caractères hexadécimaux) :
# sinon on ne tente MÊME PAS le rapprochement, le username brut est juste affiché tel quel.
# =============================================================================
CODE_PATTERN = re.compile(r"^[0-9A-F]{6}$")


def extract_code(username):
    """
    Extrait le code parrainage (6 caractères alphanumériques) depuis le username
    de l'agent, quel que soit le séparateur utilisé sur le terrain :
    "Nom/CODE", "Nom-CODE", "Nom CODE", "CODE/Nom", "CODE-Nom", "CODE Nom", etc.
    """
    if not isinstance(username, str) or not username.strip():
        return None
    raw = username.strip().upper()
    # Confusion fréquente en saisie manuelle : la lettre "O" tapée à la place
    # du chiffre "0" (ex: "YAPO/60DDEO" au lieu de "60DDE0"). On normalise
    # avant de chercher le code, pour ne rater aucune correspondance valide.
    raw = raw.replace("O", "0")

    # 1. Découpage sur les séparateurs usuels (/, -, espace) — on cherche le
    #    morceau qui correspond exactement au format d'un code (6 caractères).
    parts = [p.strip() for p in re.split(r"[/\-\s]+", raw) if p.strip()]
    candidates = [p for p in parts if CODE_PATTERN.match(p)]
    if candidates:
        return candidates[-1]

    # 2. Repli : pas de séparateur exploitable -> on cherche un bloc de 6
    #    caractères alphanumériques n'importe où dans la chaîne.
    fallback_matches = re.findall(r"[0-9A-F]{6}", raw)
    if fallback_matches:
        return fallback_matches[-1]

    return None


df["code_agent"] = df[agent_col].apply(extract_code) if agent_col else None
df["_username_brut"] = df[agent_col] if agent_col else None

ROLE_SUPERVISEUR_KW = "superviseur"


def clean_supervisor_name(raw_name):
    """
    Nettoie les valeurs brutes Kobo au format "nom___ville" (choix mal étiquetés)
    et fusionne automatiquement l'ANCIEN superviseur d'une zone avec le NOUVEAU
    officiel (config.VILLE_SUPERVISEUR_FALLBACK) — toutes les activations de
    l'équipe reviennent alors au nouveau responsable de la zone.
    """
    if not isinstance(raw_name, str) or not raw_name.strip():
        return raw_name
    if "___" in raw_name:
        parts = raw_name.split("___")
        name_part = parts[0].replace("_", " ").strip().title()
        city_part = parts[-1].replace("_", " ").replace("-", " ").strip().upper()
        if city_part in config.VILLE_SUPERVISEUR_FALLBACK:
            return config.VILLE_SUPERVISEUR_FALLBACK[city_part]
        return name_part
    return raw_name.strip()


def clean_equipe_name(raw_equipe):
    """
    Normalise le nom d'équipe (espaces/underscores/tirets/casse) pour que chaque
    zone n'apparaisse qu'une seule fois (ex: "daloa", "DALOA", "Daloa" -> "Daloa").
    Ne fusionne PAS les équipes numérotées entre elles (Bouaké 1 reste distinct
    de Bouaké 2).
    """
    if not isinstance(raw_equipe, str) or not raw_equipe.strip():
        return raw_equipe
    name = raw_equipe.replace("_", " ").replace("-", " ").strip()
    name = " ".join(name.split())  # espaces multiples -> un seul
    return name.title()


if not enr_df.empty:
    enr_df["code_parrainage"] = enr_df["code_parrainage"].astype(str).str.strip().str.upper()
    enr_df["role"] = enr_df["role"].fillna("")
    enr_df["nom_superviseur"] = enr_df["nom_superviseur"].apply(clean_supervisor_name)
    enr_df["equipe"] = enr_df["equipe"].apply(clean_equipe_name)

    # Correction de rôle pour les superviseurs connus dont le champ ROLE Kobo
    # n'est pas fiable (voir config.SUPERVISOR_ROLE_OVERRIDES)
    for _sup_name in config.SUPERVISOR_ROLE_OVERRIDES:
        _mask = enr_df["nom_prenoms"].str.upper().str.contains(_sup_name, na=False)
        enr_df.loc[_mask, "role"] = "superviseur"

    is_supervisor_role = enr_df["role"].str.lower().str.contains(ROLE_SUPERVISEUR_KW, na=False)
    commerciaux_df = enr_df[~is_supervisor_role].drop_duplicates(subset="code_parrainage", keep="last")
    superviseurs_df = enr_df[is_supervisor_role].drop_duplicates(subset="code_parrainage", keep="last")
    codes_enrolles_commerciaux = set(commerciaux_df["code_parrainage"].dropna().unique())
    sup_code_lookup = {
        str(k).strip().upper(): v
        for k, v in superviseurs_df.set_index("nom_prenoms")["code_parrainage"].to_dict().items()
    }

    df = df.merge(
        enr_df[["code_parrainage", "nom_prenoms", "nom_superviseur", "equipe", "role", "ville", "region"]]
        .rename(columns={"ville": "agent_ville"}),
        left_on="code_agent", right_on="code_parrainage", how="left",
    )
    df["nom_superviseur"] = df["nom_superviseur"].fillna("Non assigné")
    df["equipe"] = df["equipe"].fillna("Non assignée")
    df["region"] = df["region"].fillna("Non renseignée")
    # Code non matché (ou pas exploitable) -> on affiche le username brut tel quel, sans forcer un lien
    df["nom_prenoms"] = df["nom_prenoms"].fillna(df["_username_brut"].fillna("Inconnu"))

    # Filet de sécurité : pour les agents toujours "Non assigné" après le matching
    # par code, on déduit leur superviseur via la ville du client (table de
    # correspondance connue), plutôt que de les laisser sans superviseur.
    mask_non_assigne = df["nom_superviseur"] == "Non assigné"
    fallback_sup = df.loc[mask_non_assigne, "ville_propre"].map(config.VILLE_SUPERVISEUR_FALLBACK)
    df.loc[mask_non_assigne, "nom_superviseur"] = df.loc[mask_non_assigne, "nom_superviseur"].where(
        fallback_sup.isna(), fallback_sup
    )
    df.loc[mask_non_assigne & fallback_sup.notna(), "equipe"] = df.loc[
        mask_non_assigne & fallback_sup.notna(), "ville_propre"
    ].str.title()
else:
    commerciaux_df, superviseurs_df = pd.DataFrame(), pd.DataFrame()
    codes_enrolles_commerciaux, sup_code_lookup = set(), {}
    df["nom_superviseur"] = "Non assigné"
    df["equipe"] = "Non assignée"
    df["nom_prenoms"] = df["_username_brut"]
    df["agent_ville"] = None
    df["region"] = "Non renseignée"
    df["role"] = None

# Colonne d'affichage sûre : "code_agent" reste None pour les codes non identifiés
# (utilisé pour les vrais calculs de correspondance avec l'enrôlement), mais pour
# TOUS les tableaux groupés par agent, on utilise cette version qui ne fait jamais
# disparaître silencieusement une ligne (pandas groupby ignore les None par défaut).
df["code_agent_display"] = df["code_agent"].fillna("Non identifié")

# =============================================================================
# DOUBLONS & FRAUDE — un client (numéro de téléphone) = une activation.
# Capturé AVANT dédoublonnage, avec le nom/ville/équipe de chaque agent impliqué.
#   - Doublon  : le même numéro apparaît plus d'une fois.
#   - Fraude   : le même numéro apparaît plus de deux fois (signal fort à vérifier).
# =============================================================================
nb_avant_dedup = len(df)
doublons_detail = pd.DataFrame()
fraude_detail = pd.DataFrame()

if "client_telephone" in df.columns:
    df = df.sort_values("date")
    has_phone = df["client_telephone"].astype(str).str.strip().replace({"None": "", "nan": ""}) != ""
    df_avec_tel = df[has_phone].copy()
    df_sans_tel = df[~has_phone].copy()

    occ_par_numero = df_avec_tel.groupby("client_telephone").size()
    numeros_doublons = occ_par_numero[occ_par_numero > 1].index
    numeros_fraude = occ_par_numero[occ_par_numero > 2].index

    if len(numeros_doublons) > 0:
        doublons_detail = (
            df_avec_tel[df_avec_tel["client_telephone"].isin(numeros_doublons)]
            .groupby(["client_telephone", "code_agent", "nom_prenoms", "agent_ville", "equipe"])
            .size().reset_index(name="nb_fois")
            .sort_values(["client_telephone", "nb_fois"], ascending=[True, False])
        )
    if len(numeros_fraude) > 0:
        fraude_detail = (
            df_avec_tel[df_avec_tel["client_telephone"].isin(numeros_fraude)]
            .groupby(["client_telephone", "code_agent", "nom_prenoms", "agent_ville", "equipe", "nom_superviseur"])
            .size().reset_index(name="nb_fois")
            .sort_values("nb_fois", ascending=False)
        )

    # Règle de dédoublonnage : on garde la soumission où déplafonnement = "Oui"
    # (la plus récente s'il y en a plusieurs) ; à défaut, la soumission la plus récente.
    def pick_best(group):
        deplaf_oui = group[group["deplafonnement"] == "Oui"]
        return deplaf_oui.iloc[-1] if not deplaf_oui.empty else group.iloc[-1]

    if not df_avec_tel.empty:
        df_avec_tel = df_avec_tel.groupby("client_telephone", group_keys=False).apply(pick_best)
    df = pd.concat([df_avec_tel, df_sans_tel]).sort_values("date").reset_index(drop=True)

nb_doublons_supprimes = nb_avant_dedup - len(df)

# =============================================================================
# GÉOLOCALISATION (zone réelle d'activation Q9, sinon repli approximatif autour d'Abidjan)
# On distingue les points GPS RÉELS (_has_real_geo) des points approximatifs,
# pour ne jamais afficher un point simulé comme si c'était une position réelle.
# =============================================================================
lat_col = next((c for c in df.columns if "lat" in c.lower()), None)
lon_col = next((c for c in df.columns if "lon" in c.lower()), None)
np.random.seed(42)


def _to_float(v):
    try:
        f = float(v)
        return f if pd.notna(f) else None
    except (TypeError, ValueError):
        return None


df["_real_lat"] = df[lat_col].apply(_to_float) if lat_col else None
df["_real_lon"] = df[lon_col].apply(_to_float) if lon_col else None
df["_has_real_geo"] = df["_real_lat"].notna() & df["_real_lon"].notna()

df["_lat"] = df["_real_lat"].where(
    df["_has_real_geo"], 5.3200 + np.random.normal(0, 0.05, len(df))
)
df["_lon"] = df["_real_lon"].where(
    df["_has_real_geo"], -4.0200 + np.random.normal(0, 0.05, len(df))
)

now_utc = datetime.now(timezone.utc)
today = now_utc.date()
yesterday = today - timedelta(days=1)

last_submission = df["date"].max() if "date" in df.columns and pd.notna(df["date"].max()) else None
hours_since_last_submission = (now_utc - last_submission).total_seconds() / 3600 if last_submission else None
is_stale = hours_since_last_submission is not None and hours_since_last_submission > config.STALE_DATA_HOURS

# =============================================================================
# FILTRES GLOBAUX (sidebar)
# =============================================================================
valid_dates_all = df["date_only"].dropna()
min_date = valid_dates_all.min() if not valid_dates_all.empty else today
max_date = valid_dates_all.max() if not valid_dates_all.empty else today

with st.sidebar:
    st.markdown("### 🌐 Filtres globaux")

    quick_period = st.radio(
        "Période",
        ["Depuis le 15 août", "Cette semaine", "Hier", "Aujourd'hui"],
        horizontal=True,
        key="quick_period",
    )

    if quick_period == "Aujourd'hui":
        date_range = (today, today)
        st.caption(f"Filtré sur le {today.strftime('%d/%m/%Y')} uniquement.")
    elif quick_period == "Hier":
        date_range = (yesterday, yesterday)
        st.caption(f"Filtré sur le {yesterday.strftime('%d/%m/%Y')} uniquement.")
    elif quick_period == "Cette semaine":
        week_start = today - timedelta(days=today.weekday())  # lundi de cette semaine
        date_range = (week_start, today)
        st.caption(f"Filtré du {week_start.strftime('%d/%m/%Y')} au {today.strftime('%d/%m/%Y')}.")
    else:
        date_range = st.date_input("Période personnalisée", value=(min_date, max_date))

    loc_options = config.MAJOR_CITIES + (["Autres villes"] if (df[loc_col_group] == "Autres villes").any() else [])
    loc_sel = st.multiselect("Ville (7 principales)", loc_options, default=[])

    equipes = sorted(str(e) for e in df["equipe"].dropna().unique() if e != "Non assignée")
    equipe_sel = st.multiselect("Équipe", equipes, default=[])

    operateurs = sorted(str(o) for o in df["operateur"].dropna().unique()) if "operateur" in df.columns else []
    op_sel = st.multiselect("Opérateur", operateurs, default=[])

fdf_no_date = df.copy()
if loc_sel:
    fdf_no_date = fdf_no_date[fdf_no_date[loc_col_group].astype(str).isin(loc_sel)]
if op_sel:
    fdf_no_date = fdf_no_date[fdf_no_date["operateur"].astype(str).isin(op_sel)]
if equipe_sel:
    fdf_no_date = fdf_no_date[fdf_no_date["equipe"].astype(str).isin(equipe_sel)]

if isinstance(date_range, tuple) and len(date_range) == 2:
    d_start, d_end = date_range
else:
    d_start, d_end = min_date, max_date

fdf = fdf_no_date[(fdf_no_date["date_only"] >= d_start) & (fdf_no_date["date_only"] <= d_end)]

# --- Période précédente équivalente, pour comparaison automatique (peu importe le filtre actif) ---
period_len = (d_end - d_start).days + 1
prev_start = d_start - timedelta(days=period_len)
prev_end = d_start - timedelta(days=1)
fdf_prev = fdf_no_date[(fdf_no_date["date_only"] >= prev_start) & (fdf_no_date["date_only"] <= prev_end)]

if quick_period == "Aujourd'hui":
    period_label = "aujourd'hui"
    period_label_prev = "vs hier"
elif quick_period == "Hier":
    period_label = "hier"
    period_label_prev = "vs avant-hier"
elif quick_period == "Cette semaine":
    period_label = "cette semaine"
    period_label_prev = "vs semaine dernière"
else:
    period_label = "sur la période"
    period_label_prev = "vs période précédente équivalente"

# --- Données SUPERVISION filtrées sur la même période que le filtre actif ---
# (utilisées par l'entonnoir de conversion et la réconciliation déclaré/confirmé)
if not sup_df.empty:
    sup_df["date_only_sup"] = pd.to_datetime(sup_df["date"], errors="coerce").dt.date
    sup_periode = sup_df[(sup_df["date_only_sup"] >= d_start) & (sup_df["date_only_sup"] <= d_end)]
else:
    sup_periode = sup_df

# =============================================================================
# EN-TÊTE
# =============================================================================
col_title, col_status = st.columns([3, 1])
with col_title:
    badge = "<span class='stale-badge'>⚠ DONNÉES ANCIENNES</span>" if is_stale else "<span class='live-badge'>● LIVE</span>"
    st.markdown(f"# Activations Clients — Mansa Bank {badge}", unsafe_allow_html=True)
    st.caption(
        f"Données comptabilisées depuis le 15 août 2026 · "
        f"Dernière synchro activations : {to_local(last_fetch).strftime('%d/%m/%Y %H:%M')}"
        + (f" · {nb_doublons_supprimes} doublon(s) client supprimé(s)" if nb_doublons_supprimes else "")
    )
    if is_stale:
        st.error(
            f"Aucune nouvelle activation depuis {hours_since_last_submission:.0f}h "
            f"(dernière soumission le {to_local(last_submission).strftime('%d/%m %H:%M')})."
        )
    with st.expander("🔍 D'où vient le total affiché ? (diagnostic du comptage)"):
        st.markdown(
            f"""
            1. **Soumissions brutes dans Kobo** (formulaire Activation, tout historique) : **{nb_total_kobo:,}**
            2. **Après filtre "depuis le 15 août 2026"** : **{nb_apres_debut:,}**
            3. **Après dédoublonnage** (1 numéro client = 1 activation) : **{nb_apres_debut - nb_doublons_supprimes:,}**
               ({nb_doublons_supprimes} doublon(s) supprimé(s))
            """.replace(",", " ")
        )
        st.caption(
            "Si le nombre attendu (ex: 1000+) est supérieur à la ligne 1 ci-dessus, "
            "ça veut dire que ces soumissions ne sont pas encore dans Kobo lui-même — "
            "vérifie directement sur eu.kobotoolbox.org (onglet Data > Table) le nombre "
            "total de lignes du formulaire. Si Kobo a bien 1000+ lignes mais que la ligne "
            "1 ci-dessus est inférieure, dis-le moi : ce serait un vrai bug de récupération."
        )
with col_status:
    st.metric("Actualisé", to_local(last_fetch).strftime("%H:%M"))

# =============================================================================
# KPIs — VUE D'ENSEMBLE (100% réactifs aux filtres actifs : période, ville, équipe, opérateur)
# =============================================================================
total_global = len(df)
total_filtre = len(fdf)
delta_filtre = total_filtre - len(fdf_prev)

top_ville = fdf[loc_col_group].value_counts().idxmax() if not fdf[loc_col_group].dropna().empty else "—"
top_ville_count = int(fdf[loc_col_group].value_counts().max()) if not fdf[loc_col_group].dropna().empty else 0

agent_periode = fdf.groupby(["code_agent", "nom_prenoms"]).size()
agent_prev = fdf_prev.groupby(["code_agent", "nom_prenoms"]).size()
if not agent_periode.empty:
    (best_code, best_name), best_count_periode = agent_periode.idxmax(), int(agent_periode.max())
    best_count_prev = int(agent_prev.get((best_code, best_name), 0))
    best_agent_label = f"{best_name} ({best_code})"
    best_agent_delta = f"{best_count_periode - best_count_prev:+d} {period_label_prev}"
else:
    best_agent_label, best_agent_delta = "—", ""

k1, k2, k3, k4 = st.columns(4)
k1.metric(f"Activations ({period_label})", f"{total_filtre:,}".replace(",", " "), delta=f"{delta_filtre:+d} {period_label_prev}")
k2.metric("Ville n°1 (sélection)", top_ville, f"{top_ville_count} activations")
k3.metric("Meilleur agent (sélection)", best_agent_label, best_agent_delta)
k4.metric("Activations totales (depuis le 15 août)", f"{total_global:,}".replace(",", " "))

# =============================================================================
# RÉSUMÉ EXÉCUTIF
# =============================================================================
codes_actifs = set(fdf["code_agent"].dropna().unique())
codes_matches = codes_actifs & codes_enrolles_commerciaux
codes_actifs_non_enrolles = codes_actifs - set(enr_df["code_parrainage"].dropna().unique()) if not enr_df.empty else set()

taux_deploiement_txt = ""
if commerciaux_df is not None and len(commerciaux_df) > 0:
    taux = 100 * len(codes_matches) / len(codes_enrolles_commerciaux) if codes_enrolles_commerciaux else 0
    taux_deploiement_txt = f" Le taux de déploiement des AVD ({period_label}) est de <b>{taux:.0f}%</b>."

st.markdown(
    f"""
    <div class="insight-box">
    <b>{total_filtre}</b> activations {period_label} ({delta_filtre:+d} {period_label_prev}), pour un total de
    <b>{total_global:,}</b> activations depuis le 15 août.
    La ville la plus active est <b>{top_ville}</b> ({top_ville_count} activations).{taux_deploiement_txt}
    </div>
    """.replace(",", " "),
    unsafe_allow_html=True,
)

# =============================================================================
# EFFECTIFS AVD (Commerciaux) — réactifs à la période sélectionnée
# "Actif" = au moins une activation sur la période filtrée (pas tout l'historique).
# =============================================================================
st.markdown(f"<h3 class='section-title'>Effectifs AVD (Commerciaux) — {period_label}</h3>", unsafe_allow_html=True)

effectif_prevu = len(codes_enrolles_commerciaux)
effectif_deploye = len(codes_matches)
effectif_non_actif = max(effectif_prevu - effectif_deploye, 0)
taux_deploiement = (100 * effectif_deploye / effectif_prevu) if effectif_prevu else 0
nb_non_enrolles = len(codes_actifs_non_enrolles)

e1, e2, e3, e4, e5 = st.columns(5)
e1.metric("AVD prévus", effectif_prevu, help="Nombre de commerciaux enregistrés dans la base d'enrôlement.")
e2.metric("AVD déployés (actifs)", effectif_deploye, help=f"Ont fait au moins une activation {period_label}.")
e3.metric("AVD non actifs", effectif_non_actif)
e4.metric("Taux de déploiement", f"{taux_deploiement:.0f} %")
e5.metric("Actifs non enregistrés", nb_non_enrolles)

if not enr_df.empty:
    st.caption(
        f"Rôles détectés dans l'enrôlement : {', '.join(sorted(set(enr_df['role'].dropna().unique())) or ['—'])} "
        f"· Dernière synchro enrôlement : {to_local(enr_last_fetch).strftime('%d/%m/%Y %H:%M')}"
    )
    if effectif_prevu and effectif_deploye < 0.2 * effectif_prevu and quick_period != "Depuis le 15 août":
        st.info(
            f"Seuls {effectif_deploye} AVD sur {effectif_prevu} ont une activation {period_label} — "
            f"normal pour une vue journalière si tous les agents n'ont pas encore soumis."
        )

# --- AVD actifs (avec noms), sur la période sélectionnée ---
if not commerciaux_df.empty:
    actifs_df = (
        fdf[fdf["code_agent"].isin(codes_matches)]
        .groupby(["code_agent", "nom_prenoms", "nom_superviseur", "equipe"])
        .size().reset_index(name="Activations")
        .sort_values("Activations", ascending=False)
    )
    if not actifs_df.empty:
        with st.expander(f"🟢 AVD actifs Enrolle {period_label} — {len(actifs_df)} agent(s)", expanded=False):
            st.dataframe(
                actifs_df.rename(columns={
                    "code_agent": "Code", "nom_prenoms": "Nom & Prénoms",
                    "nom_superviseur": "Superviseur", "equipe": "Équipe",
                }),
                use_container_width=True, hide_index=True,
            )

# --- AVD non actifs (avec noms), sur la période sélectionnée ---
if not commerciaux_df.empty:
    non_actifs_df = commerciaux_df[~commerciaux_df["code_parrainage"].isin(codes_actifs)][
        ["code_parrainage", "nom_prenoms", "nom_superviseur", "equipe", "ville"]
    ]
    if not non_actifs_df.empty:
        with st.expander(f"🔴 AVD non actifs Enrolle {period_label} — {len(non_actifs_df)} agent(s)"):
            st.dataframe(
                non_actifs_df.rename(columns={
                    "code_parrainage": "Code", "nom_prenoms": "Nom & Prénoms",
                    "nom_superviseur": "Superviseur", "equipe": "Équipe", "ville": "Ville",
                }),
                use_container_width=True, hide_index=True,
            )

# --- Agents actifs mais NON enregistrés (alerte qualité) ---
if nb_non_enrolles > 0:
    non_enrolles_counts = (
        fdf[fdf["code_agent"].isin(codes_actifs_non_enrolles)]
        .groupby("code_agent").size().reset_index(name="Activations")
        .sort_values("Activations", ascending=False)
    )
    st.markdown(
        f"""<div class="alert-box">
        ⚠️ <b>{nb_non_enrolles} agent(s) actif(s) {period_label} ne sont pas enregistrés</b> dans la base d'enrôlement.
        Merci de rappeler aux superviseurs concernés de faire enregistrer ces agents.
        </div>""",
        unsafe_allow_html=True,
    )
    with st.expander("Voir les codes agents non enregistrés"):
        st.dataframe(non_enrolles_counts.rename(columns={"code_agent": "Code agent (non reconnu)"}),
                     use_container_width=True, hide_index=True)

# =============================================================================
# ACTIVATIONS & DÉPLAFONNEMENT PAR AVD (base unique-client, sur la période)
# =============================================================================
st.markdown("<h3 class='section-title'>Activations & déplafonnement par AVD</h3>", unsafe_allow_html=True)
if not fdf.empty:
    avd_deplaf = (
        fdf.groupby(["code_agent_display", "nom_prenoms", "equipe"])
        .agg(Activations=("submission_id", "count"), Deplafonnements=("deplafonnement", lambda s: (s == "Oui").sum()))
        .reset_index()
        .sort_values("Activations", ascending=False)
    )
    activations_safe = avd_deplaf["Activations"].where(avd_deplaf["Activations"] > 0, other=1)
    taux = (avd_deplaf["Deplafonnements"] / activations_safe * 100).round(1)
    avd_deplaf["Taux déplafonnement"] = taux.astype(str) + " %"
    st.dataframe(
        avd_deplaf.rename(columns={"code_agent_display": "Code", "nom_prenoms": "Nom & Prénoms", "equipe": "Équipe"}),
        use_container_width=True, hide_index=True, height=320,
    )

# =============================================================================
# RÉCAPITULATIF QUOTIDIEN PAR AVD, PAR SUPERVISEUR (tableau croisé)
# Code, nom & prénom, ville, équipe, puis une colonne par date avec le nombre
# d'activations de ce jour-là, trié par superviseur.
# =============================================================================
st.markdown("<h3 class='section-title'>Récapitulatif quotidien par AVD (par superviseur)</h3>", unsafe_allow_html=True)

if not fdf.empty:
    pivot_source = fdf.copy()
    pivot_source["Ville"] = pivot_source["agent_ville"].fillna("Non renseignée")

    daily_pivot = pivot_source.pivot_table(
        index=["nom_superviseur", "code_agent_display", "nom_prenoms", "Ville", "equipe"],
        columns="date_only",
        values="submission_id",
        aggfunc="count",
        fill_value=0,
    )
    daily_pivot = daily_pivot.reindex(sorted(daily_pivot.columns), axis=1)
    daily_pivot["Total"] = daily_pivot.sum(axis=1)

    # Colonnes de dates en format lisible (dd/mm)
    daily_pivot.columns = [c.strftime("%d/%m") if hasattr(c, "strftime") else c for c in daily_pivot.columns]

    daily_pivot = daily_pivot.reset_index().sort_values(
        ["nom_superviseur", "Total"], ascending=[True, False]
    )
    daily_pivot = daily_pivot.rename(columns={
        "nom_superviseur": "Superviseur", "code_agent_display": "Code", "nom_prenoms": "Nom & Prénoms", "equipe": "Équipe",
    })

    st.dataframe(daily_pivot, use_container_width=True, hide_index=True, height=450)

    csv_pivot = daily_pivot.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Télécharger ce récapitulatif (CSV)", csv_pivot,
        "recap_quotidien_avd_par_superviseur.csv", "text/csv",
    )
    st.caption(
        "Chaque colonne de date = nombre d'activations de cet AVD ce jour-là. "
        "Reflète le filtre « Période » actif dans les filtres globaux."
    )
else:
    st.caption("Aucune activation sur la période sélectionnée.")

# =============================================================================
# 🚩 DOUBLONS & FRAUDE POTENTIELLE (tout l'historique depuis le 15 août,
# indépendant du filtre période — un pattern de fraude se regarde sur la durée)
# =============================================================================
st.markdown("<h3 class='section-title'>🚩 Doublons & fraude potentielle</h3>", unsafe_allow_html=True)

rename_dup = {
    "client_telephone": "Numéro client", "code_agent": "Code agent", "nom_prenoms": "Nom & Prénoms",
    "agent_ville": "Ville agent", "equipe": "Équipe", "nom_superviseur": "Superviseur", "nb_fois": "Nb de fois",
}

if not fraude_detail.empty:
    st.error(
        f"⚠️ {fraude_detail['client_telephone'].nunique()} numéro(s) client utilisé(s) plus de 2 fois "
        f"pour déclarer une activation — à vérifier en priorité."
    )
    st.dataframe(fraude_detail.rename(columns=rename_dup), use_container_width=True, hide_index=True)
else:
    st.success("Aucun cas de fraude potentielle détecté (numéro client réutilisé plus de 2 fois).")

if not doublons_detail.empty:
    with st.expander(f"Voir tous les doublons ({doublons_detail['client_telephone'].nunique()} numéro(s) concerné(s))"):
        st.dataframe(doublons_detail.rename(columns=rename_dup), use_container_width=True, hide_index=True)

# =============================================================================
# OBJECTIF MENSUEL & TRANSACTIONS
# =============================================================================
st.markdown("<h3 class='section-title'>Transactions & Objectif mensuel</h3>", unsafe_allow_html=True)

month_start = today.replace(day=1)
df_month = df[(df["date_only"] >= month_start) & (df["date_only"] <= today)]
nb_transactions_mois = int((df_month["transaction_effectuee"] == "Oui").sum()) if "transaction_effectuee" in df.columns else 0
objectif_mensuel = 25000

gc1, gc2 = st.columns([1.3, 1])
with gc1:
    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=nb_transactions_mois,
        number={"font": {"color": T["primary"], "size": 40}},
        delta={"reference": objectif_mensuel, "increasing": {"color": T["success"]}, "decreasing": {"color": T["danger"]}},
        title={"text": f"Transactions ce mois — Objectif : {objectif_mensuel:,}".replace(",", " "), "font": {"size": 15}},
        gauge={
            "axis": {"range": [0, objectif_mensuel], "tickcolor": T["muted"]},
            "bar": {"color": T["accent"]},
            "bgcolor": T["bg"],
            "borderwidth": 0,
            "steps": [
                {"range": [0, objectif_mensuel * 0.5], "color": "#FEE2E2"},
                {"range": [objectif_mensuel * 0.5, objectif_mensuel * 0.85], "color": "#FEF3C7"},
                {"range": [objectif_mensuel * 0.85, objectif_mensuel], "color": "#DCFCE7"},
            ],
            "threshold": {"line": {"color": T["primary"], "width": 3}, "value": objectif_mensuel},
        },
    ))
    style_fig(fig_gauge, height=300)
    plot(fig_gauge)

with gc2:
    montant_total = fdf["montant_transaction"].sum() if "montant_transaction" in fdf.columns else 0
    taux_transac = (
        fdf["transaction_effectuee"].value_counts(normalize=True).mul(100).round(1).get("Oui", 0)
        if "transaction_effectuee" in fdf.columns and not fdf["transaction_effectuee"].dropna().empty else 0
    )
    st.metric("Montant total des transactions", f"{montant_total:,.0f} FCFA".replace(",", " "))
    st.metric("Taux de transaction effectuée", f"{taux_transac:.1f} %")
    reste = max(objectif_mensuel - nb_transactions_mois, 0)
    st.metric("Reste à faire ce mois", f"{reste:,}".replace(",", " "))

if "montant_transaction" in fdf.columns and fdf["montant_transaction"].notna().any():
    st.markdown("<div class='sub-title'>Montant des transactions par opérateur</div>", unsafe_allow_html=True)
    montant_par_op = fdf.groupby("operateur")["montant_transaction"].sum().reset_index().sort_values("montant_transaction", ascending=False)
    fig_montant_op = px.bar(montant_par_op, x="operateur", y="montant_transaction", text="montant_transaction")
    fig_montant_op.update_traces(marker_color=T["accent"], texttemplate="%{text:,.0f}", textposition="outside")
    fig_montant_op.update_yaxes(title="Montant (FCFA)")
    fig_montant_op.update_xaxes(title=None)
    style_fig(fig_montant_op, height=320)
    plot(fig_montant_op)

# =============================================================================
# ÉVOLUTION DES ACTIVATIONS
# =============================================================================
st.markdown("<h3 class='section-title'>Évolution des activations</h3>", unsafe_allow_html=True)
daily = fdf.groupby("date_only").size().reset_index(name="activations")
fig_line = px.area(daily, x="date_only", y="activations")
fig_line.update_traces(line_color=T["accent"], line_width=3, fillcolor="rgba(201,162,39,0.12)")
fig_line.update_xaxes(title=None)
fig_line.update_yaxes(title="Activations")
style_fig(fig_line, height=320)
plot(fig_line)

# --- Courbe cumulée (trajectoire de croissance depuis le 15 août) ---
daily_cumul = daily.sort_values("date_only").copy()
daily_cumul["cumul"] = daily_cumul["activations"].cumsum()
fig_cumul = go.Figure()
fig_cumul.add_trace(go.Scatter(
    x=daily_cumul["date_only"], y=daily_cumul["cumul"], mode="lines+markers",
    line=dict(color=T["primary"], width=3), marker=dict(size=5, color=T["primary"]),
    fill="tozeroy", fillcolor="rgba(11,30,51,0.06)", name="Cumul",
))
fig_cumul.update_layout(yaxis_title="Activations cumulées", xaxis_title=None)
style_fig(fig_cumul, height=300)
st.markdown("<div class='sub-title'>Trajectoire cumulée depuis le 15 août</div>", unsafe_allow_html=True)
plot(fig_cumul)

# =============================================================================
# CARTE — CONCENTRATION DES ACTIVATIONS PAR ZONE
# =============================================================================
st.markdown("<h3 class='section-title'>Concentration géographique des activations</h3>", unsafe_allow_html=True)

nb_geo_reels = int(fdf["_has_real_geo"].sum())
map_mode = st.radio(
    "Mode d'affichage",
    ["Vue agrégée par zone", f"Points GPS réels ({nb_geo_reels})"],
    horizontal=True,
    key="map_mode",
)

if map_mode == "Vue agrégée par zone":
    geo_agg = (
        fdf.groupby(loc_col)
        .agg(activations=("submission_id", "count"), lat=("_lat", "mean"), lon=("_lon", "mean"))
        .reset_index()
    )
    geo_agg = geo_agg[geo_agg[loc_col] != "Non renseigné"]

    if not geo_agg.empty:
        fig_map = px.scatter_mapbox(
            geo_agg, lat="lat", lon="lon", size="activations", color="activations",
            hover_name=loc_col, hover_data={"activations": True, "lat": False, "lon": False},
            color_continuous_scale=[[0, T["accent_soft"]], [0.5, T["accent"]], [1, T["primary"]]],
            size_max=55, zoom=6, mapbox_style="carto-positron",
        )
        fig_map.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=480, coloraxis_colorbar_title="Activations")
        plot(fig_map)
        st.caption(
            "Taille et couleur des bulles proportionnelles au nombre d'activations par ville/zone "
            "(position moyenne — combine points GPS réels et estimation quand le GPS est absent)."
        )
    else:
        st.caption("Pas encore de données géographiques exploitables pour cette sélection.")

else:
    geo_points = fdf[fdf["_has_real_geo"]].copy()
    if not geo_points.empty:
        geo_points["date_str"] = geo_points["date"].dt.strftime("%d/%m/%Y %H:%M")
        fig_map = px.scatter_mapbox(
            geo_points, lat="_lat", lon="_lon", color="equipe",
            hover_name="nom_prenoms",
            hover_data={loc_col: True, "operateur": True, "date_str": True, "_lat": False, "_lon": False, "equipe": False},
            zoom=6, mapbox_style="carto-positron",
        )
        fig_map.update_traces(marker=dict(size=10, opacity=0.85))
        fig_map.update_layout(
            margin=dict(t=10, b=10, l=10, r=10), height=480,
            legend=dict(title="Équipe", orientation="h", yanchor="bottom", y=1.02),
        )
        plot(fig_map)
        st.caption(
            f"{nb_geo_reels} activation(s) avec une position GPS réellement enregistrée sur le terrain "
            f"(Q9 — zone d'activation), colorées par équipe."
        )
    else:
        st.caption(
            "Aucune position GPS réelle disponible pour cette sélection — les agents n'ont peut-être "
            "pas encore validé la zone d'activation (Q9) sur le terrain."
        )

# =============================================================================
# SUIVI DES AVD ACTIFS (JOURNALIER)
# =============================================================================
st.markdown("<h3 class='section-title'>Suivi des AVD actifs (quotidien)</h3>", unsafe_allow_html=True)
avd_journalier = fdf.groupby("date_only")["code_agent"].nunique().reset_index(name="avd_actifs")
fig_avd = px.bar(avd_journalier, x="date_only", y="avd_actifs")
fig_avd.update_traces(marker_color=T["primary"], marker_line_width=0)
fig_avd.update_yaxes(title="Nombre d'AVD actifs")
fig_avd.update_xaxes(title=None)
style_fig(fig_avd, height=300)
plot(fig_avd)

# =============================================================================
# HEURES ET JOURS LES PLUS ACTIFS
# =============================================================================
st.markdown("<h3 class='section-title'>Heures et jours les plus actifs</h3>", unsafe_allow_html=True)
weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
weekday_fr = {"Monday": "Lun", "Tuesday": "Mar", "Wednesday": "Mer", "Thursday": "Jeu", "Friday": "Ven", "Saturday": "Sam", "Sunday": "Dim"}
heat = fdf.groupby(["weekday", "hour"]).size().reset_index(name="count")
heat["weekday"] = pd.Categorical(heat["weekday"], categories=weekday_order, ordered=True)
heat_pivot = heat.pivot(index="weekday", columns="hour", values="count").reindex(weekday_order)
heat_pivot.index = [weekday_fr[d] for d in heat_pivot.index]
fig_heat = px.imshow(
    heat_pivot, aspect="auto", color_continuous_scale=[T["bg"], T["accent"], T["primary"]],
    labels=dict(x="Heure", y="Jour", color="Activations"),
)
style_fig(fig_heat, height=280)
plot(fig_heat)

# =============================================================================
# OPÉRATEURS & DÉPLAFONNEMENT
# =============================================================================
c1, c2 = st.columns(2)
with c1:
    st.markdown("<h4 class='section-title'>Opérateurs les plus utilisés</h4>", unsafe_allow_html=True)
    op_counts = fdf["operateur"].value_counts().reset_index()
    op_counts.columns = ["operateur", "count"]
    fig_op = px.bar(op_counts, x="operateur", y="count", color="operateur", text="count")
    fig_op.update_traces(textposition="outside")
    style_fig(fig_op, height=340, showlegend=False)
    plot(fig_op)

with c2:
    st.markdown("<h4 class='section-title'>Déplafonnement des comptes</h4>", unsafe_allow_html=True)
    if "deplafonnement" in fdf.columns and not fdf["deplafonnement"].dropna().empty:
        deplaf_counts = fdf["deplafonnement"].value_counts().reset_index()
        deplaf_counts.columns = ["deplafonnement", "count"]
        fig_deplaf = px.pie(
            deplaf_counts, names="deplafonnement", values="count", hole=0.6,
            color="deplafonnement", color_discrete_map={"Oui": T["success"], "Non": T["danger"]},
        )
        fig_deplaf.update_traces(textinfo="percent+label")
        style_fig(fig_deplaf, height=340)
        plot(fig_deplaf)
    else:
        st.caption("Pas de données de déplafonnement disponibles.")

# =============================================================================
# CATÉGORIE SOCIO-PROFESSIONNELLE (4 GROUPES)
# =============================================================================
st.markdown("<h3 class='section-title'>Catégorie socio-professionnelle du client</h3>", unsafe_allow_html=True)

fdf["categorie_socio_pro_groupe"] = fdf["categorie_socio_pro"].apply(config.bucket_socio_pro)
csp_group_counts = fdf["categorie_socio_pro_groupe"].value_counts().reset_index()
csp_group_counts.columns = ["groupe", "count"]

fig_csp = px.pie(csp_group_counts, names="groupe", values="count", hole=0.55)
fig_csp.update_traces(textinfo="percent+label")
style_fig(fig_csp, height=380)
plot(fig_csp)

with st.expander("🔍 Vérifier le regroupement (valeur brute → groupe)"):
    verif = (
        fdf[["categorie_socio_pro", "categorie_socio_pro_groupe"]].drop_duplicates()
        .rename(columns={"categorie_socio_pro": "Valeur brute", "categorie_socio_pro_groupe": "Groupe assigné"})
    )
    st.dataframe(verif, use_container_width=True, hide_index=True)

# =============================================================================
# ACTIVATIONS PAR VILLE (Q8), RÉGION, ÉQUIPE & TOP AGENTS
# =============================================================================
c3, c4 = st.columns(2)
with c3:
    st.markdown("<h4 class='section-title'>Activations par ville (7 grandes villes)</h4>", unsafe_allow_html=True)
    ville_counts = fdf[loc_col_group].value_counts().reset_index()
    ville_counts.columns = ["ville", "count"]
    fig_ville = px.bar(ville_counts.sort_values("count"), x="count", y="ville", orientation="h", text="count")
    fig_ville.update_traces(marker_color=T["accent"], textposition="outside")
    fig_ville.update_yaxes(title=None)
    style_fig(fig_ville, height=400)
    plot(fig_ville)

with c4:
    st.markdown("<h4 class='section-title'>Activations par région (agent)</h4>", unsafe_allow_html=True)
    region_counts = fdf["region"].value_counts().head(12).reset_index()
    region_counts.columns = ["region", "count"]
    fig_region = px.bar(region_counts.sort_values("count"), x="count", y="region", orientation="h", text="count")
    fig_region.update_traces(marker_color=T["info"], textposition="outside")
    fig_region.update_yaxes(title=None)
    style_fig(fig_region, height=400)
    plot(fig_region)

c5, c6 = st.columns(2)
with c5:
    st.markdown("<h4 class='section-title'>Activations par équipe</h4>", unsafe_allow_html=True)
    equipe_counts_v2 = fdf["equipe"].value_counts().head(12).reset_index()
    equipe_counts_v2.columns = ["equipe", "count"]
    fig_equipe_v2 = px.bar(equipe_counts_v2.sort_values("count"), x="count", y="equipe", orientation="h", text="count")
    fig_equipe_v2.update_traces(marker_color=T["secondary"], textposition="outside")
    fig_equipe_v2.update_yaxes(title=None)
    style_fig(fig_equipe_v2, height=400)
    plot(fig_equipe_v2)

with c6:
    st.markdown("<h4 class='section-title'>Répartition de l'activité par agent (Top 10)</h4>", unsafe_allow_html=True)
    agent_counts = fdf.groupby("nom_prenoms").size().reset_index(name="count").sort_values("count", ascending=False).head(10)
    fig_agent = px.bar(agent_counts.sort_values("count"), x="count", y="nom_prenoms", orientation="h", text="count")
    fig_agent.update_traces(marker_color=T["primary"], textposition="outside")
    fig_agent.update_yaxes(title=None)
    style_fig(fig_agent, height=400)
    plot(fig_agent)

# =============================================================================
# CLASSEMENT DES CODES DE PARRAINAGE
# =============================================================================
st.markdown("<h3 class='section-title'>Classement des codes de parrainage</h3>", unsafe_allow_html=True)
top_n = st.slider("Nombre d'agents à afficher", 5, 30, 10)
parrain_counts = (
    fdf.groupby(["code_agent_display", "nom_prenoms"]).size().reset_index(name="activations")
    .sort_values("activations", ascending=False).head(top_n)
)

medals = ["🥇", "🥈", "🥉"]
top3 = parrain_counts.head(3)
if not top3.empty:
    cols = st.columns(len(top3))
    for i, (_, row) in enumerate(top3.iterrows()):
        with cols[i]:
            st.markdown(
                f"""<div class="medal-row">
                <span>{medals[i]} <b>{row['nom_prenoms']}</b><br><small style="color:{T['muted']}">{row['code_agent_display']}</small></span>
                <span style="color:{T['accent']}; font-weight:800; font-size:1.2rem;">{row['activations']}</span>
                </div>""",
                unsafe_allow_html=True,
            )

fig_parrain = px.bar(
    parrain_counts, x="nom_prenoms", y="activations", color="activations",
    color_continuous_scale=[T["accent_soft"], T["accent"], T["primary"]], text="activations",
)
fig_parrain.update_traces(textposition="outside")
fig_parrain.update_xaxes(title=None)
style_fig(fig_parrain, height=380)
fig_parrain.update_layout(coloraxis_showscale=False)
plot(fig_parrain)

# =============================================================================
# RÉPARTITION PAR ÉQUIPE + TABLEAU DÉTAILLÉ SUPERVISEUR → AGENTS
# =============================================================================
st.markdown("<h3 class='section-title'>Répartition par équipe & suivi des superviseurs</h3>", unsafe_allow_html=True)

equipe_counts = fdf["equipe"].value_counts().reset_index()
equipe_counts.columns = ["equipe", "activations"]
fig_equipe = px.bar(equipe_counts.sort_values("activations"), x="activations", y="equipe", orientation="h", text="activations")
fig_equipe.update_traces(marker_color=T["secondary"], textposition="outside")
fig_equipe.update_yaxes(title=None)
style_fig(fig_equipe, height=340)
plot(fig_equipe)

st.markdown("<div class='sub-title'>Détail par équipe : superviseur, agents et contribution au total</div>", unsafe_allow_html=True)

equipes_ordered = equipe_counts.sort_values("activations", ascending=False)["equipe"].tolist()
for team in equipes_ordered:
    team_df = fdf[fdf["equipe"] == team]
    total_team = len(team_df)
    sup_name = team_df["nom_superviseur"].mode().iloc[0] if not team_df["nom_superviseur"].mode().empty else "Non assigné"
    sup_code = sup_code_lookup.get(str(sup_name).strip().upper(), "—")

    agents_team = (
        team_df.groupby(["code_agent_display", "nom_prenoms"]).size().reset_index(name="Activations")
        .sort_values("Activations", ascending=False)
    )
    agents_team["% de l'équipe"] = (agents_team["Activations"] / total_team * 100).round(1).astype(str) + " %"

    st.markdown(
        f"<div class='team-header'>🏷️ Équipe {team} — Superviseur : {sup_name} "
        f"({sup_code}) — {total_team} activation(s)</div>",
        unsafe_allow_html=True,
    )
    st.dataframe(
        agents_team.rename(columns={"code_agent_display": "Code agent", "nom_prenoms": "Nom & Prénoms"}),
        use_container_width=True, hide_index=True,
    )
    if (agents_team["Activations"].sum()) != total_team:
        st.caption("⚠ Écart interne détecté — signale-le si tu vois ce message.")

# =============================================================================
# RÉCONCILIATION & ENTONNOIR (formulaire SUPERVISION) — sur la même période que
# le filtre global actif, pour rester cohérent avec le reste du dashboard.
# =============================================================================
if not sup_periode.empty:
    st.markdown(f"<h3 class='section-title'>Déclaré (agents) vs Confirmé (superviseurs) — {period_label}</h3>", unsafe_allow_html=True)
    sup_periode = sup_periode.copy()
    sup_periode["nom_superviseur"] = sup_periode["nom_superviseur"].fillna("Non précisé")

    declare_par_sup = fdf.groupby("nom_superviseur").size().reset_index(name="Déclaré (agents)")
    confirme_par_sup = sup_periode.groupby("nom_superviseur")["nb_activations_confirmees"].sum().reset_index()
    confirme_par_sup.columns = ["nom_superviseur", "Confirmé (superviseurs)"]

    recon = declare_par_sup.merge(confirme_par_sup, on="nom_superviseur", how="outer").fillna(0)
    recon["Écart"] = recon["Déclaré (agents)"] - recon["Confirmé (superviseurs)"]
    recon_melt = recon.melt(id_vars="nom_superviseur", value_vars=["Déclaré (agents)", "Confirmé (superviseurs)"],
                             var_name="Source", value_name="Activations")
    fig_recon = px.bar(
        recon_melt, x="nom_superviseur", y="Activations", color="Source", barmode="group",
        color_discrete_map={"Déclaré (agents)": T["primary"], "Confirmé (superviseurs)": T["accent"]},
    )
    fig_recon.update_xaxes(title=None)
    style_fig(fig_recon, height=360)
    plot(fig_recon)

    ecarts = recon[recon["Écart"] != 0]
    if not ecarts.empty:
        st.warning(f"{len(ecarts)} superviseur(s) avec un écart déclaré/confirmé — voir le tableau.")
        st.dataframe(ecarts, use_container_width=True, hide_index=True)

    st.markdown(f"<h4 class='section-title'>Entonnoir de conversion — {period_label}</h4>", unsafe_allow_html=True)
    st.caption("Basé sur les chiffres déclarés par les superviseurs (formulaire Supervision), sur la période sélectionnée.")
    funnel_data = pd.DataFrame({
        "Étape": ["Prospects contactés", "Présentations/démos", "Activations confirmées", "Refus/échecs"],
        "Valeur": [sup_periode["nb_prospects"].sum(), sup_periode["nb_demos"].sum(),
                   sup_periode["nb_activations_confirmees"].sum(), sup_periode["nb_refus"].sum()],
    })
    fig_funnel = go.Figure(go.Funnel(
        y=funnel_data["Étape"], x=funnel_data["Valeur"],
        marker=dict(color=[T["primary"], T["secondary"], T["accent"], T["danger"]]),
        textinfo="value+percent initial",
    ))
    style_fig(fig_funnel, height=380)
    plot(fig_funnel)

# =============================================================================
# INCIDENTS TERRAIN (formulaire SUPERVISION uniquement — les anciens sont corrigés)
# =============================================================================
st.markdown("<h3 class='section-title'>Incidents signalés</h3>", unsafe_allow_html=True)
if not sup_df.empty:
    sup_df["date_only_sup"] = pd.to_datetime(sup_df["date"], errors="coerce").dt.date

    incident_jour = st.radio(
        "Jour à afficher", ["Aujourd'hui", "Hier (J-1)"], horizontal=True, key="incident_jour",
    )
    jour_cible = today if incident_jour == "Aujourd'hui" else yesterday

    incidents_jour = sup_df[
        (sup_df["date_only_sup"] == jour_cible) &
        (sup_df["type_incident"].notna() | sup_df["action_corrective"].notna())
    ][["date", "nom_superviseur", "type_incident", "action_corrective"]]

    if not incidents_jour.empty:
        st.dataframe(
            incidents_jour.rename(columns={
                "nom_superviseur": "Superviseur", "type_incident": "Type d'incident",
                "action_corrective": "Observation / Action corrective",
            }).sort_values("date", ascending=False),
            use_container_width=True, hide_index=True, height=250,
        )
    else:
        st.success(f"Aucun incident signalé pour le {jour_cible.strftime('%d/%m/%Y')}.")
else:
    st.caption("Section activée dès que des rapports de supervision seront soumis.")

# =============================================================================
# TABLE DÉTAILLÉE + EXPORTS
# =============================================================================
st.markdown("<h3 class='section-title'>Données détaillées</h3>", unsafe_allow_html=True)
with st.expander("📋 Voir les données détaillées"):
    display_cols = [
        c for c in fdf.columns
        if c not in ["date_only", "hour", "weekday", "_lat", "_lon", "_real_lat", "_real_lon", "_has_real_geo", "code_parrainage"]
    ]
    st.dataframe(fdf[display_cols].sort_values("date", ascending=False), use_container_width=True, height=400)

    export_df = fdf[display_cols].copy()
    for col in export_df.select_dtypes(include=["datetimetz"]).columns:
        export_df[col] = export_df[col].dt.tz_localize(None)
    csv = export_df.to_csv(index=False).encode("utf-8")

    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Activations")
        equipe_counts.to_excel(writer, index=False, sheet_name="Par équipe")
        parrain_counts.to_excel(writer, index=False, sheet_name="Classement agents")

    ce1, ce2 = st.columns(2)
    ce1.download_button("⬇️ Télécharger en CSV", csv, "activations_export.csv", "text/csv", use_container_width=True)
    ce2.download_button(
        "⬇️ Télécharger en Excel", excel_buffer.getvalue(), "activations_export.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True,
    )

st.caption(
    "Sources : KoboToolbox — Activation client, Supervision, Enrôlement agents. "
    "Synchro incrémentale automatique. Page rafraîchie automatiquement."
)
