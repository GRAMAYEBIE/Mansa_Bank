"""
Vue Superviseur — version simplifiée du dashboard, verrouillée sur "Aujourd'hui".
Pas de filtre ville/équipe/opérateur/période : juste ce qui se passe AUJOURD'HUI,
pour que chaque superviseur voie l'activité de son équipe en direct, sans manipulation.

Cette page réutilise exactement la même logique de chargement/nettoyage/matching
que app.py (dédoublonnage, extraction de code, jointure enrôlement) pour garantir
des chiffres strictement identiques entre les deux vues.
"""

import unicodedata
import re
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

import config
from kobo_client import load_data, load_supervisor_data, load_enrollment_data

st.set_page_config(page_title="Vue Superviseur — Mansa Bank", page_icon="👥", layout="wide")

T = {
    "bg": "#F6F7FB", "card_bg": "#FFFFFF", "text": "#111827", "muted": "#6B7280", "border": "#E5E7EB",
    "accent": "#C9A227", "accent_soft": "#F4E9C8", "primary": "#0B1E33", "secondary": "#1E3A5F",
    "success": "#0E9F6E", "danger": "#E02424", "info": "#2563EB",
}
COLOR_SEQ = [T["primary"], T["accent"], T["secondary"], T["success"], T["info"], "#8B5CF6", T["danger"]]

st.markdown(
    f"""
    <style>
    .stApp {{ background-color: {T['bg']}; color: {T['text']}; }}
    [data-testid="stMetric"] {{
        background: {T['card_bg']}; border: 1px solid {T['border']}; border-radius: 16px;
        padding: 18px 18px 14px 18px; box-shadow: 0 1px 2px rgba(16,24,40,0.04), 0 1px 3px rgba(16,24,40,0.06);
    }}
    [data-testid="stMetricLabel"] {{ color: {T['muted']} !important; font-weight: 600; text-transform: uppercase; font-size: 0.72rem !important; }}
    [data-testid="stMetricValue"] {{ color: {T['primary']} !important; font-weight: 800; font-size: 1.4rem !important; }}
    h1, h2, h3, h4 {{ color: {T['text']} !important; font-weight: 700; }}
    .live-badge {{
        display: inline-block; background: rgba(14,159,110,0.1); color: {T['success']};
        border: 1px solid {T['success']}; border-radius: 999px; padding: 3px 14px;
        font-size: 0.78rem; font-weight: 700; margin-left: 10px; vertical-align: middle;
    }}
    .section-title {{ border-left: 5px solid {T['accent']}; padding: 2px 0 2px 12px; margin-top: 30px; margin-bottom: 10px; font-size: 1.1rem; }}
    .team-header {{ background: {T['primary']}; color: white; border-radius: 12px 12px 0 0; padding: 12px 18px; font-weight: 700; }}
    </style>
    """,
    unsafe_allow_html=True,
)

PLOTLY_TEMPLATE = go.layout.Template()
PLOTLY_TEMPLATE.layout.paper_bgcolor = T["card_bg"]
PLOTLY_TEMPLATE.layout.plot_bgcolor = T["card_bg"]
PLOTLY_TEMPLATE.layout.font = dict(color=T["text"], family="Segoe UI, sans-serif", size=13)
PLOTLY_TEMPLATE.layout.colorway = COLOR_SEQ


def plot(fig, height=340):
    fig.update_layout(template=PLOTLY_TEMPLATE, height=height, margin=dict(t=20, b=20, l=10, r=10))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, theme=None)


_LOCAL_TZ = datetime.now().astimezone().tzinfo


def to_local(ts):
    if ts is None or (hasattr(pd, "isna") and pd.isna(ts)):
        return None
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert(_LOCAL_TZ)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(_LOCAL_TZ)


st_autorefresh(interval=config.AUTO_RELOAD_MS, key="auto_reload_sup")

with st.sidebar:
    st.markdown("### ⚡ Contrôles")
    if st.button("🔄 Forcer le rafraîchissement", use_container_width=True):
        st.cache_data.clear()
        st.session_state["force_refresh_sup"] = True
    else:
        st.session_state.setdefault("force_refresh_sup", False)
    st.caption("Cette page affiche uniquement l'activité d'AUJOURD'HUI — aucun autre filtre.")

