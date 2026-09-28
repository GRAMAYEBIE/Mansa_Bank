"""
Vue Dirigeant Mansa Bank — Synthèse Exécutive KPI & Géolocalisation.
"""

import unicodedata
import re
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

import config
from kobo_client import load_data, load_enrollment_data

st.set_page_config(page_title="Vue Dirigeant — Mansa Bank", page_icon="🏛️", layout="wide")

# Theme Mansa Bank
T = {
    "bg": "#F6F7FB", "card_bg": "#FFFFFF", "text": "#111827", "muted": "#6B7280", "border": "#E5E7EB",
    "accent": "#C9A227", "primary": "#0B1E33", "secondary": "#1E3A5F", "success": "#0E9F6E", "info": "#2563EB"
}

st.markdown(
    f"""
    <style>
    .stApp {{ background-color: {T['bg']}; color: {T['text']}; }}
    [data-testid="stMetric"] {{
        background: {T['card_bg']}; border: 1px solid {T['border']}; border-radius: 16px;
        padding: 18px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    [data-testid="stMetricLabel"] {{ color: {T['muted']} !important; font-weight: 600; text-transform: uppercase; font-size: 0.75rem !important; }}
    [data-testid="stMetricValue"] {{ color: {T['primary']} !important; font-weight: 800; font-size: 1.6rem !important; }}
    h1, h2, h3, h4 {{ color: {T['text']} !important; font-weight: 700; }}
    .section-title {{ border-left: 5px solid {T['accent']}; padding-left: 12px; margin-top: 25px; margin-bottom: 15px; font-size: 1.1rem; }}
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
    st.markdown("### ⚡ Filtres Période")
    periode_selection = st.radio(
        "Sélectionnez la période :",
        options=["Aujourd'hui", "Hier", "Tout le mois"],
        index=0
    )
    if st.button("🔄 Rafraîchir les données", use_container_width=True):
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

# --- Filtrage initial ---
DATE_DEBUT = pd.Timestamp("2026-08-15").date()
if "date" in df_raw.columns:
    df_raw["date"] = pd.to_datetime(df_raw["date"], errors="coerce")
    df = df_raw[df_raw["date"].dt.date >= DATE_DEBUT].copy()
    if df.empty:
        df = df_raw.copy()
else:
    df = df_raw.copy()

df["date_only"] = df["date"].dt.date if "date" in df.columns else pd.NaT

# Extraction Code Agent / Parrainage
CODE_PATTERN = re.compile(r"^[0-9A-F]{6}$")
agent_col = next((c for c in df.columns if c in ["_submitted_by", "username"] or "agent" in c.lower()), None)

def extract_code(username):
    if not isinstance(username, str) or not username.strip():
        return None
    raw = username.strip().upper().replace("O", "0") if "60DDE" in str(username).upper().replace("O", "0") else str(username).strip().upper()
    if "60DDE0" in raw:
        return "60DDE0"
    candidates = [p for p in re.split(r"[/\-\s]+", raw) if CODE_PATTERN.match(p)]
    return candidates[-1] if candidates else None

df["code_agent"] = df[agent_col].apply(extract_code) if agent_col else None

# Enrôlements & Équipes
if not enr_df.empty:
    enr_df["code_parrainage"] = enr_df["code_parrainage"].astype(str).str.strip().str.upper()
    is_sup = enr_df["role"].fillna("").str.lower().str.contains("superviseur", na=False)
    commerciaux_df = enr_df[~is_sup].drop_duplicates(subset="code_parrainage", keep="last")
    codes_enrolles_commerciaux = set(commerciaux_df["code_parrainage"].dropna().unique())
    
    df = df.merge(
        enr_df[["code_parrainage", "equipe"]],
        left_on="code_agent", right_on="code_parrainage", how="left"
    )
    df["equipe"] = df["equipe"].fillna("Non assignée")
else:
    codes_enrolles_commerciaux = set()
    df["equipe"] = "Non assignée"

# Application forçage équipe Yapou / Villes
team_mapping = {"Daloa": "Daloa", "Abengourou": "Abengourou", "San-Pedro": "San-Pedro", "Yamoussoukro": "Yamoussoukro"}
for eq, eq_target in team_mapping.items():
    df.loc[df["equipe"].str.lower().str.contains(eq.lower(), na=False), "equipe"] = eq_target

# Dédoublonnage instantané par téléphone
if "client_telephone" in df.columns:
    df["tel_clean"] = df["client_telephone"].astype(str).str.strip().replace({"None": "", "nan": ""})
    df_avec_tel = df[df["tel_clean"] != ""].drop_duplicates(subset=["tel_clean"], keep="last")
    df_sans_tel = df[df["tel_clean"] == ""]
    df = pd.concat([df_avec_tel, df_sans_tel]).sort_values("date").reset_index(drop=True)

# Application Filtre Date
now_utc = datetime.now(timezone.utc)
today = now_utc.date()
hier = today - timedelta(days=1)
month_start = today.replace(day=1)

if periode_selection == "Aujourd'hui":
    fdf = df[df["date_only"] == today]
elif periode_selection == "Hier":
    fdf = df[df["date_only"] == hier]
else:
    fdf = df[(df["date_only"] >= month_start) & (df["date_only"] <= today)]

# Header
st.markdown(f"# 🏛️ Dashboard Dirigeant — Mansa Bank")
st.caption(f"Dernière synchro à {to_local(last_fetch).strftime('%H:%M')} · Affichage : **{periode_selection}**")

# =============================================================================
# 1. KPI CLÉS (Top Metrics)
# =============================================================================
codes_actifs = set(fdf["code_agent"].dropna().unique())
codes_matches = codes_actifs & codes_enrolles_commerciaux

avd_a_deployer = len(codes_enrolles_commerciaux)
avd_deployes = len(codes_matches)
total_activations = len(fdf)

st.markdown("<h3 class='section-title'>Indicateurs Majeurs</h3>", unsafe_allow_html=True)
m1, m2, m3 = st.columns(3)
m1.metric("Total Activations", f"{total_activations:,}".replace(",", " "))
m2.metric("AVD à déployer (Enrôlés)", avd_a_deployer)
m3.metric("AVD déployés (Actifs)", avd_deployes, delta=f"{(avd_deployes/avd_a_deployer*100):.1f}%" if avd_a_deployer > 0 else "0%")

# =============================================================================
# 2. ACTIVATIONS PAR ÉQUIPE (Vue Synthétique Globalized)
# =============================================================================
st.markdown("<h3 class='section-title'>Activations par équipe</h3>", unsafe_allow_html=True)
col_graph, col_tab = st.columns([2, 1])

eq_summary = fdf["equipe"].value_counts().reset_index()
eq_summary.columns = ["Équipe", "Activations"]

with col_graph:
    fig_eq = px.bar(
        eq_summary, x="Activations", y="Équipe", orientation="h",
        text="Activations", color="Activations",
        color_continuous_scale=[T["secondary"], T["accent"]]
    )
    fig_eq.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=320, coloraxis_showscale=False, margin=dict(t=10, b=10, l=10, r=10)
    )
    fig_eq.update_traces(textposition="outside")
    st.plotly_chart(fig_eq, use_container_width=True, config={"displayModeBar": False})

with col_tab:
    eq_summary["% Part"] = ((eq_summary["Activations"] / total_activations) * 100).round(1).astype(str) + " %" if total_activations > 0 else "0 %"
    st.dataframe(eq_summary, use_container_width=True, hide_index=True)

# =============================================================================
# 3. POSITION GÉOGRAPHIQUE
# =============================================================================
st.markdown("<h3 class='section-title'>Position géolocalisée des activations</h3>", unsafe_allow_html=True)

# Recherche automatique de coordonnées GPS dans les colonnes Kobo
lat_col = next((c for c in fdf.columns if "lat" in c.lower() or "gps" in c.lower()), None)
lon_col = next((c for c in fdf.columns if "lon" in c.lower() or "lng" in c.lower()), None)

# Alternative par geolocalisation par ville si pas de coordonnées GPS directes
geo_cities = {
    "ABIDJAN": {"lat": 5.3599517, "lon": -4.0082563},
    "BOUAKE": {"lat": 7.693850, "lon": -5.030310},
    "YAMOUSSOUKRO": {"lat": 6.827620, "lon": -5.289343},
    "DALOA": {"lat": 6.877350, "lon": -6.450230},
    "SAN-PEDRO": {"lat": 4.748510, "lon": -6.636300},
    "SAN PEDRO": {"lat": 4.748510, "lon": -6.636300},
    "ABENGOUROU": {"lat": 6.729720, "lon": -3.496390},
    "KORHOGO": {"lat": 9.458030, "lon": -5.629610},
    "MAN": {"lat": 7.412510, "lon": -7.553830},
    "GAGNOA": {"lat": 6.131930, "lon": -5.950600},
}

if lat_col and lon_col and fdf[lat_col].notna().sum() > 0:
    map_df = fdf[[lat_col, lon_col, "equipe"]].dropna()
    map_df.columns = ["lat", "lon", "equipe"]
else:
    # Agrégation par ville pour la carte
    city_col = next((c for c in fdf.columns if "ville" in c.lower()), "equipe")
    map_data = []
    for city, count in fdf[city_col].value_counts().items():
        c_upper = str(city).upper().strip()
        if c_upper in geo_cities:
            map_data.append({
                "ville": city,
                "lat": geo_cities[c_upper]["lat"],
                "lon": geo_cities[c_upper]["lon"],
                "activations": count
            })
    map_df = pd.DataFrame(map_data)

if not map_df.empty:
    if "activations" in map_df.columns:
        fig_map = px.scatter_mapbox(
            map_df, lat="lat", lon="lon", size="activations",
            hover_name="ville", hover_data=["activations"],
            color_discrete_sequence=[T["accent"]], zoom=5.8, center={"lat": 7.539989, "lon": -5.547080}
        )
    else:
        fig_map = px.scatter_mapbox(
            map_df, lat="lat", lon="lon", color="equipe",
            zoom=5.8, center={"lat": 7.539989, "lon": -5.547080}
        )
    
    fig_map.update_layout(
        mapbox_style="carto-positron",
        margin=dict(t=0, b=0, l=0, r=0),
        height=450
    )
    st.plotly_chart(fig_map, use_container_width=True)
else:
    st.info("Aucune coordonnée géolocalisée disponible pour la période sélectionnée.")

st.caption("Vue Dirigeant Mansa Bank — Synthèse Exécutive.")
st.caption("AYEBIE GRAM MESCHAC - DATASCIENTIST/DATA ENGINEER / Msc DATA SCIENCE AND ANALYTICS ACITY")
