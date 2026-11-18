"""Données de référence chargées une fois au démarrage (la base est en lecture seule hors compositions).

- snapshots joueurs par période (90 / 180 / 365 j) avec profil, équipe et distributions pour les percentiles
- agents, pool de cartes, profils d'équipes actives, calibration Elo <- rating moyen du roster
"""
from __future__ import annotations

import bisect
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta

from .db import connect

PERIODS = (90, 180, 365)
DEFAULT_PERIOD = 180
STATS = ("rating", "acs", "kd", "kast_pct", "adr", "kpr", "apr", "fkpr", "fdpr", "hs_pct", "clutch_per100")
LOWER_BETTER = {"fdpr"}
ROLES = ("duelist", "initiator", "controller", "sentinel")
REGIONS_ORDER = ["EMEA", "Americas", "Pacific", "China"]
PCT_MIN_ROUNDS = 150          # population de référence des percentiles
ROOKIE_ROUNDS = 650
ACTIVE_TEAM_DAYS = 180
GC = "Game Changers"
MAIN_CIRCUITS = ("VCT", "Challengers")


@dataclass
class PeriodData:
    rows: list[dict]
    by_id: dict[int, dict]
    dist: dict[str, list[float]]
    dist_role: dict[str, dict[str, list[float]]]

    def pct(self, stat: str, value: float | None, role: str | None = None) -> float | None:
        if value is None:
            return None
        arr = self.dist_role.get(role, {}).get(stat) if role else None
        if not arr or len(arr) < 20:
            arr = self.dist.get(stat)
        if not arr:
            return None
        p = bisect.bisect_right(arr, value) / len(arr) * 100
        return 100 - p if stat in LOWER_BETTER else p


@dataclass
class Cache:
    snapshot_date: str = ""
    model_version: str = ""
    weights: dict = field(default_factory=dict)        # poids du modèle (points Elo par unité d'écart)
    backtest: dict = field(default_factory=dict)
    map_pool: list[dict] = field(default_factory=list)
    agents: dict[int, dict] = field(default_factory=dict)
    periods: dict[int, PeriodData] = field(default_factory=dict)
    teams: dict[int, dict] = field(default_factory=dict)      # équipes actives (classement)
    elo_fit: tuple[float, float] = (1500.0, 2500.0)            # elo = a + b * (rating_moyen - 1)
    elo_reference: float = 1500.0                              # Elo médian des équipes classées
    counts: dict = field(default_factory=dict)

    def since(self, days: int) -> str:
        return (date.fromisoformat(self.snapshot_date) - timedelta(days=days)).isoformat()

    def period(self, days: int | None) -> PeriodData:
        return self.periods[days if days in self.periods else DEFAULT_PERIOD]


CACHE = Cache()


def _load_period(con: sqlite3.Connection, days: int, agents: dict[int, dict]) -> PeriodData:
    rows = con.execute("""
        SELECT s.player_id, p.ign, p.real_name, p.country_code, pp.region, pp.status, pp.main_role, pp.is_flex,
               pp.last_team_id, lt.name AS last_team_name, lt.short_tag AS last_team_tag, ltp.tier AS last_team_tier,
               p.current_team_id AS team_id, t.name AS team_name, t.short_tag AS team_tag, tp.tier,
               s.agents, s.rounds_played, s.maps_played, s.rating, s.acs, s.kd, s.kast_pct, s.adr, s.kpr, s.apr,
               s.fkpr, s.fdpr, s.hs_pct, s.clutch_per100, pp.last_seen
        FROM player_stats_snapshot s
        JOIN players p USING(player_id)
        LEFT JOIN player_profile pp USING(player_id)
        LEFT JOIN teams t ON t.team_id = p.current_team_id
        LEFT JOIN team_profile tp ON tp.team_id = p.current_team_id
        LEFT JOIN teams lt ON lt.team_id = pp.last_team_id
        LEFT JOIN team_profile ltp ON ltp.team_id = pp.last_team_id
        WHERE s.timespan_days = ? AND s.rating IS NOT NULL""", (days,)).fetchall()
    pool = con.execute("""SELECT player_id, agent_id, usage FROM player_agent_stats ORDER BY player_id, usage DESC""").fetchall()
    pools: dict[int, list[dict]] = {}
    for r in pool:
        pools.setdefault(r["player_id"], []).append({"agent_id": r["agent_id"], "usage": r["usage"]})
    for r in rows:
        r["agents"] = [a["agent_id"] for a in pools.get(r["player_id"], [])[:3]]
        r["role"] = "flex" if r["is_flex"] else r["main_role"]
        r["rookie"] = (r["rounds_played"] or 0) < ROOKIE_ROUNDS
        r["is_free_agent"] = r["status"] == "free_agent"
        r["circuit"] = r["tier"] or r["last_team_tier"]   # circuit de l'équipe actuelle, sinon de la dernière
    ref = [r for r in rows if (r["rounds_played"] or 0) >= PCT_MIN_ROUNDS]
    dist = {k: sorted(r[k] for r in ref if r[k] is not None) for k in STATS}
    dist_role = {ro: {k: sorted(r[k] for r in ref if r[k] is not None and r["main_role"] == ro) for k in STATS}
                 for ro in ROLES}
    return PeriodData(rows=rows, by_id={r["player_id"]: r for r in rows}, dist=dist, dist_role=dist_role)