FORCE = st.session_state.get("force_refresh_sup", False)


@st.cache_data(ttl=config.REFRESH_INTERVAL_SECONDS, show_spinner="Synchronisation...")
def get_data(force: bool):
    return load_data(force_refresh=force)


@st.cache_data(ttl=config.REFRESH_INTERVAL_SECONDS, show_spinner="Synchronisation enrôlement...")
def get_enrollment_data(force: bool):
    return load_enrollment_data(force_refresh=force)


df_raw, last_fetch = get_data(FORCE)
enr_df, enr_last_fetch = get_enrollment_data(FORCE)
st.session_state["force_refresh_sup"] = False

if df_raw.empty:
    st.warning("Aucune donnée disponible.")
    st.stop()

# --- Règle métier : activité comptabilisée à partir du 15 août 2026 ---
DATE_DEBUT = pd.Timestamp("2026-08-15").date()
if "date" in df_raw.columns:
    df_raw["date"] = pd.to_datetime(df_raw["date"], errors="coerce")
    df = df_raw[df_raw["date"].dt.date >= DATE_DEBUT].copy()
    if df.empty:
        df = df_raw.copy()
else:
    df = df_raw.copy()

# --- Nettoyage ville ---
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
    return city if city in config.MAJOR_CITIES else "Autres villes"


df["ville_propre"] = df[target_col].apply(clean_city)
df["ville_groupe"] = df["ville_propre"].apply(to_major_city)
loc_col_group = "ville_groupe"

df["date_only"] = df["date"].dt.date if "date" in df.columns else pd.NaT

agent_col = next(
    (c for c in df.columns if c in ["_submitted_by", "username"] or "agent" in c.lower() or "user" in c.lower()),
    None,
)

# --- Extraction du code parrainage (robuste : /, -, espace) ---
CODE_PATTERN = re.compile(r"^[0-9A-F]{6}$")


def extract_code(username):
    if not isinstance(username, str) or not username.strip():
        return None
    raw = username.strip().upper()
    # Correction spécifique demandée : forcer le code 60DDE0 pour les variantes liées à Yapo
    if "60DDE0" in raw:
        return "60DDE0"
    parts = [p.strip() for p in re.split(r"[/\-\s]+", raw) if p.strip()]
    candidates = [p for p in parts if CODE_PATTERN.match(p)]
    if candidates:
        return candidates[-1]
    fallback_matches = re.findall(r"[0-9A-F]{6}", raw)
    return fallback_matches[-1] if fallback_matches else None


df["code_agent"] = df[agent_col].apply(extract_code) if agent_col else None
df["_username_brut"] = df[agent_col] if agent_col else None

ROLE_SUPERVISEUR_KW = "superviseur"

if not enr_df.empty:
    enr_df["code_parrainage"] = enr_df["code_parrainage"].astype(str).str.strip().str.upper()
    enr_df["role"] = enr_df["role"].fillna("")
    
    # Correction manuelle / forcée dans le référentiel des superviseurs selon les consignes
    # Superviseurs par zone : Yamoussoukro (Koffi Ange Mickael), Daloa (Koukougnon Euloge), Abengourou (Berthe Mafine Chata), San-Pédro (Bosson Kasi Jacques)
    supervisor_overrides = {
        "KOFFI ANGE MICKAEL": {"role": "superviseur", "ville": "Yamoussoukro", "equipe": "Yamoussoukro"},
        "KOUKOUGNON EULOGE": {"role": "superviseur", "ville": "Daloa", "equipe": "Daloa"},
        "BERTHE MAFINE CHATA": {"role": "superviseur", "ville": "Abengourou", "equipe": "Abengourou"},
        "BOSSON KASI JACQUES": {"role": "superviseur", "ville": "San-Pedro", "equipe": "San-Pedro"},
    }
    for sup_name, sup_info in supervisor_overrides.items():
        mask = enr_df["nom_prenoms"].str.upper().str.contains(sup_name, na=False)
        if mask.any():
            enr_df.loc[mask, "role"] = sup_info["role"]
            enr_df.loc[mask, "ville"] = sup_info["ville"]
            enr_df.loc[mask, "equipe"] = sup_info["equipe"]

    is_supervisor_role = enr_df["role"].str.lower().str.contains(ROLE_SUPERVISEUR_KW, na=False)
    commerciaux_df = enr_df[~is_supervisor_role].drop_duplicates(subset="code_parrainage", keep="last")
    superviseurs_df = enr_df[is_supervisor_role].drop_duplicates(subset="code_parrainage", keep="last")
    codes_enrolles_commerciaux = set(commerciaux_df["code_parrainage"].dropna().unique())
    sup_code_lookup = superviseurs_df.set_index("nom_prenoms")["code_parrainage"].to_dict()

    df = df.merge(
        enr_df[["code_parrainage", "nom_prenoms", "nom_superviseur", "equipe", "role", "ville", "region"]]
        .rename(columns={"ville": "agent_ville"}),
        left_on="code_agent", right_on="code_parrainage", how="left",
    )
    df["nom_superviseur"] = df["nom_superviseur"].fillna("Non assigné")
    df["equipe"] = df["equipe"].fillna("Non assignée")
    df["nom_prenoms"] = df["nom_prenoms"].fillna(df["_username_brut"].fillna("Inconnu"))
