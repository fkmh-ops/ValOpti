from __future__ import annotations

import sqlite3
import unicodedata

from fastapi import APIRouter, Depends, Query

from ..cache import CACHE, DEFAULT_PERIOD, GC, MAIN_CIRCUITS, PERIODS, REGIONS_ORDER
from ..db import get_db
from ..model import attach_maps, series_pred, team_side

router = APIRouter(tags=["catalogue"])


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()


@router.get("/meta")
def meta():
    return {
        "snapshot_date": CACHE.snapshot_date,
        "model_version": CACHE.model_version,
        "model_weights": CACHE.weights,
        "model_backtest": CACHE.backtest,
        "map_pool": CACHE.map_pool,
        "agents": list(CACHE.agents.values()),
        "regions": REGIONS_ORDER,
        "periods": PERIODS,
        "default_period": DEFAULT_PERIOD,
        "counts": CACHE.counts,
        "elo_reference": CACHE.elo_reference,
    }


@router.get("/home")
def home(con: sqlite3.Connection = Depends(get_db)):
    ups = con.execute("""
        SELECT m.match_id, m.scheduled_at, m.status, COALESCE(e.name, m.event_label) AS event, m.stage,
               m.team1_id, t1.name AS team1, t1.short_tag AS tag1, m.team2_id, t2.name AS team2, t2.short_tag AS tag2
        FROM matches m LEFT JOIN events e ON e.event_id = m.event_id
        JOIN teams t1 ON t1.team_id = m.team1_id JOIN teams t2 ON t2.team_id = m.team2_id
        WHERE m.status IN ('upcoming', 'live') ORDER BY m.scheduled_at LIMIT 6""").fetchall()
    for u in ups:
        A, B = team_side(con, u["team1_id"]), team_side(con, u["team2_id"])
        u["p_team1"] = series_pred(A, B, 3)["p_a"] if A and B else None

    active = tuple(CACHE.teams)
    recent = []
    if active:
        recent = con.execute(f"""
            SELECT m.match_id, m.match_date, COALESCE(e.name, m.event_label) AS event, m.stage,
                   m.team1_id, t1.name AS team1, m.team1_score, m.team2_score, m.team2_id, t2.name AS team2, m.winner_team_id
            FROM matches m LEFT JOIN events e ON e.event_id = m.event_id
            JOIN teams t1 ON t1.team_id = m.team1_id JOIN teams t2 ON t2.team_id = m.team2_id
            WHERE m.status = 'final' AND m.is_forfeit = 0 AND m.match_date >= ?
              AND m.team1_id IN (SELECT team_id FROM team_profile WHERE tier = 'VCT')
              AND m.team2_id IN (SELECT team_id FROM team_profile WHERE tier = 'VCT')
            ORDER BY m.match_date DESC, m.match_id DESC LIMIT 7""", (CACHE.since(120),)).fetchall()
        attach_maps(con, recent)
    P = CACHE.period(DEFAULT_PERIOD)
    eligible = sorted((r for r in P.rows if (r["rounds_played"] or 0) >= 300 and r["circuit"] in MAIN_CIRCUITS),
                      key=lambda r: -r["rating"])
    slim = ("player_id", "ign", "country_code", "role", "rating", "acs", "team_tag", "team_name", "is_free_agent",
            "rookie", "last_team_name", "rounds_played")
    return {
        "upcoming": ups,
        "recent": recent,
        "top_teams": [t for t in CACHE.teams.values() if t["tier"] != GC][:6],
        "free_agents": [{k: r[k] for k in slim} for r in eligible if r["is_free_agent"]][:5],
        "top_players": [{k: r[k] for k in slim} for r in eligible][:5],
        "counts": CACHE.counts,
        "snapshot_date": CACHE.snapshot_date,
    }


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=60), kind: str | None = Query(None, pattern="^(team|player)$"),
           limit: int = Query(8, ge=1, le=30), con: sqlite3.Connection = Depends(get_db)):
    n = norm(q)
    out: list[dict] = []
    if kind in (None, "team"):
        act = [t for t in CACHE.teams.values() if n in norm(t["name"]) or (t["short_tag"] and norm(t["short_tag"]) == n)]
        act.sort(key=lambda t: (not norm(t["name"]).startswith(n), -t["elo"]))
        out += [{"kind": "team", "id": t["team_id"], "label": t["name"], "sub": f"{t['region'] or '—'} · Elo {t['elo']}",
                 "country_code": t["country_code"], "active": True} for t in act[:limit]]
        if len(out) < limit:
            seen = {o["id"] for o in out}
            more = con.execute("""SELECT t.team_id, t.name, t.country_code, tp.last_match_date FROM teams t
                                  LEFT JOIN team_profile tp USING(team_id) WHERE t.name_norm LIKE ?
                                  ORDER BY tp.last_match_date DESC LIMIT ?""", (f"%{n}%", limit)).fetchall()
            out += [{"kind": "team", "id": t["team_id"], "label": t["name"],
                     "sub": f"inactive · dernier match {t['last_match_date'] or '—'}", "country_code": t["country_code"],
                     "active": False} for t in more if t["team_id"] not in seen][: limit - len(out)]
    if kind in (None, "player"):
        P = CACHE.period(365)
        ps = [r for r in P.rows if n in norm(r["ign"])]
        ps.sort(key=lambda r: (norm(r["ign"]) != n, not norm(r["ign"]).startswith(n), -(r["rounds_played"] or 0)))
        out += [{"kind": "player", "id": r["player_id"], "label": r["ign"],
                 "sub": r["team_tag"] or r["team_name"] or ("Sans équipe" if r["is_free_agent"] else "—"),
                 "country_code": r["country_code"], "active": True} for r in ps[:limit]]
    if kind is None:
        teams = [o for o in out if o["kind"] == "team"][:4]
        players = [o for o in out if o["kind"] == "player"]
        out = (teams + players)[:limit]
    return out[:limit]


