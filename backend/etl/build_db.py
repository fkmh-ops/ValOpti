"""Construit data/valopti.db à partir de data/valorant.db (jamais modifiée).

Étapes :
  1. copie de la base brute
  2. nettoyage (cartes parasites, scores, vainqueurs, équipes incohérentes, dates)
  3. agents : référentiel + rapprochement des agents joués depuis le dataset Kaggle (data_temp.zip)
  4. tables dérivées pour l'application (Elo, profils équipes/joueurs, snapshots de stats, pools d'agents)
  5. tables applicatives (compositions, prédictions)

Chaque correction est tracée dans etl_issues (source = 'clean').

Usage : python -m etl.build_db [--raw ../data/valorant.db] [--out ../data/valopti.db] [--kaggle ../data/data_temp.zip]
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import shutil
import sqlite3
import sys
import time
import unicodedata
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from etl.ratings import EloCfg, event_tier, load_history, simulate
from etl.reference import AGENT_BY_KEY, AGENTS, AGENTS_TO_CONFIRM, REAL_MAPS, agent_key, macro_region

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SNAPSHOT_WINDOWS = (90, 180, 365)
PARAMS = json.loads((Path(__file__).with_name("model_params.json")).read_text(encoding="utf-8"))
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()


class Builder:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.summary: dict[str, int | str] = {}

    # ------------------------------------------------------------------ utils
    def x(self, sql: str, params=()) -> sqlite3.Cursor:
        return self.con.execute(sql, params)

    def one(self, sql: str, params=()):
        return self.con.execute(sql, params).fetchone()[0]

    def log(self, code: str, entity_key, detail: str, severity: str = "info"):
        self.x(
            "INSERT INTO etl_issues(created_at, severity, source, entity_key, code, detail) VALUES (?,?,?,?,?,?)",
            (NOW, severity, "clean", None if entity_key is None else str(entity_key), code, detail),
        )

    def log_many(self, code: str, rows, detail_fn, severity: str = "info"):
        n = 0
        for r in rows:
            self.log(code, r[0], detail_fn(r), severity)
            n += 1
        self.summary[code] = self.summary.get(code, 0) + n
        return n

    def step(self, name: str):
        print(f"[{time.strftime('%H:%M:%S')}] {name}", flush=True)

    # ------------------------------------------------------------ 2. nettoyage
    def clean_maps(self):
        self.step("game_maps : suppression des entrées parasites")
        rows = self.x("SELECT map_id, name FROM game_maps").fetchall()
        junk = [(mid, name) for mid, name in rows if name not in REAL_MAPS]
        ids = [mid for mid, _ in junk]
        q = ",".join("?" * len(ids))
        vetos = self.x(f"SELECT match_id, step, map_id FROM match_map_vetos WHERE map_id IN ({q})", ids).fetchall()
        names = dict(junk)
        self.log_many("VETO_JUNK_MAP_REMOVED", vetos,
                      lambda r: f"étape {r[1]} : « {names[r[2]]} » n'est pas une carte (ban d'agent ou texte)", "warning")
        self.x(f"DELETE FROM match_map_vetos WHERE map_id IN ({q})", ids)
        mm = self.x(f"SELECT match_map_id, map_id FROM match_maps WHERE map_id IN ({q})", ids).fetchall()
        self.log_many("MAP_UNKNOWN", mm, lambda r: f"carte « {names[r[1]]} » remplacée par NULL (carte inconnue)")
        self.x(f"UPDATE match_maps SET map_id = NULL WHERE map_id IN ({q})", ids)
        self.x(f"DELETE FROM game_maps WHERE map_id IN ({q})", ids)
        self.summary["game_maps_removed"] = len(ids)

    def clean_map_scores(self):
        self.step("match_maps : scores 0-0 et vainqueurs incohérents")
        # Scores 0-0 : on reconstruit depuis la liste des rounds quand elle existe
        zero = self.x("""
            SELECT mm.match_map_id, m.team1_id, m.team2_id,
                   SUM(r.winner_team_id = m.team1_id), SUM(r.winner_team_id = m.team2_id)
            FROM match_maps mm JOIN matches m USING(match_id)
            LEFT JOIN rounds r ON r.match_map_id = mm.match_map_id
            WHERE mm.team1_score = 0 AND mm.team2_score = 0
            GROUP BY mm.match_map_id""").fetchall()
        fixed, nulled = [], []
        for mmid, t1, t2, s1, s2 in zero:
            if s1 or s2:
                winner = t1 if s1 > s2 else t2 if s2 > s1 else None
                self.x("""UPDATE match_maps SET team1_score=?, team2_score=?, rounds_played=?, winner_team_id=?
                          WHERE match_map_id=?""", (s1, s2, s1 + s2, winner, mmid))
                fixed.append((mmid, s1, s2))
            else:
                self.x("""UPDATE match_maps SET team1_score=NULL, team2_score=NULL, rounds_played=NULL,
                          winner_team_id=NULL WHERE match_map_id=?""", (mmid,))
                nulled.append((mmid,))
        self.log_many("MAP_SCORE_FROM_ROUNDS", fixed, lambda r: f"score 0-0 remplacé par {r[1]}-{r[2]} (liste des rounds)", "warning")
        self.log_many("MAP_SCORE_UNKNOWN", nulled, lambda r: "score 0-0 sans rounds : score mis à NULL", "warning")

        bad = self.x("""
            SELECT mm.match_map_id, mm.winner_team_id,
                   CASE WHEN mm.team1_score > mm.team2_score THEN m.team1_id ELSE m.team2_id END
            FROM match_maps mm JOIN matches m USING(match_id)
            WHERE mm.team1_score <> mm.team2_score AND (mm.winner_team_id IS NULL OR mm.winner_team_id <>
                  CASE WHEN mm.team1_score > mm.team2_score THEN m.team1_id ELSE m.team2_id END)""").fetchall()
        for mmid, _, w in bad:
            self.x("UPDATE match_maps SET winner_team_id=? WHERE match_map_id=?", (w, mmid))
        self.log_many("MAP_WINNER_FIXED", bad, lambda r: f"vainqueur {r[1]} -> {r[2]} (d'après le score)", "warning")

    def remap_foreign_team(self, table: str, team_col: str, key_cols: tuple[str, ...], mm_col="match_map_id"):
        """Lignes dont l'équipe n'est pas une des deux équipes du match : on rapproche par nom normalisé."""
        join = (f"JOIN match_maps mm ON mm.match_map_id = x.{mm_col} JOIN matches m ON m.match_id = mm.match_id"
                if mm_col == "match_map_id" else f"JOIN matches m ON m.match_id = x.{mm_col}")
        keys = ", ".join(f"x.{k}" for k in key_cols)
        rows = self.x(f"""
            SELECT {keys}, x.{team_col},
                   (SELECT t2.team_id FROM teams t1 JOIN teams t2 ON t2.name_norm = t1.name_norm
                     WHERE t1.team_id = x.{team_col} AND t2.team_id IN (m.team1_id, m.team2_id))
            FROM {table} x {join}
            WHERE x.{team_col} IS NOT NULL AND x.{team_col} NOT IN (m.team1_id, m.team2_id)""").fetchall()
        where = " AND ".join(f"{k}=?" for k in key_cols)
        remapped = deleted = 0
        for r in rows:
            key, old, new = r[:len(key_cols)], r[len(key_cols)], r[len(key_cols) + 1]
            if new:
                self.x(f"UPDATE {table} SET {team_col}=? WHERE {where}", (new, *key))
                self.log("TEAM_REMAPPED", "/".join(map(str, key)), f"{table}: équipe {old} -> {new} (doublon de nom)", "warning")
                remapped += 1
            else:
                self.x(f"DELETE FROM {table} WHERE {where}", key)
                self.log("ROW_FOREIGN_TEAM_DELETED", "/".join(map(str, key)), f"{table}: équipe {old} absente du match", "error")
                deleted += 1
        self.summary[f"{table}_team_remapped"] = remapped
        self.summary[f"{table}_team_deleted"] = deleted

    def clean_matches(self):
        self.step("matches : dates, scores en rounds, nuls, forfaits, vainqueurs")
        self.x("ALTER TABLE matches ADD COLUMN best_of INTEGER")
        self.x("ALTER TABLE matches ADD COLUMN is_forfeit INTEGER NOT NULL DEFAULT 0")
        self.x("ALTER TABLE matches ADD COLUMN team1_rounds INTEGER")
        self.x("ALTER TABLE matches ADD COLUMN team2_rounds INTEGER")

        rows = self.x("SELECT match_id, match_date FROM matches WHERE match_date < '2020-01-01'").fetchall()
        self.log_many("DATE_INVALID", rows, lambda r: f"date {r[1]} (epoch) mise à NULL", "warning")
        self.x("UPDATE matches SET match_date = NULL WHERE match_date < '2020-01-01'")

        # BO1 : vlr.gg affiche le score en rounds (13-7) à la place du score en maps
        rows = self.x("SELECT match_id, team1_score, team2_score FROM matches WHERE team1_score > 5 OR team2_score > 5").fetchall()
        for mid, s1, s2 in rows:
            self.x("""UPDATE matches SET team1_rounds=?, team2_rounds=?, team1_score=?, team2_score=?, best_of=1,
                      winner_team_id = CASE WHEN ? > ? THEN team1_id WHEN ? > ? THEN team2_id ELSE winner_team_id END
                      WHERE match_id=?""", (s1, s2, int(s1 > s2), int(s2 > s1), s1, s2, s2, s1, mid))
        self.summary["BO1_ROUND_SCORE_CONVERTED"] = len(rows)
        self.log("BO1_ROUND_SCORE_CONVERTED", None, f"{len(rows)} matchs BO1 : score en rounds converti en score en maps (rounds conservés)", "warning")
        # La map unique d'un BO1 sans score retrouve son score en rounds
        self.x("""UPDATE match_maps SET
                    team1_score = (SELECT team1_rounds FROM matches m WHERE m.match_id = match_maps.match_id),
                    team2_score = (SELECT team2_rounds FROM matches m WHERE m.match_id = match_maps.match_id),
                    winner_team_id = (SELECT winner_team_id FROM matches m WHERE m.match_id = match_maps.match_id)
                  WHERE team1_score IS NULL AND match_id IN (SELECT match_id FROM matches WHERE team1_rounds IS NOT NULL)
                    AND match_id IN (SELECT match_id FROM match_maps GROUP BY match_id HAVING COUNT(*) = 1)""")

        # 1-1 = BO2 nul : pas de vainqueur
        rows = self.x("SELECT match_id FROM matches WHERE status='final' AND team1_score = team2_score AND team1_score > 0 AND winner_team_id IS NOT NULL").fetchall()
        self.log_many("DRAW_WINNER_REMOVED", rows, lambda r: "match nul (BO2) : vainqueur supprimé", "warning")
        self.x("UPDATE matches SET winner_team_id = NULL, best_of = 2 WHERE status='final' AND team1_score = team2_score AND team1_score > 0")

        # 0-0 (ou score absent) avec vainqueur = forfait / résultat administratif
        n = self.x("""UPDATE matches SET is_forfeit = 1 WHERE status='final' AND COALESCE(team1_score,0) = 0
                      AND COALESCE(team2_score,0) = 0
                      AND NOT EXISTS (SELECT 1 FROM match_maps mm WHERE mm.match_id = matches.match_id)""").rowcount
        self.summary["FORFEIT_FLAGGED"] = n
        self.log("FORFEIT_FLAGGED", None, f"{n} matchs 0-0 sans map marqués is_forfeit=1 (exclus des stats et de l'Elo)")

        # Vainqueur absent ou contraire au score
        rows = self.x("""SELECT match_id, winner_team_id, CASE WHEN team1_score > team2_score THEN team1_id ELSE team2_id END
                         FROM matches WHERE status='final' AND team1_score <> team2_score
                         AND (winner_team_id IS NULL OR winner_team_id <> CASE WHEN team1_score > team2_score THEN team1_id ELSE team2_id END)""").fetchall()
        for mid, _, w in rows:
            self.x("UPDATE matches SET winner_team_id=? WHERE match_id=?", (w, mid))
        self.log_many("MATCH_WINNER_FIXED", rows, lambda r: f"vainqueur {r[1]} -> {r[2]} (d'après le score)", "warning")

        # Score du match différent des maps gagnées : on garde le score officiel, on signale
        rows = self.x("""SELECT m.match_id, m.team1_score, m.team2_score,
                   SUM(mm.winner_team_id = m.team1_id), SUM(mm.winner_team_id = m.team2_id)
            FROM matches m JOIN match_maps mm USING(match_id) WHERE m.best_of IS NOT 1
            GROUP BY m.match_id HAVING m.team1_score <> SUM(mm.winner_team_id = m.team1_id)
                OR m.team2_score <> SUM(mm.winner_team_id = m.team2_id)""").fetchall()
        self.log_many("MATCH_SCORE_VS_MAPS", rows, lambda r: f"score {r[1]}-{r[2]} mais maps gagnées {r[3]}-{r[4]} (maps manquantes)", "warning")

        # best_of déduit du score quand il n'est pas connu
        self.x("""UPDATE matches SET best_of = CASE MAX(COALESCE(team1_score,0), COALESCE(team2_score,0))
                    WHEN 1 THEN 1 WHEN 2 THEN 3 WHEN 3 THEN 5 ELSE NULL END
                  WHERE best_of IS NULL AND status='final'""")

    def clean_events(self):
        self.step("events : dates incohérentes")
        rows = self.x("SELECT event_id, start_date, end_date FROM events WHERE end_date < start_date").fetchall()
        self.log_many("EVENT_END_BEFORE_START", rows, lambda r: f"fin {r[2]} avant début {r[1]} : end_date mise à NULL", "warning")
        self.x("UPDATE events SET end_date = NULL WHERE end_date < start_date")
        self.x("UPDATE events SET status = 'completed' WHERE status IS NULL AND COALESCE(end_date, start_date) < (SELECT MAX(match_date) FROM matches)")

    # -------------------------------------------------------------- 3. agents
    def load_agents(self, kaggle_zip: Path | None):
        self.step("agents : référentiel et rôles")
        self.x("DELETE FROM agents")
        self.x("INSERT INTO agents(agent_id, name, role) VALUES " + ",".join("(?,?,?)" for _ in AGENTS),
               [v for i, (n, r) in enumerate(AGENTS, 1) for v in (i, n, r)])
        for n in AGENTS_TO_CONFIRM:
            self.log("AGENT_ROLE_TO_CONFIRM", n, "agent absent de la maquette, rôle à confirmer", "info")
        agent_id = {n: i for i, (n, _) in enumerate(AGENTS, 1)}

        if not kaggle_zip or not kaggle_zip.exists():
            print("  ! data_temp.zip introuvable : agents joués non renseignés")
            return
        self.step("agents : rapprochement Kaggle -> player_map_stats (empreinte joueur/map/K/D/A/ACS)")
        idx: dict[tuple, list[tuple]] = collections.defaultdict(list)
        for mmid, pid, ign, mp, k, d, a, acs in self.x("""
                SELECT s.match_map_id, s.player_id, p.ign_norm, gm.name, s.kills, s.deaths, s.assists, s.acs
                FROM player_map_stats s JOIN players p USING(player_id)
                JOIN match_maps mm USING(match_map_id) JOIN game_maps gm ON gm.map_id = mm.map_id"""):
            idx[(mp, k, d, a, acs)].append((ign, mmid, pid))

        # deux niveaux : exact (pseudo + empreinte) prioritaire sur empreinte seule (pseudo changé depuis)
        assign_lvl: dict[str, dict[tuple, int]] = {"exact": {}, "stats": {}}
        conflict_lvl: dict[str, set[tuple]] = {"exact": set(), "stats": set()}
        stats = collections.Counter()
        with zipfile.ZipFile(kaggle_zip) as z:
            files = sorted(n for n in z.namelist() if n.endswith("matches/overview.csv"))
            for name in files:
                with z.open(name) as fh:
                    for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", newline="")):
                        if r["Side"] != "both" or r["Map"] not in REAL_MAPS:
                            continue
                        stats["rows"] += 1
                        ag = AGENT_BY_KEY.get(agent_key(r["Agents"]))
                        if not ag:
                            stats["agent_multi_or_unknown"] += 1
                            continue
                        try:
                            key = (r["Map"], int(r["Kills"]), int(r["Deaths"]), int(r["Assists"]),
                                   int(r["Average Combat Score"]))
                        except ValueError:
                            stats["non_numeric"] += 1
                            continue
                        cands = idx.get(key)
                        if not cands:
                            stats["no_match"] += 1
                            continue
                        ign = norm(r["Player"])
                        exact = [c for c in cands if c[0] == ign]
                        pick = exact if exact else cands  # pseudo changé depuis : empreinte seule si unique
                        if len(pick) != 1:
                            stats["ambiguous"] += 1
                            continue
                        lvl = "exact" if exact else "stats"
                        stats["matched_" + lvl] += 1
                        k2 = (pick[0][1], pick[0][2])
                        tgt = assign_lvl[lvl]
                        if k2 in tgt and tgt[k2] != agent_id[ag]:
                            conflict_lvl[lvl].add(k2)
                        tgt[k2] = agent_id[ag]
        assign: dict[tuple, int] = {}
        conflicts: set[tuple] = set()
        for lvl in ("stats", "exact"):  # exact écrase stats
            for k2 in conflict_lvl[lvl]:
                assign_lvl[lvl].pop(k2, None)
            assign.update(assign_lvl[lvl])
        for k2 in conflict_lvl["exact"] | (conflict_lvl["stats"] - assign.keys()):
            conflicts.add(k2)
            self.log("AGENT_CONFLICT", f"{k2[0]}/{k2[1]}", "deux agents différents pour la même ligne : laissé NULL", "warning")
        self.x("UPDATE player_map_stats SET agent_id = NULL")
        self.con.executemany("UPDATE player_map_stats SET agent_id=? WHERE match_map_id=? AND player_id=?",
                             [(a, mm, p) for (mm, p), a in assign.items()])
        stats["assigned"] = len(assign)
        stats["conflicts"] = len(conflicts)
        self.summary["agents_backfill"] = json.dumps(dict(stats))
        self.log("AGENTS_BACKFILLED", None, json.dumps(dict(stats)))
        print("  ", dict(stats))

    # ----------------------------------------------------- 4. tables dérivées
    def derived(self):
        snap = self.one("SELECT MAX(match_date) FROM matches WHERE status='final'")
        snap_d = date.fromisoformat(snap)
        self.summary["snapshot_date"] = snap
        self.x("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

        self.step("pool de cartes actif (90 derniers jours)")
        since90 = (snap_d - timedelta(days=90)).isoformat()
        rows = self.x("""SELECT gm.map_id, gm.name, COUNT(*) FROM match_maps mm JOIN matches m USING(match_id)
                         JOIN game_maps gm ON gm.map_id = mm.map_id WHERE m.match_date >= ? GROUP BY 1,2 ORDER BY 3 DESC""",
                      (since90,)).fetchall()
        total = sum(r[2] for r in rows) or 1
        pool = [{"map_id": r[0], "name": r[1]} for r in rows if r[2] / total >= 0.05][:7]
        meta = {"snapshot_date": snap, "built_at": NOW, "map_pool": json.dumps(pool),
                "model_version": PARAMS["model_version"], "model_weights": json.dumps(PARAMS["weights"]),
                "model_backtest": json.dumps(PARAMS.get("backtest", {}))}

        self._team_profiles(snap_d)
        self._player_profiles(snap_d)
        self._snapshots(snap_d)
        self._agent_stats(snap_d)

        self.x("DELETE FROM meta")
        self.con.executemany("INSERT INTO meta VALUES (?,?)", list(meta.items()))

    def _team_profiles(self, snap_d: date):
        self.step("team_profile : Elo ValOpti, région, tier, forme")
        # Elo : même moteur et mêmes paramètres que le backtest (etl/model_params.json)
        cfg = EloCfg(**PARAMS["elo"])
        st, _ = simulate(load_history(self.con), cfg)
        elo, n, hist = st.elo, st.n, st.hist
        self.x("DROP TABLE IF EXISTS team_map_elo")
        self.x("""CREATE TABLE team_map_elo (team_id INTEGER NOT NULL REFERENCES teams(team_id),
                  map_id INTEGER NOT NULL REFERENCES game_maps(map_id), offset REAL NOT NULL, PRIMARY KEY (team_id, map_id))""")
        self.con.executemany("INSERT INTO team_map_elo VALUES (?,?,?)",
                             [(t, m, v) for (t, m), v in st.map_off.items() if v])

        since365 = (snap_d - timedelta(days=365)).isoformat()
        # tier déduit des événements joués sur 12 mois
        tier_rows = self.x("""SELECT t.team_id, e.name FROM matches m JOIN events e ON e.event_id = m.event_id
                              JOIN teams t ON t.team_id IN (m.team1_id, m.team2_id) WHERE m.match_date >= ?""",
                           (since365,)).fetchall()
        rank = {"VCT": 3, "Challengers": 2, "Game Changers": 1}
        tiers: dict[int, str] = {}
        for tid, ev in tier_rows:
            t = event_tier(ev)
            if t and rank[t] > rank.get(tiers.get(tid, ""), 0):
                tiers[tid] = t

        # région : pays de l'équipe, sinon pays majoritaire des joueurs, sinon région des événements
        teams = self.x("SELECT team_id, country_code FROM teams").fetchall()
        pl_votes = collections.defaultdict(collections.Counter)
        for tid, cc in self.x("""SELECT s.team_id, p.country_code FROM player_map_stats s JOIN players p USING(player_id)
                                 WHERE p.country_code IS NOT NULL"""):
            r = macro_region(cc)
            if r:
                pl_votes[tid][r] += 1
        ev_votes = collections.defaultdict(collections.Counter)
        for tid, reg in self.x("""SELECT t.team_id, e.region FROM matches m JOIN events e ON e.event_id = m.event_id
                                  JOIN teams t ON t.team_id IN (m.team1_id, m.team2_id)"""):
            r = macro_region(reg)
            if r:
                ev_votes[tid][r] += 1

        self.x("DROP TABLE IF EXISTS team_profile")
        self.x("""CREATE TABLE team_profile (
            team_id INTEGER PRIMARY KEY REFERENCES teams(team_id), region TEXT, region_source TEXT, tier TEXT,
            elo INTEGER, elo_matches INTEGER, wins_365 INTEGER, losses_365 INTEGER, last_match_date DATE,
            streak_type TEXT, streak_length INTEGER, last5 TEXT)""")
        out = []
        for tid, cc in teams:
            reg, src = macro_region(cc), "country"
            if not reg and pl_votes[tid]:
                reg, src = pl_votes[tid].most_common(1)[0][0], "players"
            if not reg and ev_votes[tid]:
                reg, src = ev_votes[tid].most_common(1)[0][0], "events"
            h = hist.get(tid, [])
            recent = [x for x in h if x[0] >= since365]
            res = [x[1] for x in reversed(h)]
            k = 0
            while k < len(res) and res[k] == res[0]:
                k += 1
            out.append((tid, reg, src if reg else None, tiers.get(tid, "Autre"),
                        round(elo[tid]) if tid in n else None, n[tid],
                        sum(x[1] == "W" for x in recent), sum(x[1] == "L" for x in recent),
                        h[-1][0] if h else None, res[0] if res else None, k if res else None, "".join(res[:5])))
        self.con.executemany("INSERT INTO team_profile VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", out)
        self.summary["teams_with_elo"] = len(n)

    def _player_profiles(self, snap_d: date):
        self.step("player_profile : équipe actuelle, statut (actif / libre / inactif), région")
        self.x("DROP TABLE IF EXISTS _pm")
        self.x("""CREATE TEMP TABLE _pm AS
                  SELECT s.player_id, s.team_id, m.match_id, m.match_date, mm.rounds_played
                  FROM player_map_stats s JOIN match_maps mm USING(match_map_id) JOIN matches m USING(match_id)
                  WHERE m.match_date IS NOT NULL""")
        self.x("CREATE INDEX _pm_p ON _pm(player_id, match_date)")
        self.x("CREATE INDEX _pm_t ON _pm(team_id, match_date)")
        self.x("DROP TABLE IF EXISTS player_profile")
        self.x("""CREATE TABLE player_profile (
            player_id INTEGER PRIMARY KEY REFERENCES players(player_id), region TEXT, last_team_id INTEGER,
            first_seen DATE, last_seen DATE, maps_total INTEGER, rounds_total INTEGER,
            team_matches_since INTEGER, status TEXT CHECK (status IN ('active','free_agent','inactive')),
            main_role TEXT, is_flex INTEGER)""")
        self.x("""INSERT INTO player_profile(player_id, last_team_id, first_seen, last_seen, maps_total, rounds_total)
                  SELECT a.player_id,
                         (SELECT b.team_id FROM _pm b WHERE b.player_id = a.player_id ORDER BY b.match_date DESC, b.match_id DESC LIMIT 1),
                         MIN(a.match_date), MAX(a.match_date), COUNT(*), SUM(a.rounds_played)
                  FROM _pm a GROUP BY a.player_id""")
        # Matchs détaillés joués par la dernière équipe après le dernier match du joueur
        self.x("""UPDATE player_profile SET team_matches_since = (
                    SELECT COUNT(DISTINCT t.match_id) FROM _pm t
                    WHERE t.team_id = player_profile.last_team_id AND t.match_date > player_profile.last_seen)""")
        s180 = (snap_d - timedelta(days=180)).isoformat()
        s365 = (snap_d - timedelta(days=365)).isoformat()
        self.x("""UPDATE player_profile SET status = CASE
                    WHEN team_matches_since >= 2 AND last_seen >= ? THEN 'free_agent'
                    WHEN last_seen < ? THEN 'inactive'
                    WHEN team_matches_since >= 2 THEN 'inactive'
                    ELSE 'active' END""", (s365, s180))
        # Région
        team_reg = dict(self.x("SELECT team_id, region FROM team_profile"))
        rows = self.x("""SELECT pp.player_id, p.country_code, pp.last_team_id FROM player_profile pp
                         JOIN players p USING(player_id)""").fetchall()
        self.con.executemany("UPDATE player_profile SET region=? WHERE player_id=?",
                             [(macro_region(cc) or team_reg.get(t), pid) for pid, cc, t in rows])
        # players.current_team_id : vide dans la base brute (2 lignes), on le renseigne pour les actifs
        self.x("UPDATE players SET current_team_id = NULL")
        n = self.x("""UPDATE players SET current_team_id = (SELECT last_team_id FROM player_profile pp
                      WHERE pp.player_id = players.player_id AND pp.status = 'active')
                      WHERE player_id IN (SELECT player_id FROM player_profile WHERE status='active')""").rowcount
        self.summary["players_current_team_set"] = n
        self.log("CURRENT_TEAM_DERIVED", None,
                 f"players.current_team_id renseigné pour {n} joueurs actifs (équipe du dernier match, joueur toujours aligné)")

    def _snapshots(self, snap_d: date):
        self.step("player_stats_snapshot : 90 / 180 / 365 jours")
        self.x("DELETE FROM player_stats_snapshot")
        cols = [r[1] for r in self.x("PRAGMA table_info(player_stats_snapshot)")]
        if "clutch_per100" not in cols:
            self.x("ALTER TABLE player_stats_snapshot ADD COLUMN clutch_per100 REAL")
            self.x("ALTER TABLE player_stats_snapshot ADD COLUMN maps_played INTEGER")
        snap = snap_d.isoformat()
        for days in SNAPSHOT_WINDOWS:
            since = (snap_d - timedelta(days=days)).isoformat()
            self.x("""
            WITH w AS (
                SELECT s.*, mm.rounds_played AS rp, m.match_id, m.match_date
                FROM player_map_stats s JOIN match_maps mm USING(match_map_id) JOIN matches m USING(match_id)
                WHERE m.match_date > ? AND m.match_date <= ? AND mm.rounds_played > 0 AND m.is_forfeit = 0
            ), cl AS (
                SELECT a.player_id, SUM(a.clutch_1v1 + a.clutch_1v2 + a.clutch_1v3 + a.clutch_1v4 + a.clutch_1v5) AS cl,
                       SUM((SELECT SUM(mm.rounds_played) FROM match_maps mm WHERE mm.match_id = a.match_id)) AS rnd
                FROM player_match_advanced a JOIN matches m USING(match_id)
                WHERE m.match_date > ? AND m.match_date <= ? GROUP BY a.player_id
            ), last_team AS (
                SELECT player_id, team_id FROM (
                    SELECT player_id, team_id, ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY match_date DESC, match_id DESC) rn FROM w
                ) WHERE rn = 1
            ), ag AS (
                SELECT player_id, GROUP_CONCAT(name, ',') AS agents FROM (
                    SELECT w.player_id, a.name, ROW_NUMBER() OVER (PARTITION BY w.player_id ORDER BY COUNT(*) DESC) rn
                    FROM w JOIN agents a ON a.agent_id = w.agent_id GROUP BY w.player_id, a.name
                ) WHERE rn <= 3 GROUP BY player_id
            )
            INSERT INTO player_stats_snapshot(snapshot_date, region, timespan_days, player_id, team_id, agents,
                rounds_played, maps_played, rating, acs, kd, kast_pct, adr, kpr, apr, fkpr, fdpr, hs_pct, clutch_pct, clutch_per100)
            SELECT ?, 'all', ?, w.player_id, lt.team_id, ag.agents, SUM(w.rp), COUNT(*),
                   SUM(w.rating * w.rp) / NULLIF(SUM(CASE WHEN w.rating IS NOT NULL THEN w.rp END), 0),
                   SUM(w.acs * w.rp) * 1.0 / NULLIF(SUM(CASE WHEN w.acs IS NOT NULL THEN w.rp END), 0),
                   SUM(w.kills) * 1.0 / NULLIF(SUM(w.deaths), 0),
                   SUM(w.kast_pct * w.rp) / NULLIF(SUM(CASE WHEN w.kast_pct IS NOT NULL THEN w.rp END), 0),
                   SUM(w.adr * w.rp) / NULLIF(SUM(CASE WHEN w.adr IS NOT NULL THEN w.rp END), 0),
                   SUM(w.kills) * 1.0 / SUM(w.rp), SUM(w.assists) * 1.0 / SUM(w.rp),
                   SUM(w.first_kills) * 1.0 / SUM(w.rp), SUM(w.first_deaths) * 1.0 / SUM(w.rp),
                   SUM(w.hs_pct * w.kills) / NULLIF(SUM(CASE WHEN w.hs_pct IS NOT NULL THEN w.kills END), 0),
                   NULL, 100.0 * cl.cl / NULLIF(cl.rnd, 0)
            FROM w LEFT JOIN last_team lt ON lt.player_id = w.player_id
            LEFT JOIN ag ON ag.player_id = w.player_id
            LEFT JOIN cl ON cl.player_id = w.player_id
            GROUP BY w.player_id""", (since, snap, since, snap, snap, days))
            self.summary[f"snapshot_{days}d_players"] = self.one(
                "SELECT COUNT(*) FROM player_stats_snapshot WHERE timespan_days=?", (days,))

    def _agent_stats(self, snap_d: date):
        self.step("player_agent_stats et rôle principal")
        self.x("DELETE FROM player_agent_stats")
        since = (snap_d - timedelta(days=365)).isoformat()
        # Fenêtre 12 mois, ou tout l'historique si le joueur n'a aucun agent connu sur 12 mois
        self.x("""
        WITH base AS (
            SELECT s.player_id, s.agent_id, s.rating, s.acs, s.kills, s.deaths, s.adr, s.kast_pct, mm.rounds_played rp,
                   m.match_date >= ? AS recent
            FROM player_map_stats s JOIN match_maps mm USING(match_map_id) JOIN matches m USING(match_id)
            WHERE s.agent_id IS NOT NULL AND mm.rounds_played > 0
        ), has_recent AS (SELECT player_id FROM base WHERE recent GROUP BY player_id),
        sel AS (
            SELECT b.* FROM base b WHERE b.recent OR b.player_id NOT IN (SELECT player_id FROM has_recent)
        )
        INSERT INTO player_agent_stats(player_id, agent_id, usage, rounds, rating, acs, kd, adr, kast_pct, extra_json)
        SELECT player_id, agent_id,
               COUNT(*) * 1.0 / SUM(COUNT(*)) OVER (PARTITION BY player_id),
               SUM(rp),
               SUM(rating * rp) / NULLIF(SUM(CASE WHEN rating IS NOT NULL THEN rp END), 0),
               SUM(acs * rp) * 1.0 / NULLIF(SUM(CASE WHEN acs IS NOT NULL THEN rp END), 0),
               SUM(kills) * 1.0 / NULLIF(SUM(deaths), 0),
               SUM(adr * rp) / NULLIF(SUM(CASE WHEN adr IS NOT NULL THEN rp END), 0),
               SUM(kast_pct * rp) / NULLIF(SUM(CASE WHEN kast_pct IS NOT NULL THEN rp END), 0),
               json_object('maps', COUNT(*), 'window', CASE WHEN MAX(recent) THEN '365d' ELSE 'all' END)
        FROM sel GROUP BY player_id, agent_id""", (since,))
        rows = self.x("""SELECT pas.player_id, a.role, SUM(pas.usage) FROM player_agent_stats pas
                         JOIN agents a USING(agent_id) GROUP BY 1, 2 ORDER BY 1, 3 DESC""").fetchall()
        best: dict[int, tuple[str, float]] = {}
        for pid, role, share in rows:
            if pid not in best:
                best[pid] = (role, share)
        self.con.executemany("UPDATE player_profile SET main_role=?, is_flex=? WHERE player_id=?",
                             [(r, int(s < 0.6), pid) for pid, (r, s) in best.items()])
        self.summary["players_with_role"] = len(best)

    # --------------------------------------------------- 5. tables applicatives
    def app_tables(self):
        self.step("tables applicatives et index")
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS compositions (
            composition_id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner_email TEXT,
            created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL, score INTEGER, notes TEXT);
        CREATE TABLE IF NOT EXISTS composition_slots (
            composition_id INTEGER NOT NULL REFERENCES compositions(composition_id) ON DELETE CASCADE,
            slot_index INTEGER NOT NULL CHECK (slot_index BETWEEN 0 AND 4),
            slot_role TEXT NOT NULL CHECK (slot_role IN ('duelist','initiator','controller','sentinel','flex')),
            player_id INTEGER REFERENCES players(player_id), agent_id INTEGER REFERENCES agents(agent_id),
            PRIMARY KEY (composition_id, slot_index), UNIQUE (composition_id, player_id));
        CREATE TABLE IF NOT EXISTS predictions (
            prediction_id INTEGER PRIMARY KEY, created_at TIMESTAMP NOT NULL, match_id INTEGER REFERENCES matches(match_id),
            side_a_team_id INTEGER REFERENCES teams(team_id), side_a_comp_id INTEGER REFERENCES compositions(composition_id),
            side_b_team_id INTEGER REFERENCES teams(team_id), side_b_comp_id INTEGER REFERENCES compositions(composition_id),
            best_of INTEGER NOT NULL CHECK (best_of IN (1,3,5)), p_side_a REAL NOT NULL, predicted_score TEXT,
            model_version TEXT NOT NULL, factors_json TEXT,
            CHECK (side_a_team_id IS NOT NULL OR side_a_comp_id IS NOT NULL),
            CHECK (side_b_team_id IS NOT NULL OR side_b_comp_id IS NOT NULL));
        CREATE TABLE IF NOT EXISTS prediction_maps (
            prediction_id INTEGER NOT NULL REFERENCES predictions(prediction_id) ON DELETE CASCADE,
            step INTEGER NOT NULL, action TEXT NOT NULL CHECK (action IN ('ban','pick','decider')),
            side TEXT CHECK (side IN ('a','b')), map_id INTEGER NOT NULL REFERENCES game_maps(map_id), p_side_a REAL,
            PRIMARY KEY (prediction_id, step));
        CREATE INDEX IF NOT EXISTS idx_matches_status_date ON matches(status, match_date);
        CREATE INDEX IF NOT EXISTS idx_pma_player ON player_match_advanced(player_id);
        CREATE INDEX IF NOT EXISTS idx_pss_ts ON player_stats_snapshot(timespan_days, rating);
        CREATE INDEX IF NOT EXISTS idx_pp_status ON player_profile(status);
        CREATE INDEX IF NOT EXISTS idx_tp_region ON team_profile(region, elo);
        CREATE INDEX IF NOT EXISTS idx_players_team ON players(current_team_id);
        CREATE INDEX IF NOT EXISTS idx_vetos_map ON match_map_vetos(map_id);
        """)