else:
    commerciaux_df, superviseurs_df = pd.DataFrame(), pd.DataFrame()
    codes_enrolles_commerciaux, sup_code_lookup = set(), {}
    df["nom_superviseur"] = "Non assigné"
    df["equipe"] = "Non assignée"
    df["nom_prenoms"] = df["_username_brut"]

# Correction spécifique pour s'assurer que le code 60DDE0 (Yapo Ayekoe Bienvenue) est bien rattaché
mask_yapo = df["code_agent"] == "60DDE0"
if mask_yapo.any():
    df.loc[mask_yapo, "nom_prenoms"] = "YAPO AYEKOE BIENVENUE"
    df.loc[mask_yapo, "nom_superviseur"] = "KOFFI ANGE MICKAEL"
    df.loc[mask_yapo, "equipe"] = "Yamoussoukro"

df["code_agent_display"] = df["code_agent"].fillna("Non identifié")

# --- Dédoublonnage : 1 numéro client = 1 activation (règle déplafonnement=Oui prioritaire) ---
if "client_telephone" in df.columns:
    df = df.sort_values("date")
    has_phone = df["client_telephone"].astype(str).str.strip().replace({"None": "", "nan": ""}) != ""
    df_avec_tel = df[has_phone].copy()
    df_sans_tel = df[~has_phone].copy()

    def pick_best(group):
        deplaf_oui = group[group["deplafonnement"] == "Oui"]
        return deplaf_oui.iloc[-1] if not deplaf_oui.empty else group.iloc[-1]

    if not df_avec_tel.empty:
        df_avec_tel = df_avec_tel.groupby("client_telephone", group_keys=False).apply(pick_best)
    df = pd.concat([df_avec_tel, df_sans_tel]).sort_values("date").reset_index(drop=True)

now_utc = datetime.now(timezone.utc)
today = now_utc.date()
last_submission = df["date"].max() if pd.notna(df["date"].max()) else None
is_stale = last_submission is not None and (now_utc - last_submission).total_seconds() / 3600 > config.STALE_DATA_HOURS

# =============================================================================
# TOUT EST VERROUILLÉ SUR AUJOURD'HUI — aucun filtre ville/équipe/opérateur/période
# =============================================================================
fdf = df[df["date_only"] == today]

badge = "<span class='live-badge'>● LIVE</span>"
st.markdown(f"# 👥 Vue Superviseur — {today.strftime('%d/%m/%Y')} {badge}", unsafe_allow_html=True)
st.caption(f"Actualisé à {to_local(last_fetch).strftime('%H:%M')} · Cette page ne montre QUE l'activité du jour.")
if is_stale:
    st.warning("Aucune nouvelle activation récente — vérifie que la collecte terrain fonctionne.")

# =============================================================================
# EFFECTIFS AVD DU JOUR
# =============================================================================
codes_actifs = set(fdf["code_agent"].dropna().unique())
codes_matches = codes_actifs & codes_enrolles_commerciaux
codes_actifs_non_enrolles = codes_actifs - set(enr_df["code_parrainage"].dropna().unique()) if not enr_df.empty else set()

