from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..cache import CACHE, DEFAULT_PERIOD, STATS
from ..db import get_db
from ..model import attach_maps, mean, player_agent_pool, player_form, player_map_ratings, player_summary, team_map_record, team_roster

router = APIRouter(tags=["joueurs et équipes"])

SORTABLE = set(STATS) | {"ign", "rounds_played"}
LIST_FIELDS = ("player_id", "ign", "real_name", "country_code", "region", "status", "role", "main_role", "team_id",
               "team_name", "team_tag", "tier", "circuit", "last_team_id", "last_team_name", "agents", "rounds_played",
               "maps_played", "rookie", "is_free_agent", *STATS)


def _filter(rows, q, region, role, status, tier, min_rounds):
    q = (q or "").strip().lower()
    for r in rows:
        if region and r["region"] != region:
            continue
        if role and not (r["role"] == role or (role != "flex" and r["main_role"] == role)):
            continue
        if status == "free_agent" and not r["is_free_agent"]:
            continue
        if status == "contracted" and not r["team_id"]:
            continue
        if status == "rookie" and not r["rookie"]:
            continue
        if tier and r["circuit"] != tier:
            continue
        if (r["rounds_played"] or 0) < min_rounds:
            continue
        if q and q not in r["ign"].lower() and q not in (r["real_name"] or "").lower() \
                and q not in (r["team_name"] or "").lower():
            continue
        yield r


@router.get("/players")
def list_players(
    period: int = Query(DEFAULT_PERIOD), q: str | None = None, region: str | None = None,
    role: str | None = Query(None, pattern="^(duelist|initiator|controller|sentinel|flex)$"),
    status: str | None = Query(None, pattern="^(free_agent|contracted|rookie)$"),
    tier: str | None = None, min_rounds: int = Query(0, ge=0),
    sort: str = "rating", dir: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
):
    P = CACHE.period(period)
    if sort not in SORTABLE:
        raise HTTPException(422, f"tri inconnu : {sort}")
    items = list(_filter(P.rows, q, region, role, status, tier, min_rounds))
    rev = dir == "desc"
    if sort == "ign":
        items.sort(key=lambda r: r["ign"].lower(), reverse=rev)
    else:
        items.sort(key=lambda r: (r[sort] is None, -(r[sort] or 0) if rev else (r[sort] or 0)))
    page = items[offset: offset + limit]
    return {
        "total": len(items), "period": period if period in CACHE.periods else DEFAULT_PERIOD,
        "items": [{**{k: r[k] for k in LIST_FIELDS},
                   "pct": {k: P.pct(k, r[k]) for k in STATS}} for r in page],
    }


@router.get("/players/{player_id}")
def get_player(player_id: int, period: int = Query(DEFAULT_PERIOD), con: sqlite3.Connection = Depends(get_db)):
    base = con.execute("""SELECT p.player_id, p.ign, p.real_name, p.country_code, p.total_winnings_usd, p.vlr_player_id,
                                 pp.region, pp.status, pp.first_seen, pp.last_seen, pp.maps_total, pp.rounds_total,
                                 pp.main_role, pp.is_flex, pp.last_team_id, lt.name AS last_team_name,
                                 p.current_team_id AS team_id, t.name AS team_name, t.short_tag AS team_tag
                          FROM players p LEFT JOIN player_profile pp USING(player_id)
                          LEFT JOIN teams t ON t.team_id = p.current_team_id LEFT JOIN teams lt ON lt.team_id = pp.last_team_id
                          WHERE p.player_id = ?""", (player_id,)).fetchone()
    if not base:
        raise HTTPException(404, "joueur introuvable")
    P = CACHE.period(period)
    snap = P.by_id.get(player_id)
    role = base["main_role"]
    stats = None
    if snap:
        stats = {k: snap[k] for k in (*STATS, "rounds_played", "maps_played")}
        stats["pct_role"] = {k: P.pct(k, snap[k], role) for k in STATS}
        stats["pct_all"] = {k: P.pct(k, snap[k]) for k in STATS}
    form = player_form(con, player_id, 10)
    maps = player_map_ratings(con, player_id)
    names = {m["map_id"]: m["name"] for m in CACHE.map_pool}
    career = con.execute("""
        SELECT t.team_id, t.name AS team_name, MIN(ptm.first_seen_date) AS first_seen, MAX(ptm.last_seen_date) AS last_seen
        FROM player_team_membership ptm JOIN teams t ON t.team_id = ptm.team_id
        WHERE ptm.player_id = ? GROUP BY t.team_id, t.name ORDER BY last_seen DESC LIMIT 12""", (player_id,)).fetchall()
    for c in career:
        c["is_current"] = c["team_id"] == base["team_id"]
    return {
        **base, "role": "flex" if base["is_flex"] else role, "period": period, "stats": stats,
        "rookie": (snap or {}).get("rounds_played", 0) < 650,
        "is_free_agent": base["status"] == "free_agent",
        "agents": player_agent_pool(con, player_id),
        "form": list(reversed(form)),
        "maps": sorted(({"map_id": mid, "name": names[mid], **{k: r[k] for k in ("maps", "rating", "acs", "won")}}
                        for mid, r in maps.items() if mid in names), key=lambda x: -(x["rating"] or 0)),
        "career": career,
    }


@router.get("/teams/{team_id}")
def get_team(team_id: int, con: sqlite3.Connection = Depends(get_db)):
    t = con.execute("""SELECT t.team_id, t.name, t.short_tag, t.country_code, t.logo_url, tp.*
                       FROM teams t LEFT JOIN team_profile tp USING(team_id) WHERE t.team_id = ?""", (team_id,)).fetchone()
    if not t:
        raise HTTPException(404, "équipe introuvable")
    ranked = CACHE.teams.get(team_id, {})
    roster = []
    for pid in team_roster(con, team_id):
        s = player_summary(con, pid)
        f = [x["rating"] for x in player_form(con, pid, 5)]
        roster.append({k: s.get(k) for k in ("player_id", "ign", "country_code", "role", "rating", "acs", "kast_pct",
                                              "rounds_played", "is_free_agent")} | {"form5": mean(f) if f else None})
    rec = team_map_record(con, team_id)
    matches = con.execute("""
        SELECT m.match_id, m.match_date, m.team1_id, m.team2_id, m.team1_score, m.team2_score, m.winner_team_id,
               t1.name AS team1, t2.name AS team2, COALESCE(e.name, m.event_label) AS event
        FROM matches m LEFT JOIN teams t1 ON t1.team_id = m.team1_id LEFT JOIN teams t2 ON t2.team_id = m.team2_id
        LEFT JOIN events e ON e.event_id = m.event_id
        WHERE m.status = 'final' AND m.is_forfeit = 0 AND (m.team1_id = ? OR m.team2_id = ?)
        ORDER BY m.match_date DESC, m.match_id DESC LIMIT 8""", (team_id, team_id)).fetchall()
    attach_maps(con, matches)
    vlr = con.execute("""SELECT region, rank, rating, wins, losses FROM team_rankings WHERE team_id = ?
                         ORDER BY snapshot_date DESC LIMIT 1""", (team_id,)).fetchone()
    return {
        **t, "world_rank": ranked.get("world_rank"), "region_rank": ranked.get("region_rank"),
        "ranked": bool(ranked), "roster": roster, "vlr_ranking": vlr,
        "maps": [{"map_id": m["map_id"], "name": m["name"], **rec.get(m["map_id"], {"played": 0, "won": 0})}
                 for m in CACHE.map_pool],
        "matches": matches,
    }
