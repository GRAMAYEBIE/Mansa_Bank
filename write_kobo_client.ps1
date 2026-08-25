$content = @'
"""
Client pour KoboToolbox : télécharge les soumissions d'un formulaire, gère le cache
local et normalise les données en DataFrame pandas exploitable par le dashboard.

Utilisation en ligne de commande :
    python kobo_client.py --inspect     # liste les colonnes disponibles dans le form
    python kobo_client.py --fetch       # force un téléchargement complet (ignore le cache)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import requests
import config


def _headers():
    if not config.KOBO_TOKEN:
        raise RuntimeError(
            "KOBO_TOKEN manquant. Définis la variable d'environnement KOBO_TOKEN "
            "(Compte Kobo > Settings > API Token) avant de lancer le script."
        )
    return {"Authorization": f"Token {config.KOBO_TOKEN}"}


def fetch_schema(asset_uid: str = None) -> dict:
    """Récupère le schéma complet du formulaire (structure, questions, ordre, labels)."""
    asset_uid = asset_uid or config.ASSET_UID
    url = f"{config.KOBO_BASE_URL}/api/v2/assets/{asset_uid}/"
    resp = requests.get(url, headers=_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def print_schema(asset_uid: str = None):
    """
    Affiche TOUTES les questions du formulaire dans leur ordre d'apparition,
    avec leur nom technique (celui à utiliser dans COLUMN_MAP) et leur libellé.
    Fiable même si un champ est vide dans les dernières soumissions.
    """
    asset_uid = asset_uid or config.ASSET_UID
    schema = fetch_schema(asset_uid)
    survey = schema.get("content", {}).get("survey", [])
    translations = schema.get("content", {}).get("translations", [None])

    print(f"Formulaire : {schema.get('name', asset_uid)}  (UID: {asset_uid})")
    print("-" * 70)
    q_num = 0
    choices = schema.get("content", {}).get("choices", [])
    choices_by_list = {}
    for c in choices:
        list_name = c.get("list_name")
        label = c.get("label")
        if isinstance(label, list):
            label = label[0] if label else ""
        choices_by_list.setdefault(list_name, []).append((c.get("name"), label))

    for item in survey:
        qtype = item.get("type", "")
        if qtype in ("start", "end", "today", "deviceid", "note"):
            continue
        name = item.get("name") or item.get("$autoname") or "?"
        label = item.get("label")
        if isinstance(label, list):
            label = label[0] if label else ""
        q_num += 1
        print(f" Q{q_num:<3} [{qtype:<16}] name='{name}'  ->  \"{label}\"")

        if qtype in ("select_one", "select_multiple"):
            list_name = item.get("select_from_list_name")
            options = choices_by_list.get(list_name, [])
            for code, opt_label in options:
                print(f"        · {code}  =  \"{opt_label}\"")


def print_schema_raw(asset_uid: str = None):
    """Affiche le JSON brut complet de survey + choices — utile pour déboguer la structure exacte."""
    asset_uid = asset_uid or config.ASSET_UID
    schema = fetch_schema(asset_uid)
    content = schema.get("content", {})
    print(json.dumps(
        {"survey": content.get("survey", []), "choices": content.get("choices", [])},
        indent=2, ensure_ascii=False,
    ))


def fetch_sample(asset_uid: str = None, limit: int = 5) -> list[dict]:
    """Récupère un petit échantillon en UNE seule requête (pas de pagination) — utilisé pour --inspect."""
    asset_uid = asset_uid or config.ASSET_UID
    url = f"{config.KOBO_BASE_URL}/api/v2/assets/{asset_uid}/data/"
    params = {"format": "json", "limit": limit}
    resp = requests.get(url, headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("results", [])


def fetch_all_submissions(asset_uid: str = None, page_size: int = 1000, since: str = None) -> list[dict]:
    """
    Télécharge TOUTES les soumissions du formulaire en suivant l'URL 'next' fournie par l'API Kobo.
    Indispensable pour dépasser la limite de 1000 lignes et récupérer les 21 et 22 août.
    """
    asset_uid = asset_uid or config.ASSET_UID
    url = f"{config.KOBO_BASE_URL}/api/v2/assets/{asset_uid}/data/"
    results = []

    params = {"format": "json", "limit": page_size}
    if since:
        params["query"] = json.dumps({"_submission_time": {"$gt": since}})

    while url:
        resp = requests.get(url, headers=_headers(), params=params, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        
        batch = payload.get("results", [])
        results.extend(batch)

        # Récupère l'URL de la page suivante fournie par Kobo
        url = payload.get("next")
        # Une fois qu'on suit 'next', les paramètres de pagination sont inclus dedans
        params = None

    return results

def _normalize_genre(value):
    if not isinstance(value, str):
        return value
    return config.GENRE_ALIASES.get(value.strip().lower(), value.strip())


def _normalize_oui_non(value):
    if not isinstance(value, str):
        return value
    return config.OUI_NON_ALIASES.get(value.strip().lower(), value.strip())


def _parse_geopoint(value):
    """
    Parse un champ geopoint Kobo/ODK, stocké comme chaîne "lat lon alt acc"
    (séparée par des espaces). Retourne (lat, lon) ou (None, None).
    """
    if not isinstance(value, str) or not value.strip():
        return None, None
    parts = value.strip().split()
    if len(parts) < 2:
        return None, None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None, None


def to_dataframe(raw_submissions: list[dict]) -> pd.DataFrame:
    """Transforme la liste JSON brute de Kobo en DataFrame propre et typé."""
    if not raw_submissions:
        return pd.DataFrame(columns=list(config.COLUMN_MAP.keys()))

    df = pd.json_normalize(raw_submissions)
    cm = config.COLUMN_MAP

    def get_col(key):
        """Renvoie la colonne mappée, ou une série vide si le mapping est None/absent."""
        col_name = cm.get(key)
        if not col_name:
            return pd.Series([None] * len(df))
        resolved = _resolve_column(df, col_name)
        if resolved:
            return df[resolved]
        return pd.Series([None] * len(df))

    out = pd.DataFrame()
    out["submission_id"] = df.get("_id", pd.Series(range(len(df))))
    out["date"] = pd.to_datetime(get_col("date"), errors="coerce", utc=True)
    out["code_parrainage"] = get_col("code_parrainage")
    out["client_telephone"] = get_col("client_telephone").astype(str).str.strip().str.replace(r"\D", "", regex=True)
    out["operateur"] = get_col("operateur").astype(str).str.upper().replace("NONE", None)
    out["genre"] = get_col("genre").apply(_normalize_genre)
    out["categorie_socio_pro"] = get_col("categorie_socio_pro")
    out["ville"] = get_col("ville")
    out["deplafonnement"] = get_col("deplafonnement").apply(_normalize_oui_non)
    out["transaction_effectuee"] = get_col("transaction_effectuee").apply(_normalize_oui_non)
    out["montant_transaction"] = pd.to_numeric(get_col("montant_transaction"), errors="coerce")
    out["incident_signale"] = get_col("incident_signale").apply(_normalize_oui_non)
    out["incident_detail"] = get_col("incident_detail")
    out["nom_agent"] = get_col("nom_agent")

    # Coordonnées GPS : priorité au geopoint réel de la zone d'activation (Q9),
    # bien plus fiable que "_geolocation" (qui reflète souvent la position de
    # démarrage de l'app, pas le lieu réel de l'activation).
    geo_raw = get_col("geopoint_activation")
    parsed = geo_raw.apply(_parse_geopoint)
    out["latitude"] = parsed.apply(lambda t: t[0])
    out["longitude"] = parsed.apply(lambda t: t[1])

    # Fallback sur "_geolocation" si le champ dédié est vide pour certaines lignes
    if "_geolocation" in df.columns:
        geoloc = df["_geolocation"]
        fallback_lat = geoloc.apply(lambda g: g[0] if isinstance(g, list) and len(g) == 2 else None)
        fallback_lon = geoloc.apply(lambda g: g[1] if isinstance(g, list) and len(g) == 2 else None)
        out["latitude"] = out["latitude"].fillna(fallback_lat)
        out["longitude"] = out["longitude"].fillna(fallback_lon)

    out = out.dropna(subset=["submission_id"]).reset_index(drop=True)
    return out


def _resolve_column(df: pd.DataFrame, target_name: str) -> str | None:
    """
    Retrouve une colonne même si Kobo l'a préfixée par un nom de groupe
    (ex: "group_dk7ug64/Code_de_parrainage_ex_DSA_001" au lieu de
    "Code_de_parrainage_ex_DSA_001", quand la question est dans une section/groupe).
    """
    if target_name in df.columns:
        return target_name
    for col in df.columns:
        if col.split("/")[-1] == target_name:
            return col
    return None


def to_dataframe_supervisor(raw_submissions: list[dict]) -> pd.DataFrame:
    """Transforme les soumissions du formulaire SUPERVISION en DataFrame propre."""
    if not raw_submissions:
        return pd.DataFrame(columns=list(config.SUPERVISOR_COLUMN_MAP.keys()))

    df = pd.json_normalize(raw_submissions)
    cm = config.SUPERVISOR_COLUMN_MAP

    def get_col(key):
        target = cm.get(key)
        if not target:
            return pd.Series([None] * len(df))
        resolved = _resolve_column(df, target)
        if resolved:
            return df[resolved]
        return pd.Series([None] * len(df))

    out = pd.DataFrame()
    out["submission_id"] = df.get("_id", pd.Series(range(len(df))))
    out["date"] = pd.to_datetime(get_col("date"), errors="coerce", utc=True)
    out["code_parrainage_agent"] = get_col("code_parrainage_agent").astype(str).str.strip().str.upper()
    out["nom_superviseur"] = get_col("nom_superviseur")
    out["region"] = get_col("region")
    out["localite_region"] = get_col("localite_region")
    out["localites_couvertes"] = get_col("localites_couvertes")
    out["commune_quartier"] = get_col("commune_quartier")
    out["nb_prospects"] = pd.to_numeric(get_col("nb_prospects"), errors="coerce").fillna(0)
    out["nb_demos"] = pd.to_numeric(get_col("nb_demos"), errors="coerce").fillna(0)
    out["nb_activations_confirmees"] = pd.to_numeric(get_col("nb_activations_confirmees"), errors="coerce").fillna(0)
    out["nb_refus"] = pd.to_numeric(get_col("nb_refus"), errors="coerce").fillna(0)
    out["type_incident"] = get_col("type_incident")
    out["action_corrective"] = get_col("action_corrective")

    out = out.dropna(subset=["submission_id"]).reset_index(drop=True)
    return out


def to_dataframe_enrollment(raw_submissions: list[dict]) -> pd.DataFrame:
    """Transforme les soumissions du formulaire ENROLLEMENT en DataFrame propre."""
    if not raw_submissions:
        return pd.DataFrame(columns=list(config.ENROLLMENT_COLUMN_MAP.keys()))

    df = pd.json_normalize(raw_submissions)
    cm = config.ENROLLMENT_COLUMN_MAP

    def get_col(key):
        target = cm.get(key)
        if not target:
            return pd.Series([None] * len(df))
        resolved = _resolve_column(df, target)
        if resolved:
            return df[resolved]
        return pd.Series([None] * len(df))

    out = pd.DataFrame()
    out["submission_id"] = df.get("_id", pd.Series(range(len(df))))
    out["date"] = pd.to_datetime(get_col("date"), errors="coerce", utc=True)
    out["code_parrainage"] = get_col("code_parrainage").astype(str).str.strip().str.upper()
    out["numero_the_code"] = get_col("numero_the_code")
    out["nom_prenoms"] = get_col("nom_prenoms")
    out["role"] = get_col("role")
    out["nom_superviseur"] = get_col("nom_superviseur")
    out["region"] = get_col("region")
    out["localite_region"] = get_col("localite_region")
    out["ville"] = get_col("ville")
    out["equipe"] = get_col("equipe")

    out = out.dropna(subset=["submission_id"]).reset_index(drop=True)
    # Un agent peut avoir plusieurs soumissions d'enrôlement (corrections) -> on garde la plus récente par code
    out = out.sort_values("date").drop_duplicates(subset="code_parrainage", keep="last").reset_index(drop=True)
    return out


def _load_generic(
    asset_uid: str,
    cache_file: str,
    last_fetch_file: str,
    transform_fn,
    force_refresh: bool = False,
    full_resync: bool = False,
) -> tuple[pd.DataFrame, datetime]:
    """
    Cache + fetch complet (pas d'incrémental : l'expérience a montré que le fetch
    incrémental par date de soumission pouvait silencieusement ne rien récupérer
    de neuf. Pour ce volume de données, un fetch complet à chaque synchro est
    largement assez rapide et beaucoup plus fiable — la priorité va à l'exactitude
    des chiffres affichés, pas à la marginale économie de bande passante.
    """
    os.makedirs(config.CACHE_DIR, exist_ok=True)

    has_cache = os.path.exists(last_fetch_file) and os.path.exists(cache_file)
    if has_cache and not force_refresh and not full_resync:
        with open(last_fetch_file) as f:
            last_fetch = datetime.fromisoformat(f.read().strip())
        age = (datetime.now(timezone.utc) - last_fetch).total_seconds()
        if age < config.REFRESH_INTERVAL_SECONDS:
            return pd.read_parquet(cache_file), last_fetch

    raw = fetch_all_submissions(asset_uid=asset_uid)
    df = transform_fn(raw)
    df.to_parquet(cache_file, index=False)

    now = datetime.now(timezone.utc)
    with open(last_fetch_file, "w") as f:
        f.write(now.isoformat())

    return df, now


def load_data(force_refresh: bool = False, full_resync: bool = False) -> tuple[pd.DataFrame, datetime]:
    """
    Charge les données du formulaire ACTIVATIONS en combinant cache local + fetch incrémental.
    `full_resync=True` ignore tout et retélécharge l'historique complet.
    Retourne (df, timestamp_dernier_fetch).
    """
    return _load_generic(
        asset_uid=config.ASSET_UID,
        cache_file=config.CACHE_FILE,
        last_fetch_file=config.LAST_FETCH_FILE,
        transform_fn=to_dataframe,
        force_refresh=force_refresh,
        full_resync=full_resync,
    )


def load_supervisor_data(force_refresh: bool = False, full_resync: bool = False) -> tuple[pd.DataFrame, datetime]:
    """Charge les données du formulaire SUPERVISION (même logique de cache/incrémental)."""
    return _load_generic(
        asset_uid=config.SUPERVISOR_ASSET_UID,
        cache_file=config.SUPERVISOR_CACHE_FILE,
        last_fetch_file=config.SUPERVISOR_LAST_FETCH_FILE,
        transform_fn=to_dataframe_supervisor,
        force_refresh=force_refresh,
        full_resync=full_resync,
    )


def load_enrollment_data(force_refresh: bool = False, full_resync: bool = False) -> tuple[pd.DataFrame, datetime]:
    """Charge les données du formulaire ENROLLEMENT (base de référence des agents)."""
    return _load_generic(
        asset_uid=config.ENROLLMENT_ASSET_UID,
        cache_file=config.ENROLLMENT_CACHE_FILE,
        last_fetch_file=config.ENROLLMENT_LAST_FETCH_FILE,
        transform_fn=to_dataframe_enrollment,
        force_refresh=force_refresh,
        full_resync=full_resync,
    )


def inspect_fields(asset_uid: str = None):
    """Affiche les champs disponibles dans le formulaire pour t'aider à remplir COLUMN_MAP."""
    raw = fetch_sample(asset_uid=asset_uid, limit=5)
    if not raw:
        print_schema(asset_uid)
        return

    print("Champs détectés dans une soumission réelle :")
    for key in sorted(raw[0].keys()):
        print(" -", key, "=", json.dumps(raw[0][key])[:80])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect", action="store_true", help="Liste les champs présents dans un échantillon de soumissions")
    parser.add_argument("--schema", action="store_true", help="Liste TOUTES les questions du formulaire, dans l'ordre, avec leur nom technique (fiable même si des champs sont vides)")
    parser.add_argument("--schema-raw", action="store_true", help="Affiche le JSON brut complet (survey + choices) — diagnostic")
    parser.add_argument("--fetch", action="store_true", help="Force un téléchargement complet")
    parser.add_argument("--asset", type=str, default=None, help="UID du formulaire à cibler (par défaut : celui de config.py)")
    args = parser.parse_args()

    if args.schema:
        print_schema(args.asset)
        sys.exit(0)

    if args.schema_raw:
        print_schema_raw(args.asset)
        sys.exit(0)

    if args.inspect:
        inspect_fields(args.asset)
        sys.exit(0)

    if args.fetch:
        df, ts = load_data(force_refresh=True, full_resync=True)
        print(f"[Activations] {len(df)} soumissions téléchargées à {ts.isoformat()}")
        print(df.head())
        sdf, sts = load_supervisor_data(force_refresh=True, full_resync=True)
        print(f"\n[Supervision] {len(sdf)} soumissions téléchargées à {sts.isoformat()}")
        print(sdf.head())
        edf, ets = load_enrollment_data(force_refresh=True, full_resync=True)
        print(f"\n[Enrôlement] {len(edf)} agent(s) téléchargé(s) à {ets.isoformat()}")
        print(edf.head())
        sys.exit(0)

    parser.print_help()

'@
[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot "kobo_client.py"), $content, [System.Text.UTF8Encoding]::new($true))
$firstLine = Get-Content (Join-Path $PSScriptRoot "kobo_client.py") -TotalCount 1
if ($firstLine -like "*content = @*") { Write-Host "ERREUR : kobo_client.py mal ecrit !" -ForegroundColor Red } else { Write-Host "OK : kobo_client.py ecrit correctement" -ForegroundColor Green }
