"""Contrôles d'intégrité et de propreté des données.

Exécute la même batterie de contrôles sur la base brute et la base nettoyée, puis écrit un rapport
Markdown comparatif (data/RAPPORT_QUALITE.md).

Usage : python -m etl.audit [--raw ../data/valorant.db] [--clean ../data/valopti.db] [--out ../data/RAPPORT_QUALITE.md]
Code retour 1 si un contrôle bloquant échoue sur la base nettoyée.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

REAL_MAPS = "('Ascent','Bind','Haven','Split','Icebox','Breeze','Fracture','Pearl','Lotus','Sunset','Abyss','Corrode','Summit')"
VALID_MAP_SCORE = """((MAX(team1_score,team2_score)=13 AND MIN(team1_score,team2_score)<=11)
                    OR (ABS(team1_score-team2_score)=2 AND MIN(team1_score,team2_score)>=12))"""


@dataclass
class Check:
    code: str
    label: str
    sql: str            # renvoie un entier : nombre de lignes en défaut
    blocking: bool      # doit valoir 0 sur la base nettoyée
    note: str = ""


CHECKS: list[Check] = [
    # Intégrité référentielle et structure
    Check("FK", "Violations de clés étrangères", "SELECT COUNT(*) FROM pragma_foreign_key_check", True),
    Check("INTEGRITY", "PRAGMA integrity_check en erreur",
          "SELECT COUNT(*) FROM pragma_integrity_check WHERE integrity_check <> 'ok'", True),
    Check("MAPS_JUNK", "Entrées de game_maps qui ne sont pas des cartes",
          f"SELECT COUNT(*) FROM game_maps WHERE name NOT IN {REAL_MAPS}", True,
          "noms d'agents et texte issus d'un veto mal découpé"),
    Check("AGENTS_EMPTY", "Table agents vide ou rôles manquants",
          "SELECT CASE WHEN COUNT(*)=0 THEN 1 ELSE SUM(role IS NULL) END FROM agents", True),
    # Matchs
    Check("M_DATE", "Matchs datés avant 2020 (epoch)", "SELECT COUNT(*) FROM matches WHERE match_date < '2020-01-01'", True),
    Check("M_ROUNDS_AS_MAPS", "Score de match > 5 (score en rounds stocké comme score en maps)",
          "SELECT COUNT(*) FROM matches WHERE team1_score > 5 OR team2_score > 5", True),
    Check("M_WINNER_VS_SCORE", "Vainqueur contraire au score",
          """SELECT COUNT(*) FROM matches WHERE status='final' AND team1_score <> team2_score AND winner_team_id <>
             CASE WHEN team1_score > team2_score THEN team1_id ELSE team2_id END""", True),
    Check("M_WINNER_MISSING", "Match terminé, score départagé, sans vainqueur",
          """SELECT COUNT(*) FROM matches WHERE status='final' AND team1_score <> team2_score AND winner_team_id IS NULL
             AND team1_id IS NOT NULL AND team2_id IS NOT NULL""", True,
          "les matchs gagnés par une équipe inconnue (Unknown, TBD, bye) restent sans vainqueur"),
    Check("M_DRAW_WITH_WINNER", "Match nul (1-1, 2-2) avec un vainqueur",
          "SELECT COUNT(*) FROM matches WHERE status='final' AND team1_score = team2_score AND team1_score > 0 AND winner_team_id IS NOT NULL", True),
    Check("M_WINNER_OUTSIDER", "Vainqueur qui n'est pas une des deux équipes",
          "SELECT COUNT(*) FROM matches WHERE winner_team_id IS NOT NULL AND winner_team_id NOT IN (team1_id, team2_id)", True),
    Check("M_FORFEIT_UNFLAGGED", "Matchs 0-0 sans map non identifiés comme forfaits",
          """SELECT COUNT(*) FROM matches m WHERE status='final' AND COALESCE(team1_score,0)=0 AND COALESCE(team2_score,0)=0
             AND NOT EXISTS (SELECT 1 FROM match_maps mm WHERE mm.match_id=m.match_id)
             AND {forfeit_unflagged}""", True),
    Check("M_SCORE_VS_MAPS", "Score du match ≠ maps gagnées (maps manquantes)",
          """SELECT COUNT(*) FROM (SELECT m.match_id FROM matches m JOIN match_maps mm USING(match_id) {bo_filter}
             GROUP BY m.match_id HAVING m.team1_score <> SUM(mm.winner_team_id=m.team1_id)
             OR m.team2_score <> SUM(mm.winner_team_id=m.team2_id))""", False,
          "conservé tel quel et tracé : le score officiel prime, certaines maps n'ont pas été scrapées"),
    Check("M_TEAMS_NULL", "Matchs avec une équipe inconnue (TBD)",
          "SELECT COUNT(*) FROM matches WHERE team1_id IS NULL OR team2_id IS NULL", False,
          "matchs à venir dont l'adversaire n'est pas encore connu"),
    # Maps
    Check("MM_MAP_JUNK", "Maps jouées rattachées à une « carte » invalide",
          f"SELECT COUNT(*) FROM match_maps mm JOIN game_maps gm USING(map_id) WHERE gm.name NOT IN {REAL_MAPS}", True),
    Check("MM_ZERO", "Maps à 0-0", "SELECT COUNT(*) FROM match_maps WHERE team1_score=0 AND team2_score=0", True),
    Check("MM_WINNER", "Vainqueur de map contraire au score",
          """SELECT COUNT(*) FROM match_maps mm JOIN matches m USING(match_id) WHERE mm.team1_score <> mm.team2_score
             AND mm.winner_team_id <> CASE WHEN mm.team1_score > mm.team2_score THEN m.team1_id ELSE m.team2_id END""", True),
    Check("MM_SCORE_SHAPE", "Score de map impossible en règles Valorant (hors NULL)",
          f"SELECT COUNT(*) FROM match_maps WHERE team1_score IS NOT NULL AND NOT {VALID_MAP_SCORE}", False,
          "12-13 / 13-12 : prolongation tronquée côté vlr.gg ; signalé, non corrigé faute de source"),
    Check("MM_ROUNDS_INCOMPLETE", "Liste des rounds incomplète (rounds_complete = 0)",
          "SELECT COUNT(*) FROM match_maps WHERE rounds_complete = 0", False, "déjà signalé par l'ETL d'origine"),
    Check("MM_HALVES", "Somme des mi-temps ≠ score",
          "SELECT COUNT(*) FROM match_maps WHERE team1_score_ct + team1_score_t + COALESCE(team1_score_ot,0) <> team1_score", False),
    # Stats joueurs
    Check("PMS_FOREIGN_TEAM", "Stats joueur rattachées à une équipe absente du match",
          """SELECT COUNT(*) FROM player_map_stats s JOIN match_maps mm USING(match_map_id) JOIN matches m USING(match_id)
             WHERE s.team_id NOT IN (m.team1_id, m.team2_id)""", True),
    Check("ROUND_FOREIGN_TEAM", "Rounds gagnés par une équipe absente du match",
          """SELECT COUNT(*) FROM rounds r JOIN match_maps mm USING(match_map_id) JOIN matches m USING(match_id)
             WHERE r.winner_team_id NOT IN (m.team1_id, m.team2_id)""", True),
    Check("PMS_KD", "kd_diff ≠ kills − deaths", "SELECT COUNT(*) FROM player_map_stats WHERE kd_diff <> kills - deaths", True),
    Check("PMS_FK", "fk_diff ≠ FK − FD", "SELECT COUNT(*) FROM player_map_stats WHERE fk_diff <> first_kills - first_deaths", True),
    Check("PMS_RANGE", "Stats hors bornes (rating>4, ACS>700, KAST/HS hors 0-100, kills/deaths<0)",
          """SELECT COUNT(*) FROM player_map_stats WHERE rating > 4 OR acs > 700 OR kast_pct NOT BETWEEN 0 AND 100
             OR hs_pct NOT BETWEEN 0 AND 100 OR kills < 0 OR deaths < 0""", True),
    Check("PMS_AGENT_NULL", "Lignes de stats sans agent", "SELECT COUNT(*) FROM player_map_stats WHERE agent_id IS NULL", False,
          "vlr.gg (scraper) ne renvoie pas l'agent ; rempli depuis Kaggle uniquement pour le circuit VCT"),
    Check("PMS_RATING_NULL", "Lignes de stats sans rating", "SELECT COUNT(*) FROM player_map_stats WHERE rating IS NULL", False,
          "rating absent sur vlr.gg pour 2020-2021 : exclu des moyennes"),
    Check("PMS_TEAM_SIZE", "Couples map/équipe avec ≠ 5 joueurs",
          "SELECT COUNT(*) FROM (SELECT match_map_id, team_id FROM player_map_stats GROUP BY 1,2 HAVING COUNT(*) <> 5)", False),
    Check("DUELS_NEG", "Duels avec kills négatifs", "SELECT COUNT(*) FROM player_duels WHERE kills < 0 OR deaths < 0", True),
    Check("ECO_WON_GT_PLAYED", "Économie : rounds gagnés > joués",
          """SELECT COUNT(*) FROM team_map_economy WHERE eco_won > eco_played OR semi_eco_won > semi_eco_played
             OR semi_buy_won > semi_buy_played OR full_buy_won > full_buy_played""", True),
    # Référentiels
    Check("PLAYERS_NO_TEAM", "Joueurs actifs sans équipe courante",
          """SELECT COUNT(*) FROM players WHERE current_team_id IS NULL AND player_id IN (
             SELECT s.player_id FROM player_map_stats s JOIN match_maps mm USING(match_map_id) JOIN matches m USING(match_id)
             WHERE m.match_date >= date((SELECT MAX(match_date) FROM matches WHERE status='final'), '-90 day'))
             {free_agent_filter}""", True,
          "base brute : current_team_id n'était renseigné que pour 2 joueurs"),
    Check("PLAYERS_DUP_IGN", "Pseudos partagés par plusieurs joueurs",
          "SELECT COUNT(*) FROM (SELECT ign_norm FROM players GROUP BY 1 HAVING COUNT(*) > 1)", False,
          "homonymes légitimes (ghost, demon...) : distingués par vlr_player_id"),
    Check("PLAYERS_NO_VLR", "Joueurs sans identifiant vlr.gg", "SELECT COUNT(*) FROM players WHERE vlr_player_id IS NULL", False),
    Check("TEAMS_DUP_NAME", "Noms d'équipe partagés par plusieurs équipes",
          "SELECT COUNT(*) FROM (SELECT name_norm FROM teams GROUP BY 1 HAVING COUNT(*) > 1)", False,
          "« Team », « Orgless »... : équipes amateurs homonymes"),
    Check("EVENTS_DATES", "Événements finissant avant de commencer",
          "SELECT COUNT(*) FROM events WHERE end_date < start_date", True),
    Check("EVENTS_STATUS", "Événements sans statut", "SELECT COUNT(*) FROM events WHERE status IS NULL", False),
    Check("RANKINGS_COVERAGE", "Régions couvertes par team_rankings (vlr.gg)",
          "SELECT COUNT(DISTINCT region) FROM team_rankings", False,
          "8 régions secondaires seulement : l'app utilise l'Elo ValOpti calculé sur tous les matchs"),
    Check("SNAPSHOT_EMPTY", "player_stats_snapshot vide", "SELECT COUNT(*) = 0 FROM player_stats_snapshot", True),
    Check("AGENT_STATS_EMPTY", "player_agent_stats vide", "SELECT COUNT(*) = 0 FROM player_agent_stats", True),
]


def has_col(con, table, col) -> bool:
    return any(r[1] == col for r in con.execute(f"PRAGMA table_info({table})"))


def run(db: Path) -> dict[str, int | str]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    clean = has_col(con, "matches", "is_forfeit")
    has_pp = con.execute("SELECT 1 FROM sqlite_master WHERE name='player_profile'").fetchone() is not None
    subs = {
        "forfeit_unflagged": "is_forfeit = 0" if clean else "1",
        "bo_filter": "WHERE m.best_of IS NOT 1" if clean else "",
        "free_agent_filter": ("AND player_id NOT IN (SELECT player_id FROM player_profile WHERE status <> 'active')"
                              if has_pp else ""),
    }
    out = {}
    for c in CHECKS:
        try:
            out[c.code] = con.execute(c.sql.format(**subs)).fetchone()[0]
        except sqlite3.Error as e:
            out[c.code] = f"n/a ({e})"
    con.close()
    return out


def table_counts(db: Path) -> dict[str, int]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY 1")]
    res = {n: con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}
    con.close()
    return res


def fmt(v) -> str:
    return f"{v:,}".replace(",", " ") if isinstance(v, int) else str(v)


def report(raw: Path, clean: Path, out: Path) -> int:
    r, c = run(raw), run(clean)
    tr, tc = table_counts(raw), table_counts(clean)
    summary_file = clean.parent / "valopti_build_summary.json"
    summary = json.loads(summary_file.read_text(encoding="utf-8")) if summary_file.exists() else {}
    con = sqlite3.connect(f"file:{clean}?mode=ro", uri=True)
    issues = con.execute("""SELECT code, severity, COUNT(*) FROM etl_issues WHERE source='clean'
                            GROUP BY 1,2 ORDER BY 3 DESC""").fetchall()
    cover = con.execute("""SELECT substr(m.match_date,1,4), COUNT(*), SUM(s.agent_id IS NOT NULL)
                           FROM player_map_stats s JOIN match_maps mm USING(match_map_id) JOIN matches m USING(match_id)
                           GROUP BY 1 ORDER BY 1""").fetchall()
    con.close()

    failed = [ch for ch in CHECKS if ch.blocking and c[ch.code] not in (0, None)]
    L = ["# Rapport qualité des données ValOpti", "",
         f"- Base brute : `{raw.name}` (non modifiée)",
         f"- Base nettoyée : `{clean.name}` (générée par `python -m etl.build_db`)",
         f"- Date des données (dernier match terminé) : **{summary.get('snapshot_date', '?')}**",
         f"- Contrôles bloquants en échec sur la base nettoyée : **{len(failed)}**", "",
         "## Contrôles", "",
         "Bloquant = doit être à 0 après nettoyage. Les contrôles non bloquants décrivent des limites de la source, conservées et documentées.", "",
         "| Contrôle | Bloquant | Base brute | Base nettoyée | Statut | Note |",
         "|---|:-:|--:|--:|:-:|---|"]
    for ch in CHECKS:
        vr, vc = r[ch.code], c[ch.code]
        ok = vc in (0, None) if ch.blocking else True
        status = "OK" if (ch.blocking and ok) else ("ÉCHEC" if ch.blocking else "info")
        L.append(f"| {ch.label} | {'oui' if ch.blocking else ''} | {fmt(vr)} | {fmt(vc)} | {status} | {ch.note} |")
    L += ["", "## Corrections appliquées (etl_issues, source = clean)", "",
          "| Code | Sévérité | Lignes |", "|---|---|--:|"]
    L += [f"| {code} | {sev} | {fmt(n)} |" for code, sev, n in issues]
    if "agents_backfill" in summary:
        L += ["", "## Rapprochement des agents (Kaggle VCT 2021-2026 → player_map_stats)", "",
              "Empreinte : carte + kills + deaths + assists + ACS, puis pseudo. Si le pseudo a changé, l'empreinte seule est acceptée quand elle est unique.", "",
              "```json", json.dumps(json.loads(summary["agents_backfill"]), indent=2), "```", "",
              "| Année | Lignes de stats | Avec agent | Couverture |", "|---|--:|--:|--:|"]
        L += [f"| {y} | {fmt(n)} | {fmt(a)} | {a / n:.0%} |" for y, n, a in cover if y]
    L += ["", "## Volumes", "", "| Table | Brute | Nettoyée |", "|---|--:|--:|"]
    for t in sorted(set(tr) | set(tc)):
        L.append(f"| {t} | {fmt(tr.get(t, '—'))} | {fmt(tc.get(t, '—'))} |")
    L += ["", "## Indicateurs dérivés", "", "```json",
          json.dumps({k: v for k, v in summary.items() if k != "agents_backfill"}, indent=2, ensure_ascii=False), "```", ""]
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"Rapport écrit : {out}")
    for ch in failed:
        print(f"  ÉCHEC {ch.code}: {c[ch.code]}")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=DATA / "valorant.db")
    ap.add_argument("--clean", type=Path, default=DATA / "valopti.db")
    ap.add_argument("--out", type=Path, default=DATA / "RAPPORT_QUALITE.md")
    a = ap.parse_args()
    sys.exit(report(a.raw, a.clean, a.out))


if __name__ == "__main__":
    main()