def load() -> Cache:
    con = connect()
    try:
        meta = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM meta")}
        CACHE.snapshot_date = meta["snapshot_date"]
        CACHE.model_version = meta.get("model_version", "elo-map-form-v1")
        CACHE.weights = json.loads(meta.get("model_weights") or '{"d_elo": 0.6, "d_wr": 300, "d_form": 500}')
        CACHE.backtest = json.loads(meta.get("model_backtest") or "{}")
        CACHE.map_pool = json.loads(meta["map_pool"])
        CACHE.agents = {r["agent_id"]: r for r in con.execute("SELECT agent_id, name, role FROM agents ORDER BY agent_id")}
        CACHE.periods = {d: _load_period(con, d, CACHE.agents) for d in PERIODS}

        active_since = CACHE.since(ACTIVE_TEAM_DAYS)
        teams = con.execute("""
            SELECT t.team_id, t.name, t.short_tag, t.country_code, t.logo_url, tp.region, tp.tier, tp.elo, tp.elo_matches,
                   tp.wins_365, tp.losses_365, tp.last_match_date, tp.streak_type, tp.streak_length, tp.last5
            FROM team_profile tp JOIN teams t USING(team_id)
            WHERE tp.last_match_date >= ? AND tp.elo_matches >= 10 ORDER BY tp.elo DESC""", (active_since,)).fetchall()
        # Game Changers : circuit quasi fermé (Elo non comparable) -> classement séparé
        n_main = n_gc = 0
        reg_rank: dict[str, int] = {}
        for t in teams:
            if t["tier"] == GC:
                n_gc += 1
                t["world_rank"], t["region_rank"] = n_gc, None
                continue
            n_main += 1
            t["world_rank"] = n_main
            if t["region"]:
                reg_rank[t["region"]] = reg_rank.get(t["region"], 0) + 1
                t["region_rank"] = reg_rank[t["region"]]
            else:
                t["region_rank"] = None
        CACHE.teams = {t["team_id"]: t for t in teams}
        elos = sorted(t["elo"] for t in teams if t["tier"] != GC)
        CACHE.elo_reference = float(elos[len(elos) // 2]) if elos else 1500.0

        # Calibration : Elo d'équipe ~ rating moyen de son roster actuel (sert à noter une composition)
        p = CACHE.period(DEFAULT_PERIOD)
        pts = []
        for t in teams:
            if t["tier"] == GC:
                continue
            rs = [r["rating"] for r in p.rows if r["team_id"] == t["team_id"] and (r["rounds_played"] or 0) >= PCT_MIN_ROUNDS]
            if len(rs) >= 4:
                pts.append((sum(rs) / len(rs) - 1, t["elo"]))
        if len(pts) >= 20:
            mx = sum(x for x, _ in pts) / len(pts)
            my = sum(y for _, y in pts) / len(pts)
            vx = sum((x - mx) ** 2 for x, _ in pts)
            b = sum((x - mx) * (y - my) for x, y in pts) / vx if vx else 2500.0
            CACHE.elo_fit = (my - b * mx, b)

        CACHE.counts = {
            "players_tracked": len(p.rows),
            "free_agents": sum(r["is_free_agent"] for r in p.rows),
            "teams_active": len(teams),
            "maps_analysed": con.execute("""SELECT COUNT(*) AS n FROM match_maps mm JOIN matches m USING(match_id)
                                            WHERE m.match_date > ? AND mm.team1_score IS NOT NULL""",
                                         (CACHE.since(DEFAULT_PERIOD),)).fetchone()["n"],
        }
    finally:
        con.close()
    return CACHE
