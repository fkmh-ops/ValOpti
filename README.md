# ValOpti — The Draft Maker

Application de recrutement esport Valorant : scouting de joueurs, composition de rosters (Draft Maker), prédictions de matchs et classement des équipes, à partir des données vlr.gg collectées.

| Dossier | Contenu |
|---|---|
| `app/` | Maquette d'origine (HTML statique, données fictives) et requêtes SQL de référence |
| `data/` | Données : `valorant.db` (base brute, **jamais modifiée**), `data_temp.zip` (Kaggle VCT 2021-2026), scraper vlr.gg |
| `backend/` | API **FastAPI** (Python 3.12+) + ETL de nettoyage + audit qualité + tests |
| `frontend/` | Interface **React 19 + TypeScript + Vite** (React Router, TanStack Query), design de la maquette |

## Démarrage

Prérequis : Python 3.12+ (testé en 3.14) et Node 20+.

```powershell
# 1. Backend : environnement et base nettoyée (~4 min, crée data/valopti.db)
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m etl.build_db
.venv\Scripts\python -m etl.audit          # écrit data/RAPPORT_QUALITE.md, code retour 1 si un contrôle bloquant échoue

# 2. Frontend
cd ..\frontend
npm install
npm run build                              # produit frontend/dist, servi par FastAPI

# 3. Lancer l'application complète
cd ..\backend
.venv\Scripts\python -m uvicorn valopti.main:app --port 8000
# -> http://localhost:8000   (documentation de l'API : http://localhost:8000/docs)
```

Développement front avec rechargement à chaud : lancer l'API (étape 3) puis `npm run dev` dans `frontend/` et ouvrir http://localhost:5173 (les appels `/api` sont relayés vers le port 8000).

Tests : `cd backend; .venv\Scripts\python -m pytest -q` (contrôles qualité bloquants, API, modèle, compositions).

Réentraîner le modèle : `.venv\Scripts\python -m etl.backtest` (environ 2 min), puis `.venv\Scripts\python -m etl.build_db` pour appliquer les nouveaux paramètres. Typage front : `npm run typecheck`.

## Écrans

- **Accueil** : matchs programmés avec probabilité, résultats VCT récents, top équipes, joueurs sans équipe à suivre, meilleurs ratings.
- **Scouting** : ~1 900 joueurs actifs sur 180 jours (2 900 sur 365 j), filtres région / rôle / statut / circuit / rounds / période, tri sur 11 stats, couleur selon le percentile.
- **Draft Maker** : 5 slots par rôle, choix de l'agent, note ValOpti (puissance de feu, entry, utilitaire, clutch, équilibre des rôles), alertes, projection par carte. Compositions sauvegardées **en base** (tables `compositions` / `composition_slots`).
- **Prédictions** : équipe ou composition contre équipe, BO1/3/5, veto simulé, distribution des scores, facteurs expliqués, confrontations directes.
- **Classement** : Elo ValOpti par région, et un classement Game Changers séparé.
- **Fiches** joueur / équipe en panneau latéral, avec une URL partageable (`?player=3002`, `?team=711`).

## Données : ce que fait l'ETL (`backend/etl/build_db.py`)

La base brute avait des défauts bloquants pour l'application. Chaque correction est tracée dans `etl_issues` (source `clean`) et le détail chiffré, avant et après, est dans **`data/RAPPORT_QUALITE.md`**.

- **Cartes** : 16 « cartes » parasites dans `game_maps` (noms d'agents, texte issu d'un veto mal découpé, `TBD`) supprimées, et les vetos ou maps concernés nettoyés.
- **Scores** : 24 171 BO1 avaient le score en rounds (13-7) à la place du score en maps. Ils sont convertis en 1-0 et le score en rounds est conservé dans `team1_rounds` / `team2_rounds`. Les maps à 0-0 sont reconstruites depuis les rounds quand c'est possible, sinon passées à NULL. Vainqueurs contraires au score corrigés, nuls BO2 sans vainqueur, 3 285 forfaits (0-0 sans map) marqués `is_forfeit` et exclus des statistiques.
- **Équipes en doublon** : les lignes de stats ou de rounds rattachées à une équipe homonyme absente du match sont réaffectées.
- **Agents** : la table `agents` était vide et vlr.gg ne fournit pas l'agent joué. Le référentiel des 29 agents et de leurs rôles est créé, puis 174 000 lignes de stats reçoivent leur agent par rapprochement avec le dataset Kaggle (empreinte carte + K/D/A + ACS + pseudo).
- **Équipe actuelle** : `players.current_team_id` n'était renseigné que pour 2 joueurs. Il est déduit des feuilles de match. Un joueur est « sans équipe » quand sa dernière équipe a joué au moins 2 matchs sans lui.
- **Tables dérivées** : `team_profile` (Elo, région, tier, forme), `player_profile`, `player_stats_snapshot` (90 / 180 / 365 j), `player_agent_stats`, `meta` (date des données, pool de cartes actif).

## Modèle

Les paramètres sont **choisis par backtest** (`python -m etl.backtest`) : l'historique est rejoué match par match en n'utilisant que l'information disponible avant chaque match. Entraînement avant juillet 2025, test ensuite. Le script écrit `backend/etl/model_params.json`, lu par l'ETL et l'API, et le rapport `data/RAPPORT_MODELE.md`.

- **Elo ValOpti** : recalculé chronologiquement sur tous les matchs terminés depuis 2020 (forfaits exclus). K = 64 puis 40, majoré selon l'écart de maps, départ selon le circuit du premier match, retour partiel vers la moyenne après 6 mois d'inactivité. Réduire l'Elo après un changement de roster a été testé et dégrade les prédictions : écarté.
- **Prédiction par carte** : `Δ = 0,55 × écart d'Elo + 0,25 × écart d'Elo sur la carte + 204 × écart de forme`, puis `p = 1 / (1 + 10^(−Δ/400))`. Les poids sont appris par régression logistique. Le winrate lissé par carte n'apporte rien une fois l'Elo par carte présent : retiré.
- **Résultat sur les séries jamais vues** : log loss 0,682 → 0,653, précision 61,9 % → 62,9 %. Surtout, les probabilités sont mieux calibrées : l'ancien modèle était trop sûr de lui (« 84 % » ne se réalisait que 71 % du temps).
- **Série** : combinaison des cartes d'un veto simulé sur le pool actif (7 cartes les plus jouées sur 90 j).
- **Composition** : Elo estimé par régression de l'Elo des équipes classées sur le rating moyen de leur roster, moins une pénalité si les rôles sont mal couverts.

## Limites connues (liées aux sources)

- Les **agents** ne sont connus que pour le circuit VCT (dataset Kaggle) : environ 25 % des lignes de stats. Les joueurs hors VCT ont un rôle « — ». Il faudrait scraper les profils joueurs vlr.gg (`/player`) pour compléter.
- Les stats détaillées couvrent environ 2 900 joueurs sur les 12 derniers mois : c'est la couverture du scraping des pages match.
- Les données s'arrêtent au **8 octobre 2026** : les matchs « programmés » sont ceux connus à cette date.
- Le statut « sans équipe » est une déduction. À vérifier avant de contacter un joueur.
- Les rôles de Miks et Veto (agents absents de la maquette) sont à confirmer (`AGENTS_TO_CONFIRM` dans `etl/reference.py`).