@router.get("/rankings")
def rankings(region: str = Query("all", description="all, EMEA, Americas, Pacific, China ou gc (Game Changers)"), limit: int = Query(100, ge=1, le=500), con: sqlite3.Connection = Depends(get_db)):
    if region == "gc":
        ts = [t for t in CACHE.teams.values() if t["tier"] == GC][:limit]
    else:
        ts = [t for t in CACHE.teams.values() if t["tier"] != GC and region in ("all", t["region"])][:limit]
    ids = [t["team_id"] for t in ts]
    best: dict[int, dict] = {}
    if ids:
        q = ",".join("?" * len(ids))
        rec: dict[tuple, list[int]] = {}
        for r in con.execute(f"""
                SELECT m.team1_id, m.team2_id, mm.map_id, mm.winner_team_id FROM match_maps mm JOIN matches m USING(match_id)
                WHERE m.match_date > ? AND mm.map_id IS NOT NULL AND mm.winner_team_id IS NOT NULL
                  AND (m.team1_id IN ({q}) OR m.team2_id IN ({q}))""", (CACHE.since(365), *ids, *ids)):
            for tid in (r["team1_id"], r["team2_id"]):
                x = rec.setdefault((tid, r["map_id"]), [0, 0])
                x[0] += 1
                x[1] += r["winner_team_id"] == tid
        names = {m["map_id"]: m["name"] for m in CACHE.map_pool}
        for (tid, mid), (pl, won) in rec.items():
            if mid in names and pl >= 3:
                wr = won / pl
                if tid not in best or wr > best[tid]["winrate"]:
                    best[tid] = {"map": names[mid], "winrate": wr, "played": pl}
        vlr = {r["team_id"]: r for r in con.execute(f"""SELECT team_id, region, rank, rating FROM team_rankings
                    WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM team_rankings) AND team_id IN ({q})""", ids)}
    else:
        vlr = {}
    return [{**t, "best_map": best.get(t["team_id"]), "vlr_ranking": vlr.get(t["team_id"])} for t in ts]

