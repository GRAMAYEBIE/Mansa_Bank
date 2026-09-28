"""
Vue Dirigeant Mansa Bank — Synthèse Exécutive Haute Performance.
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
from kobo_client import load_data, load_enrollment_data

st.set_page_config(page_title="Vue Dirigeant — Mansa Bank", page_icon="🏛️", layout="wide")

# Charte graphique Mansa Bank
T = {
    "bg": "#F6F7FB", "card_bg": "#FFFFFF", "text": "#111827", "muted": "#6B7280", "border": "#E5E7EB",
    "accent": "#C9A227", "primary": "#0B1E33", "secondary": "#1E3A5F", "success": "#0E9F6E", "danger": "#E02424"
}

st.markdown(
    f"""
    <style>
    .stApp {{ background-color: {T['bg']}; color: {T['text']}; }}
    [data-testid="stMetric"] {{
        background: {T['card_bg']}; border: 1px solid {T['border']}; border-radius: 16px;
        padding: 18px; box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }}
    [data-testid="stMetricLabel"] {{ color: {T['muted']} !important; font-weight: 600; text-transform: uppercase; font-size: 0.72rem !important; }}
    [data-testid="stMetricValue"] {{ color: {T['primary']} !important; font-weight: 800; font-size: 1.4rem !important; }}
    h1, h2, h3, h4 {{ color: {T['text']} !important; font-weight: 700; }}
    .section-title {{ border-left: 5px solid {T['accent']}; padding-left: 12px; margin-top: 25px; margin-bottom: 15px; font-size: 1.1rem; }}
    .live-badge {{
        display: inline-block; background: rgba(14,159,110,0.1); color: {T['success']};
        border: 1px solid {T['success']}; border-radius: 999px; padding: 3px 14px;
        font-size: 0.78rem; font-weight: 700; margin-left: 10px; vertical-align: middle;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

_LOCAL_TZ = datetime.now().astimezone().tzinfo

def to_local(ts):
    if ts is None or pd.isna(ts):
        return None
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert(_LOCAL_TZ)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(_LOCAL_TZ)

st_autorefresh(interval=config.AUTO_RELOAD_MS, key="auto_reload_dir")

with st.sidebar:
    st.markdown("### ⚡ Filtres & Contrôles")
    periode_selection = st.radio(
        "Afficher l'activité de :",
        options=["Aujourd'hui", "Hier", "Tout le mois"],
        index=0
    )

    if st.button("🔄 Forcer le rafraîchissement", use_container_width=True):
        st.cache_data.clear()
        st.session_state["force_refresh_dir"] = True
    else:
        st.session_state.setdefault("force_refresh_dir", False)

FORCE = st.session_state.get("force_refresh_dir", False)

@st.cache_data(ttl=config.REFRESH_INTERVAL_SECONDS)
def get_data(force: bool):
    return load_data(force_refresh=force)

@st.cache_data(ttl=config.REFRESH_INTERVAL_SECONDS)
def get_enrollment_data(force: bool):
    return load_enrollment_data(force_refresh=force)

df_raw, last_fetch = get_data(FORCE)
enr_df, enr_last_fetch = get_enrollment_data(FORCE)
st.session_state["force_refresh_dir"] = False

if df_raw.empty:
    st.warning("Aucune donnée disponible.")
    st.stop()

# --- Filtrage initial des dates ---
DATE_DEBUT = pd.Timestamp("2026-08-15").date()
if "date" in df_raw.columns:
    df_raw["date"] = pd.to_datetime(df_raw["date"], errors="coerce")
    df = df_raw[df_raw["date"].dt.date >= DATE_DEBUT].copy()
    if df.empty:
        df = df_raw.copy()
else:
    df = df_raw.copy()

df["date_only"] = df["date"].dt.date if "date" in df.columns else pd.NaT

# --- Normalisation Code Agent / Parrainage ---
CODE_PATTERN = re.compile(r"^[0-9A-F]{6}$")
agent_col = next((c for c in df.columns if c in ["_submitted_by", "username"] or "agent" in c.lower()), None)

def extract_code(username):
    if not isinstance(username, str) or not username.strip():
        return None
    raw = username.strip().upper()
    raw_normalized = raw.replace("O", "0") if "60DDE" in raw.replace("O", "0") else raw
    if "60DDE0" in raw_normalized:
        return "60DDE0"
    candidates = [p for p in re.split(r"[/\-\s]+", raw_normalized) if CODE_PATTERN.match(p)]
    return candidates[-1] if candidates else None

df["code_agent"] = df[agent_col].apply(extract_code) if agent_col else None
df["_username_brut"] = df[agent_col] if agent_col else None

# --- Enrôlement & Équipes ---
if not enr_df.empty:
    enr_df["code_parrainage"] = enr_df["code_parrainage"].astype(str).str.strip().str.upper()
    is_sup = enr_df["role"].fillna("").str.lower().str.contains("superviseur", na=False)
    commerciaux_df = enr_df[~is_sup].drop_duplicates(subset="code_parrainage", keep="last")
    codes_enrolles_commerciaux = set(commerciaux_df["code_parrainage"].dropna().unique())
    
    df = df.merge(
        enr_df[["code_parrainage", "nom_prenoms", "equipe"]],
        left_on="code_agent", right_on="code_parrainage", how="left"
    )
    df["equipe"] = df["equipe"].fillna("Non assignée")
    df["nom_prenoms"] = df["nom_prenoms"].fillna(df["_username_brut"].fillna("Inconnu"))
else:
    codes_enrolles_commerciaux = set()
    df["equipe"] = "Non assignée"
    df["nom_prenoms"] = df["_username_brut"]

# Forçage YAPO & zones
mask_yapo = (df["code_agent"] == "60DDE0") | df["_username_brut"].astype(str).str.upper().str.contains("60DDE0|YAPO", na=False)
if mask_yapo.any():
    df.loc[mask_yapo, ["code_agent", "nom_prenoms", "equipe"]] = ["60DDE0", "YAPO AYEKOE BIENVENUE", "Yamoussoukro"]

team_mapping = {"Daloa": "Daloa", "Abengourou": "Abengourou", "San-Pedro": "San-Pedro", "Yamoussoukro": "Yamoussoukro"}
for eq, eq_target in team_mapping.items():
    df.loc[df["equipe"].str.lower().str.contains(eq.lower(), na=False), "equipe"] = eq_target

df["code_agent_display"] = df["code_agent"].fillna("Non identifié")

# --- Dédoublonnage instantané ---
if "client_telephone" in df.columns:
    df["tel_clean"] = df["client_telephone"].astype(str).str.strip().replace({"None": "", "nan": ""})
    df_avec_tel = df[df["tel_clean"] != ""].drop_duplicates(subset=["tel_clean"], keep="last")
    df_sans_tel = df[df["tel_clean"] == ""]
    df = pd.concat([df_avec_tel, df_sans_tel]).sort_values("date").reset_index(drop=True)

# --- Filtrage Période ---
now_utc = datetime.now(timezone.utc)
today = now_utc.date()
hier = today - timedelta(days=1)
month_start = today.replace(day=1)

if periode_selection == "Aujourd'hui":
    target_date_label = "aujourd'hui"
    fdf = df[df["date_only"] == today]
elif periode_selection == "Hier":
    target_date_label = "hier"
    fdf = df[df["date_only"] == hier]
else:
    target_date_label = "ce mois"
    fdf = df[(df["date_only"] >= month_start) & (df["date_only"] <= today)]

# Header
badge = "<span class='live-badge'>● LIVE</span>" if periode_selection == "Aujourd'hui" else ""
st.markdown(f"# 🏛️ Vue Dirigeant Mansa — {periode_selection} {badge}", unsafe_allow_html=True)
st.caption(f"Actualisé à {to_local(last_fetch).strftime('%H:%M')} · Affichage de l'activité du : **{target_date_label}**.")

# =============================================================================
# 1. EFFECTIFS AVD & KPI CLÉS (Identique au Superviseur)
# =============================================================================
codes_actifs = set(fdf["code_agent"].dropna().unique())
codes_matches = codes_actifs & codes_enrolles_commerciaux
codes_actifs_non_enrolles = codes_actifs - set(enr_df["code_parrainage"].dropna().unique()) if not enr_df.empty else set()

effectif_prevu = len(codes_enrolles_commerciaux)
effectif_deploye = len(codes_matches)
nb_non_enrolles = len(codes_actifs_non_enrolles)

top_equipe = fdf["equipe"].value_counts().idxmax() if not fdf["equipe"].dropna().empty else "—"
agent_today = fdf.groupby(["code_agent_display", "nom_prenoms"]).size()
best_agent_label = "—"
if not agent_today.empty:
    (best_code, best_name), best_count = agent_today.idxmax(), int(agent_today.max())
    best_agent_label = f"{best_name} ({best_code})"

st.markdown(f"<h3 class='section-title'>Effectifs AVD ({target_date_label})</h3>", unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)
c1.metric("AVD PRÉVU", effectif_prevu)
c2.metric("AVD DÉPLOYÉ", effectif_deploye)
c3.metric("AVD ACTIF ENRÔLÉ", effectif_deploye)
c4.metric("AVD NON ENRÔLÉ ACTIF", nb_non_enrolles)

c5, c6, c7 = st.columns(3)
c5.metric("MEILLEURE ÉQUIPE", top_equipe)
c6.metric("MEILLEUR AGENT", best_agent_label)
c7.metric(f"ACTIVATIONS ({target_date_label.upper()})", len(fdf))

# =============================================================================
# 2. ÉVOLUTION DES ACTIVITÉS
# =============================================================================
st.markdown("<h3 class='section-title'>Évolution des activités</h3>", unsafe_allow_html=True)
daily = df.groupby("date_only").size().reset_index(name="activations")
fig_line = px.area(daily, x="date_only", y="activations")
fig_line.update_traces(line_color=T["accent"], line_width=3, fillcolor="rgba(201,162,39,0.15)")
fig_line.update_layout(
    paper_bgcolor=T["card_bg"], plot_bgcolor=T["card_bg"],
    height=300, margin=dict(t=10, b=10, l=10, r=10)
)
fig_line.update_xaxes(title=None)
st.plotly_chart(fig_line, use_container_width=True, config={"displayModeBar": False})

# =============================================================================
# 3. ACTIVATIONS PAR ÉQUIPE (Synthèse Globale sans détails AVD)
# =============================================================================
st.markdown(f"<h3 class='section-title'>Activations par équipe ({target_date_label})</h3>", unsafe_allow_html=True)
equipe_counts = fdf["equipe"].value_counts().reset_index()
equipe_counts.columns = ["Équipe", "Activations"]

fig_equipe = px.bar(equipe_counts.sort_values("Activations"), x="Activations", y="Équipe", orientation="h", text="Activations")
fig_equipe.update_traces(marker_color=T["secondary"], textposition="outside")
fig_equipe.update_layout(
    paper_bgcolor=T["card_bg"], plot_bgcolor=T["card_bg"],
    height=280, margin=dict(t=10, b=10, l=10, r=10)
)
fig_equipe.update_yaxes(title=None)
st.plotly_chart(fig_equipe, use_container_width=True, config={"displayModeBar": False})

# =============================================================================
# 4. TOP 5 MEILLEURS AGENTS
# =============================================================================
st.markdown(f"<h3 class='section-title'>Top 5 meilleurs agents ({target_date_label})</h3>", unsafe_allow_html=True)
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
    st.caption("Aucune activation enregistrée pour cette période.")

# =============================================================================
# 5. POSITION GÉOGRAPHIQUE (Sécurisé & Cadré sur la Côte d'Ivoire)
# =============================================================================
st.markdown("<h3 class='section-title'>Position géolocalisée</h3>", unsafe_allow_html=True)

mode_geo = st.radio(
    "Mode d'affichage cartographique :",
    options=[f"Vue agrégée par zone", f"Points GPS réels ({len(fdf)})"],
    index=0,
    horizontal=True,
    label_visibility="collapsed"
)

# Coordonnées officielles des villes de Côte d'Ivoire
GEO_CITIES_CI = {
    "YAMOUSSOKRO": (6.827620, -5.289343),
    "DALOA": (6.877350, -6.450230),
    "SAN-PEDRO": (4.748510, -6.636300),
    "SAN PEDRO": (4.748510, -6.636300),
    "ABENGOUROU": (6.729720, -3.496390),
    "ABIDJAN": (5.359952, -4.008256),
    "BOUAKE": (7.693850, -5.030310),
    "KORHOGO": (9.458030, -5.629610),
    "MAN": (7.412510, -7.553830),
    "GAGNOA": (6.131930, -5.950600),
}

CI_CENTER = {"lat": 7.539989, "lon": -5.547080}
CI_ZOOM = 5.8

lat_col = next((c for c in fdf.columns if "lat" in c.lower() or "gps" in c.lower()), None)
lon_col = next((c for c in fdf.columns if "lon" in c.lower() or "lng" in c.lower()), None)

if fdf.empty:
    st.info("Aucune activation enregistrée pour la période sélectionnée.")
else:
    if "Points GPS réels" in mode_geo and lat_col and lon_col and fdf[lat_col].notna().sum() > 0:
        map_df = fdf[[lat_col, lon_col, "equipe"]].dropna()
        map_df.columns = ["lat", "lon", "equipe"]
        
        fig_map = px.scatter_mapbox(
            map_df, lat="lat", lon="lon", color="equipe",
            zoom=CI_ZOOM, center=CI_CENTER,
            color_discrete_sequence=[T["accent"], T["secondary"], T["primary"], T["success"]]
        )
    else:
        # Construction de l'agrégation sécurisée
        geo_rows = []
        counts = fdf["equipe"].value_counts()
        
        for eq, count in counts.items():
            eq_clean = str(eq).upper().replace("-", " ").strip()
            coords = None
            for c_name, c_coords in GEO_CITIES_CI.items():
                if c_name in eq_clean:
                    coords = c_coords
                    break
            if not coords:
                coords = GEO_CITIES_CI["YAMOUSSOKRO"]
                
            geo_rows.append({"zone": eq, "lat": coords[0], "lon": coords[1], "Activations": int(count)})
        
        geo_df = pd.DataFrame(geo_rows)
        
        if not geo_df.empty and geo_df["Activations"].sum() > 0:
            fig_map = px.scatter_mapbox(
                geo_df, lat="lat", lon="lon", size="Activations", color="Activations",
                hover_name="zone", size_max=35, zoom=CI_ZOOM, center=CI_CENTER,
                color_continuous_scale=[[0, "#E5C875"], [0.5, "#C9A227"], [1.0, "#111827"]]
            )
        else:
            # Fallback en cas de total = 0
            fig_map = px.scatter_mapbox(
                pd.DataFrame([{"lat": CI_CENTER["lat"], "lon": CI_CENTER["lon"], "zone": "Aucune activation"}]),
                lat="lat", lon="lon", hover_name="zone", zoom=CI_ZOOM, center=CI_CENTER
            )

    fig_map.update_layout(
        mapbox_style="carto-positron",
        margin=dict(t=0, b=0, l=0, r=0),
        height=450,
        paper_bgcolor=T["card_bg"]
    )

    st.plotly_chart(fig_map, use_container_width=True, config={"displayModeBar": False})
    st.caption("Taille et couleur des bulles proportionnelles au nombre d'activations par ville/zone en Côte d'Ivoire.")
    
    st.caption ("AYEBIE GRAM MESCHAC DATA SCIENTIST/DATA ENGINEER - MsC DATASCIENCE AND ANALYTICS ACITY")
    