effectif_prevu = len(codes_enrolles_commerciaux)
effectif_deploye = len(codes_matches)
effectif_non_actif = max(effectif_prevu - effectif_deploye, 0)
nb_non_enrolles = len(codes_actifs_non_enrolles)

# Remplacement de "Meilleure ville" par "Meilleure équipe"
top_equipe = fdf["equipe"].value_counts().idxmax() if not fdf["equipe"].dropna().empty else "—"
agent_today = fdf.groupby(["code_agent_display", "nom_prenoms"]).size()
best_agent_label = "—"
if not agent_today.empty:
    (best_code, best_name), best_count = agent_today.idxmax(), int(agent_today.max())
    best_agent_label = f"{best_name} ({best_code}) — {best_count}"

st.markdown("<h3 class='section-title'>Effectifs AVD</h3>", unsafe_allow_html=True)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("AVD prévu", effectif_prevu)
c2.metric("AVD déployé", effectif_deploye)
c3.metric("AVD actif enrôlé", effectif_deploye)
c4.metric("AVD non actif enrôlé", effectif_non_actif)
c5.metric("AVD non enrôlé actif", nb_non_enrolles)

c6, c7, c8 = st.columns(3)
c6.metric("Meilleure équipe", top_equipe)
c7.metric("Meilleur agent", best_agent_label)
c8.metric("Activations aujourd'hui", len(fdf))

# =============================================================================
# OBJECTIF MENSUEL (jauge uniquement)
# =============================================================================
st.markdown("<h3 class='section-title'>Objectif mensuel</h3>", unsafe_allow_html=True)
month_start = today.replace(day=1)
df_month = df[(df["date_only"] >= month_start) & (df["date_only"] <= today)]
nb_transactions_mois = int((df_month["transaction_effectuee"] == "Oui").sum()) if "transaction_effectuee" in df.columns else 0
objectif_mensuel = 25000

fig_gauge = go.Figure(go.Indicator(
    mode="gauge+number",
    value=nb_transactions_mois,
    number={"font": {"color": T["primary"], "size": 36}},
    title={"text": f"Objectif : {objectif_mensuel:,}".replace(",", " "), "font": {"size": 14}},
    gauge={
        "axis": {"range": [0, objectif_mensuel], "tickcolor": T["muted"]},
        "bar": {"color": T["accent"]},
        "bgcolor": T["bg"], "borderwidth": 0,
        "steps": [
            {"range": [0, objectif_mensuel * 0.5], "color": "#FEE2E2"},
            {"range": [objectif_mensuel * 0.5, objectif_mensuel * 0.85], "color": "#FEF3C7"},
            {"range": [objectif_mensuel * 0.85, objectif_mensuel], "color": "#DCFCE7"},
        ],
        "threshold": {"line": {"color": T["primary"], "width": 3}, "value": objectif_mensuel},
    },
))
plot(fig_gauge, height=280)

# =============================================================================
# ÉVOLUTION DES ACTIVITÉS (contexte, depuis le 15 août jusqu'à aujourd'hui)
# =============================================================================
st.markdown("<h3 class='section-title'>Évolution des activités</h3>", unsafe_allow_html=True)
daily = df.groupby("date_only").size().reset_index(name="activations")
fig_line = px.area(daily, x="date_only", y="activations")
fig_line.update_traces(line_color=T["accent"], line_width=3, fillcolor="rgba(201,162,39,0.12)")
fig_line.update_xaxes(title=None)
plot(fig_line)

# =============================================================================
# ACTIVATIONS PAR ÉQUIPE (aujourd'hui) — Suppression du graph par ville
# =============================================================================
st.markdown("<h4 class='section-title'>Activations par équipe (aujourd'hui)</h4>", unsafe_allow_html=True)
equipe_counts = fdf["equipe"].value_counts().reset_index()
equipe_counts.columns = ["equipe", "count"]
fig_equipe = px.bar(equipe_counts.sort_values("count"), x="count", y="equipe", orientation="h", text="count")
fig_equipe.update_traces(marker_color=T["secondary"], textposition="outside")
fig_equipe.update_yaxes(title=None)
plot(fig_equipe, height=340)
st.dataframe(
    equipe_counts.rename(columns={"equipe": "Équipe", "count": "Activations (aujourd'hui)"}).sort_values(
        "Activations (aujourd'hui)", ascending=False
    ),
    use_container_width=True, hide_index=True,
)