def build(raw: Path, out: Path, kaggle: Path | None) -> dict:
    t0 = time.time()
    tmp = out.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    print(f"copie {raw} -> {tmp}")
    shutil.copyfile(raw, tmp)
    con = sqlite3.connect(tmp)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA foreign_keys=OFF")
    b = Builder(con)
    try:
        b.clean_maps()
        b.clean_map_scores()
        b.remap_foreign_team("player_map_stats", "team_id", ("match_map_id", "player_id"))
        b.remap_foreign_team("rounds", "winner_team_id", ("match_map_id", "round_number"))
        b.remap_foreign_team("player_match_advanced", "team_id", ("match_id", "player_id"), mm_col="match_id")
        b.clean_matches()
        b.clean_events()
        b.load_agents(kaggle)
        b.derived()
        b.app_tables()
        con.commit()
        bad_fk = con.execute("SELECT COUNT(*) FROM pragma_foreign_key_check").fetchone()[0]
        b.summary["foreign_key_violations"] = bad_fk
        b.step("ANALYZE + VACUUM")
        con.execute("ANALYZE")
        con.execute("VACUUM")
    finally:
        con.close()
    out.unlink(missing_ok=True)
    tmp.rename(out)
    b.summary["duration_s"] = round(time.time() - t0)
    (out.parent / "valopti_build_summary.json").write_text(json.dumps(b.summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(b.summary, indent=2, ensure_ascii=False))
    return b.summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=DATA / "valorant.db")
    ap.add_argument("--out", type=Path, default=DATA / "valopti.db")
    ap.add_argument("--kaggle", type=Path, default=DATA / "data_temp.zip")
    a = ap.parse_args()
    build(a.raw, a.out, a.kaggle)


if __name__ == "__main__":
    main()
