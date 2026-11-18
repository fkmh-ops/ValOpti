# Rapport qualité des données ValOpti

- Base brute : `valorant.db` (non modifiée)
- Base nettoyée : `valopti.db` (générée par `python -m etl.build_db`)
- Date des données (dernier match terminé) : **2026-10-08**
- Contrôles bloquants en échec sur la base nettoyée : **0**

## Contrôles

Bloquant = doit être à 0 après nettoyage. Les contrôles non bloquants décrivent des limites de la source, conservées et documentées.

| Contrôle | Bloquant | Base brute | Base nettoyée | Statut | Note |
|---|:-:|--:|--:|:-:|---|
| Violations de clés étrangères | oui | 0 | 0 | OK |  |
| PRAGMA integrity_check en erreur | oui | 0 | 0 | OK |  |
| Entrées de game_maps qui ne sont pas des cartes | oui | 16 | 0 | OK | noms d'agents et texte issus d'un veto mal découpé |
| Table agents vide ou rôles manquants | oui | 1 | 0 | OK |  |
| Matchs datés avant 2020 (epoch) | oui | 1 | 0 | OK |  |
| Score de match > 5 (score en rounds stocké comme score en maps) | oui | 24 171 | 0 | OK |  |
| Vainqueur contraire au score | oui | 69 | 0 | OK |  |
| Match terminé, score départagé, sans vainqueur | oui | 8 | 0 | OK | les matchs gagnés par une équipe inconnue (Unknown, TBD, bye) restent sans vainqueur |
| Match nul (1-1, 2-2) avec un vainqueur | oui | 26 | 0 | OK |  |
| Vainqueur qui n'est pas une des deux équipes | oui | 0 | 0 | OK |  |
| Matchs 0-0 sans map non identifiés comme forfaits | oui | 3 284 | 0 | OK |  |
| Score du match ≠ maps gagnées (maps manquantes) |  | 181 | 161 | info | conservé tel quel et tracé : le score officiel prime, certaines maps n'ont pas été scrapées |
| Matchs avec une équipe inconnue (TBD) |  | 280 | 280 | info | matchs à venir dont l'adversaire n'est pas encore connu |
| Maps jouées rattachées à une « carte » invalide | oui | 247 | 0 | OK |  |
| Maps à 0-0 | oui | 231 | 0 | OK |  |
| Vainqueur de map contraire au score | oui | 4 | 0 | OK |  |
| Score de map impossible en règles Valorant (hors NULL) |  | 379 | 148 | info | 12-13 / 13-12 : prolongation tronquée côté vlr.gg ; signalé, non corrigé faute de source |
| Liste des rounds incomplète (rounds_complete = 0) |  | 998 | 998 | info | déjà signalé par l'ETL d'origine |
| Somme des mi-temps ≠ score |  | 75 | 75 | info |  |
| Stats joueur rattachées à une équipe absente du match | oui | 70 | 0 | OK |  |
| Rounds gagnés par une équipe absente du match | oui | 103 | 0 | OK |  |
| kd_diff ≠ kills − deaths | oui | 0 | 0 | OK |  |
| fk_diff ≠ FK − FD | oui | 0 | 0 | OK |  |
| Stats hors bornes (rating>4, ACS>700, KAST/HS hors 0-100, kills/deaths<0) | oui | 0 | 0 | OK |  |
| Lignes de stats sans agent |  | 696 388 | 522 072 | info | vlr.gg (scraper) ne renvoie pas l'agent ; rempli depuis Kaggle uniquement pour le circuit VCT |
| Lignes de stats sans rating |  | 123 260 | 123 260 | info | rating absent sur vlr.gg pour 2020-2021 : exclu des moyennes |
| Couples map/équipe avec ≠ 5 joueurs |  | 367 | 367 | info |  |
| Duels avec kills négatifs | oui | 0 | 0 | OK |  |
| Économie : rounds gagnés > joués | oui | 0 | 0 | OK |  |
| Joueurs actifs sans équipe courante | oui | 907 | 0 | OK | base brute : current_team_id n'était renseigné que pour 2 joueurs |
| Pseudos partagés par plusieurs joueurs |  | 5 022 | 5 022 | info | homonymes légitimes (ghost, demon...) : distingués par vlr_player_id |
| Joueurs sans identifiant vlr.gg |  | 17 226 | 17 226 | info |  |
| Noms d'équipe partagés par plusieurs équipes |  | 528 | 528 | info | « Team », « Orgless »... : équipes amateurs homonymes |
| Événements finissant avant de commencer | oui | 18 | 0 | OK |  |
| Événements sans statut |  | 2 | 2 | info |  |
| Régions couvertes par team_rankings (vlr.gg) |  | 8 | 8 | info | 8 régions secondaires seulement : l'app utilise l'Elo ValOpti calculé sur tous les matchs |
| player_stats_snapshot vide | oui | 1 | 0 | OK |  |
| player_agent_stats vide | oui | 1 | 0 | OK |  |

## Corrections appliquées (etl_issues, source = clean)