# =============================================================================
# PERFORMANCES / ACTIVATIONS DES SUPERVISEURS (Aujourd'hui)
# =============================================================================
st.markdown("<h3 class='section-title'>Performances des Superviseurs (Aujourd'hui)</h3>", unsafe_allow_html=True)
if not superviseurs_df.empty:
    sup_perf_list = []
    for _, sup_row in superviseurs_df.iterrows():
        s_name = sup_row.get("nom_prenoms", "Inconnu")
        s_code = sup_row.get("code_parrainage", "—")
        s_team = sup_row.get("equipe", "Non assignée")
        
        # Le total du superviseur correspond au total des activations de son équipe
        team_activations = len(fdf[fdf["equipe"] == s_team]) if s_team != "Non assignée" else 0
        
        sup_perf_list.append({
            "Code parrainage": s_code,
            "Nom & Prénoms": s_name,
            "Équipe": s_team,
            "Activations (Aujourd'hui)": team_activations
        })
    df_sup_perf = pd.DataFrame(sup_perf_list).sort_values("Activations (Aujourd'hui)", ascending=False)
    st.dataframe(df_sup_perf, use_container_width=True, hide_index=True)
else:
    st.caption("Aucun superviseur trouvé dans le référentiel d'enrôlement.")

# =============================================================================
# TOP 5 MEILLEURS AGENTS (aujourd'hui)
# =============================================================================
st.markdown("<h3 class='section-title'>Top 5 meilleurs agents (aujourd'hui)</h3>", unsafe_allow_html=True)
top5 = (
    fdf.groupby(["code_agent_display", "nom_prenoms"]).size().reset_index(name="Activations")
    .sort_values("Activations", ascending=False).head(5)
)
medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
if not top5.empty:
    cols = st.columns(len(top5))
    for i, (_, row) in enumerate(top5.iterrows()):
        with cols[i]:
            st.markdown(
                f"""<div style="background:{T['card_bg']}; border:1px solid {T['border']}; border-radius:12px;
                padding:14px; text-align:center;">
                <div style="font-size:1.5rem;">{medals[i]}</div>
                <b>{row['nom_prenoms']}</b><br>
                <small style="color:{T['muted']}">{row['code_agent_display']}</small><br>
                <span style="color:{T['accent']}; font-weight:800; font-size:1.3rem;">{row['Activations']}</span>
                </div>""",
                unsafe_allow_html=True,
            )
else:
    st.caption("Aucune activation enregistrée aujourd'hui pour le moment.")

# =============================================================================
# RÉPARTITION PAR ÉQUIPE & SUIVI DES SUPERVISEURS (aujourd'hui)
# =============================================================================
st.markdown("<h3 class='section-title'>Répartition par équipe & détails des AVD</h3>", unsafe_allow_html=True)

equipes_ordered = equipe_counts.sort_values("count", ascending=False)["equipe"].tolist() if not equipe_counts.empty else []
for team in equipes_ordered:
    team_df = fdf[fdf["equipe"] == team]
    total_team = len(team_df)
    sup_name = team_df["nom_superviseur"].mode().iloc[0] if not team_df["nom_superviseur"].mode().empty else "Non assigné"
    sup_code = sup_code_lookup.get(sup_name, "—")

    agents_team = (
        team_df.groupby(["code_agent_display", "nom_prenoms"]).size().reset_index(name="Activations")
        .sort_values("Activations", ascending=False)
    )
    agents_team["% de l'équipe"] = (agents_team["Activations"] / total_team * 100).round(1).astype(str) + " %" if total_team > 0 else "0 %"

    st.markdown(
        f"<div class='team-header'>🏷️ Équipe {team} — Superviseur : {sup_name} ({sup_code}) — "
        f"{total_team} activation(s) aujourd'hui</div>",
        unsafe_allow_html=True,
    )
    st.dataframe(
        agents_team.rename(columns={"code_agent_display": "Code agent", "nom_prenoms": "Nom & Prénoms"}),
        use_container_width=True, hide_index=True,
    )

st.caption("Vue Superviseur — se rafraîchit automatiquement. Pour l'analyse détaillée et les filtres avancés, voir la page principale.")
