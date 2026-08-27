# Dashboard Activations — Mansa Bank (Kobo → Streamlit)

Dashboard temps réel branché sur ton formulaire Kobo `aX2Y4fgZQ8uZRsQepPaREw`
(Activation client). Les données sont mises en cache localement et
re-téléchargées automatiquement toutes les 4h.

## 1. Installation

```bash
pip install -r requirements.txt
```

## 2. Configuration — ton token API Kobo

1. Va sur `https://eu.kobotoolbox.org` → clique sur ton profil → **Account settings** → **API token** (ou `https://eu.kobotoolbox.org/token/`).
2. Copie le token.
3. Crée un fichier `.env` (copie `.env.example`) et colle ton token :

```bash
cp .env.example .env
# puis édite .env et mets ton vrai KOBO_TOKEN
```

Ou plus simple, exporte-le directement dans le terminal avant de lancer :

```bash
export KOBO_TOKEN="ton_token_ici"
```

## 3. IMPORTANT — Vérifier les noms de colonnes

Je ne connais pas les noms exacts des questions de ton formulaire Kobo. Avant
de lancer le dashboard, vérifie-les avec :

```bash
python kobo_client.py --inspect
```

Ça t'affiche soit les vraies clés des soumissions existantes, soit le schéma
du formulaire s'il n'y a pas encore de données. Compare ça avec `COLUMN_MAP`
dans `config.py` et corrige les noms si besoin (ex: `operateur` → `operateur_mobile_money`
si c'est comme ça que ta question s'appelle dans Kobo).

## 4. Lancer le dashboard

``bash
streamlit run app.py
```
`
## 5. Lancer le dasboard superviseur 

``bash
streamlit run superviseur.py
```

Ça ouvre le dashboard dans ton navigateur. Le bouton **"Forcer le
rafraîchissement"** dans la barre latérale permet de re-télécharger tout de
suite sans attendre les 30 min pour les 2 dashboard.

## Ce que le dashboard affiche

- Nombre d'activations global depuis le début de l'activité
- Nombre d'activations aujourd'hui **avec tendance vs hier**
- Nombre d'activations cette semaine **avec tendance vs semaine dernière**
- Évolution des activations dans le temps (courbe)
- **Heatmap heure × jour de semaine** pour repérer les pics d'activité (utile pour organiser les équipes terrain)
- Opérateurs les plus utilisés (graph)
- Répartition Homme / Femme
- Catégorie socio-professionnelle
- Activations par ville
- Ville n°1 (top activations)
- Classement des codes de parrainage avec **médailles 🥇🥈🥉** pour le top 3
- **Alerte de fraîcheur des données** : si aucune nouvelle activation depuis plus de 24h, un bandeau rouge le signale (utile pour détecter un problème de collecte terrain)
- Table détaillée + export **CSV et Excel** (multi-onglets : détail, par ville, top parrainage)
- Filtres : ville, opérateur, période
- **Page qui se rafraîchit automatiquement** toutes les 5 min (configurable), donc plus besoin de cliquer sur rien pour voir les nouvelles données

## Fonctionnement du rafraîchissement (important)

Deux mécanismes distincts qui travaillent ensemble :

1. **Synchro avec Kobo (toutes les 2h)** : `REFRESH_INTERVAL_SECONDS`. Le
   script ne télécharge que les soumissions **nouvelles depuis la dernière
   synchro** (fetch incrémental), pas tout l'historique — donc c'est rapide
   et léger, même avec des milliers de soumissions.
2. **Rafraîchissement de la page (toutes les 5 min)** : `AUTO_RELOAD_MS`. La
   page Streamlit se recharge toute seule pour vérifier si le cache a de
   nouvelles données à afficher — donc si quelqu'un laisse le dashboard
   ouvert sur un écran, il se met à jour tout seul sans qu'on touche à rien.

Tu peux ajuster les deux indépendamment dans `.env` ou `config.py`.

## Déploiement (optionnel)

Pour que ce soit accessible 24/7 sans garder ton PC allumé, tu peux déployer
gratuitement sur **Streamlit Community Cloud** (connecte juste ce dossier à
un repo GitHub et ajoute `KOBO_TOKEN` dans les "Secrets" de l'app), ou sur ta
VM Oracle Cloud Always Free à côté de ton pipeline Mansa Bank (Dagster/MinIO)
si tu veux tout centraliser au même endroit plus tard.

## Notes techniques

- `kobo_client.py` gère la pagination automatique ET le fetch incrémental
  (ne retélécharge que les nouvelles soumissions), donc ça reste rapide même
  avec des dizaines de milliers de soumissions à 2h de cadence.
- Les données sont mises en cache en local dans `cache/activations.parquet`
  et fusionnées (dédupliquées par ID de soumission) à chaque synchro.
- `python kobo_client.py --fetch` force une resynchronisation complète
  (utile si tu changes le formulaire ou en cas de doute sur la cohérence).
- Si `is_stale` (pas de nouvelle activation depuis 24h) tu peux ajuster le
  seuil via `STALE_DATA_HOURS` dans `.env`.