| Code | Sévérité | Lignes |
|---|---|--:|
| AGENT_CONFLICT | warning | 1 115 |
| MAP_UNKNOWN | info | 247 |
| MAP_SCORE_UNKNOWN | warning | 231 |
| TEAM_REMAPPED | warning | 183 |
| MATCH_SCORE_VS_MAPS | warning | 167 |
| MATCH_WINNER_FIXED | warning | 73 |
| DRAW_WINNER_REMOVED | warning | 26 |
| VETO_JUNK_MAP_REMOVED | warning | 20 |
| EVENT_END_BEFORE_START | warning | 18 |
| MAP_WINNER_FIXED | warning | 10 |
| AGENT_ROLE_TO_CONFIRM | info | 2 |
| AGENTS_BACKFILLED | info | 1 |
| BO1_ROUND_SCORE_CONVERTED | warning | 1 |
| CURRENT_TEAM_DERIVED | info | 1 |
| DATE_INVALID | warning | 1 |
| FORFEIT_FLAGGED | info | 1 |

## Rapprochement des agents (Kaggle VCT 2021-2026 → player_map_stats)

Empreinte : carte + kills + deaths + assists + ACS, puis pseudo. Si le pseudo a changé, l'empreinte seule est acceptée quand elle est unique.

```json
{
  "rows": 273052,
  "matched_exact": 157723,
  "ambiguous": 12911,
  "matched_stats": 24998,
  "non_numeric": 415,
  "no_match": 76938,
  "agent_multi_or_unknown": 67,
  "assigned": 174316,
  "conflicts": 1115
}
```

| Année | Lignes de stats | Avec agent | Couverture |
|---|--:|--:|--:|
| 2020 | 66 020 | 2 410 | 4% |
| 2021 | 153 821 | 71 814 | 47% |
| 2022 | 138 429 | 53 291 | 38% |
| 2023 | 103 325 | 10 354 | 10% |
| 2024 | 93 861 | 12 822 | 14% |
| 2025 | 76 820 | 13 722 | 18% |
| 2026 | 64 112 | 9 903 | 15% |

## Volumes

| Table | Brute | Nettoyée |
|---|--:|--:|
| agents | 0 | 29 |
| composition_slots | — | 0 |
| compositions | — | 0 |
| etl_issues | 32 915 | 35 012 |
| event_rosters | 147 611 | 147 611 |
| event_teams | 29 650 | 29 650 |
| events | 2 995 | 2 995 |
| game_maps | 29 | 13 |
| h2h_history | 297 288 | 297 288 |
| match_map_vetos | 97 068 | 97 048 |
| match_maps | 69 727 | 69 727 |
| match_vods | 34 802 | 34 802 |
| matches | 107 970 | 107 970 |
| meta | — | 6 |
| news_articles | 30 | 30 |
| player_agent_stats | 0 | 29 710 |
| player_duels | 1 060 015 | 1 060 015 |
| player_event_placements | 3 | 3 |
| player_map_stats | 696 388 | 696 388 |
| player_match_advanced | 213 140 | 213 140 |
| player_matches | 3 | 3 |
| player_profile | — | 21 065 |
| player_social_links | 6 | 6 |
| player_stats_snapshot | 0 | 5 774 |
| player_team_membership | 117 720 | 117 720 |
| players | 45 795 | 45 795 |
| prediction_maps | — | 0 |
| predictions | — | 0 |
| raw_ingest | 0 | 0 |
| rounds | 1 423 794 | 1 423 794 |
| team_aliases | 23 802 | 23 802 |
| team_map_economy | 47 950 | 47 950 |
| team_map_elo | — | 23 921 |
| team_profile | — | 21 105 |
| team_rankings | 263 | 263 |
| teams | 21 105 | 21 105 |

## Indicateurs dérivés

```json
{
  "VETO_JUNK_MAP_REMOVED": 20,
  "MAP_UNKNOWN": 247,
  "game_maps_removed": 16,
  "MAP_SCORE_FROM_ROUNDS": 0,
  "MAP_SCORE_UNKNOWN": 231,
  "MAP_WINNER_FIXED": 10,
  "player_map_stats_team_remapped": 70,
  "player_map_stats_team_deleted": 0,
  "rounds_team_remapped": 103,
  "rounds_team_deleted": 0,
  "player_match_advanced_team_remapped": 10,
  "player_match_advanced_team_deleted": 0,
  "DATE_INVALID": 1,
  "BO1_ROUND_SCORE_CONVERTED": 24171,
  "DRAW_WINNER_REMOVED": 26,
  "FORFEIT_FLAGGED": 3285,
  "MATCH_WINNER_FIXED": 73,
  "MATCH_SCORE_VS_MAPS": 167,
  "EVENT_END_BEFORE_START": 18,
  "snapshot_date": "2026-10-08",
  "teams_with_elo": 20208,
  "players_current_team_set": 1732,
  "snapshot_90d_players": 869,
  "snapshot_180d_players": 1965,
  "snapshot_365d_players": 2940,
  "players_with_role": 10251,
  "foreign_key_violations": 0,
  "duration_s": 264
}
```
