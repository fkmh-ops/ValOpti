"""Modèles explicables : profil d'équipe, prédiction de série (veto + Markov), note de composition.

Δ_map = w_elo × (Elo_A − Elo_B) + w_map × (Elo carte_A − Elo carte_B) + w_form × (forme_A − forme_B)
p_map = 1 / (1 + 10^(−Δ/400))
Les poids sont appris par backtest (etl/backtest.py) et lus dans la table meta.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field

from .cache import CACHE, DEFAULT_PERIOD, ROOKIE_ROUNDS

SLOT_ROLES = ("duelist", "initiator", "controller", "sentinel", "flex")
MAP_WR_DAYS = 365
VETO_SEQ = {
    1: ["A ban", "B ban", "A ban", "B ban", "A ban", "B ban"],
    3: ["A ban", "B ban", "A pick", "B pick", "A ban", "B ban"],
    5: ["A ban", "B ban", "A pick", "B pick", "A pick", "B pick"],
}


def elo_p(d: float) -> float:
    return 1 / (1 + 10 ** (-d / 400))


def mean(xs) -> float:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def clamp(v, a, b):
    return max(a, min(b, v))


@dataclass
class Side:
    key: str
    name: str
    tag: str
    elo: float
    elo_label: str
    wr: dict[int, float]                 # map_id -> winrate lissé 12 mois (affichage)
    map_off: dict[int, float]            # map_id -> Elo propre à la carte (écart au niveau global)
    form: float
    players: list[dict] = field(default_factory=list)   # {player, agent_id}
    team: dict | None = None
    composition: bool = False
    detail: dict = field(default_factory=dict)


# ----------------------------------------------------------------- équipes
def team_roster(con: sqlite3.Connection, team_id: int) -> list[int]:
    """Roster actuel ; à défaut, les 5 joueurs de la dernière map jouée."""
    ids = [r["player_id"] for r in con.execute(
        "SELECT player_id FROM players WHERE current_team_id = ?", (team_id,))]
    if len(ids) >= 5:
        p = CACHE.period(365)
        ids.sort(key=lambda i: -(p.by_id.get(i, {}).get("rounds_played") or 0))
        return ids[:5] if len(ids) > 5 else ids
    last = con.execute("""SELECT s.player_id FROM player_map_stats s JOIN match_maps mm USING(match_map_id)
                          JOIN matches m USING(match_id) WHERE s.team_id = ?
                          ORDER BY m.match_date DESC, mm.match_map_id DESC LIMIT 5""", (team_id,)).fetchall()
    return [r["player_id"] for r in last]


def team_map_record(con: sqlite3.Connection, team_id: int, days: int = MAP_WR_DAYS) -> dict[int, dict]:
    rows = con.execute("""
        SELECT mm.map_id, COUNT(*) AS played, SUM(mm.winner_team_id = ?) AS won
        FROM match_maps mm JOIN matches m USING(match_id)
        WHERE m.match_id IN (SELECT match_id FROM matches WHERE team1_id = ? UNION ALL
                             SELECT match_id FROM matches WHERE team2_id = ?)
          AND m.match_date > ? AND mm.map_id IS NOT NULL AND mm.winner_team_id IS NOT NULL
        GROUP BY mm.map_id""", (team_id, team_id, team_id, CACHE.since(days))).fetchall()
    return {r["map_id"]: {"played": r["played"], "won": r["won"]} for r in rows}


def player_form(con: sqlite3.Connection, player_id: int, n: int = 10) -> list[dict]:
    return con.execute("""
        SELECT m.match_date, gm.name AS map_name, s.rating, s.acs, s.agent_id, m.match_id
        FROM player_map_stats s JOIN match_maps mm USING(match_map_id) JOIN matches m USING(match_id)
        LEFT JOIN game_maps gm ON gm.map_id = mm.map_id
        WHERE s.player_id = ? AND s.rating IS NOT NULL
        ORDER BY m.match_date DESC, mm.map_number DESC LIMIT ?""", (player_id, n)).fetchall()


def player_map_ratings(con: sqlite3.Connection, player_id: int, days: int = MAP_WR_DAYS) -> dict[int, dict]:
    rows = con.execute("""
        SELECT mm.map_id, COUNT(*) AS maps, SUM(s.rating * mm.rounds_played) / SUM(mm.rounds_played) AS rating,
               AVG(s.acs) AS acs, SUM(mm.winner_team_id = s.team_id) AS won
        FROM player_map_stats s JOIN match_maps mm USING(match_map_id) JOIN matches m USING(match_id)
        WHERE s.player_id = ? AND s.rating IS NOT NULL AND mm.map_id IS NOT NULL AND m.match_date > ?
        GROUP BY mm.map_id""", (player_id, CACHE.since(days))).fetchall()
    return {r["map_id"]: r for r in rows}


def player_agent_pool(con: sqlite3.Connection, player_id: int) -> list[dict]:
    return con.execute("""SELECT pas.agent_id, a.name, a.role, pas.usage, pas.rounds, pas.rating, pas.acs, pas.kd,
                                 pas.adr, pas.kast_pct, json_extract(pas.extra_json, '$.maps') AS maps
                          FROM player_agent_stats pas JOIN agents a USING(agent_id)
                          WHERE pas.player_id = ? ORDER BY pas.usage DESC""", (player_id,)).fetchall()


def player_summary(con: sqlite3.Connection, player_id: int, period: int = DEFAULT_PERIOD) -> dict:
    """Ligne snapshot si le joueur a joué sur la période, sinon fiche minimale."""
    r = CACHE.period(period).by_id.get(player_id) or CACHE.period(365).by_id.get(player_id)
    if r:
        return r
    p = con.execute("""SELECT p.player_id, p.ign, p.real_name, p.country_code, pp.region, pp.status, pp.main_role,
                              pp.is_flex, p.current_team_id AS team_id, t.name AS team_name, t.short_tag AS team_tag
                       FROM players p LEFT JOIN player_profile pp USING(player_id) LEFT JOIN teams t ON t.team_id = p.current_team_id
                       WHERE p.player_id = ?""", (player_id,)).fetchone()
    if not p:
        return {}
    p.update(role="flex" if p.get("is_flex") else p.get("main_role"), rating=None, acs=None, kast_pct=None,
             rounds_played=0, agents=[], rookie=True, is_free_agent=p.get("status") == "free_agent")
    return p


def default_agent(con: sqlite3.Connection, player_id: int, role: str | None, taken: list[int]) -> int | None:
    pool = [a for a in player_agent_pool(con, player_id) if a["agent_id"] not in taken]
    for a in pool:
        if role and role != "flex" and a["role"] == role:
            return a["agent_id"]
    return pool[0]["agent_id"] if pool else None


def team_side(con: sqlite3.Connection, team_id: int) -> Side | None:
    t = con.execute("""SELECT t.team_id, t.name, t.short_tag, t.country_code, tp.region, tp.tier, tp.elo
                       FROM teams t LEFT JOIN team_profile tp USING(team_id) WHERE t.team_id = ?""", (team_id,)).fetchone()
    if not t:
        return None
    rec = team_map_record(con, team_id)
    wr = {m["map_id"]: (rec.get(m["map_id"], {}).get("won", 0) + 2) / (rec.get(m["map_id"], {}).get("played", 0) + 4)
          for m in CACHE.map_pool}
    offs = {r["map_id"]: r["offset"] for r in con.execute("SELECT map_id, offset FROM team_map_elo WHERE team_id = ?", (team_id,))}
    map_off = {m["map_id"]: offs.get(m["map_id"], 0.0) for m in CACHE.map_pool}
    roster = team_roster(con, team_id)
    forms = []
    players = []
    taken: list[int] = []
    for pid in roster:
        f = [x["rating"] for x in player_form(con, pid, 5)]
        if f:
            forms.append(mean(f))
        ag = default_agent(con, pid, None, taken)
        if ag:
            taken.append(ag)
        players.append({"player": player_summary(con, pid), "agent_id": ag})
    return Side(key=f"team:{team_id}", name=t["name"], tag=t["short_tag"] or t["name"][:4].upper(),
                elo=t["elo"] or 1500, elo_label="Elo ValOpti", wr=wr, map_off=map_off, form=mean(forms) if forms else 1.0,
                players=players, team={**t, **(CACHE.teams.get(team_id) or {})},
                detail={"map_record": rec})


def composition_side(con: sqlite3.Connection, name: str, slots: list[dict], key: str) -> Side | dict:
    filled = [s for s in slots if s.get("player_id")]
    if len(filled) < 5:
        return {"incomplete": True, "name": name}
    an = analyse_draft(con, slots)
    a, b = CACHE.elo_fit
    elo = a + b * (an["avg"] - 1) - (100 - an["parts"]["balance"]) * 1.5
    avg = an["avg"]
    wr, map_off = {}, {}
    for m in CACHE.map_pool:
        vals = [an["player_maps"][s["player_id"]].get(m["map_id"], avg) for s in filled]
        wr[m["map_id"]] = clamp(0.5 + (mean(vals) - avg) * 3, 0.25, 0.75)
        map_off[m["map_id"]] = wr_to_offset(wr[m["map_id"]])
    forms = [mean([x["rating"] for x in player_form(con, s["player_id"], 5)]) for s in filled]
    return Side(key=key, name=name or "Composition en cours", tag="CMP", elo=round(elo), elo_label="Elo estimé",
                wr=wr, map_off=map_off, form=mean(forms) or 1.0, composition=True,
                players=[{"player": player_summary(con, s["player_id"]), "agent_id": s.get("agent_id")} for s in filled],
                detail={"score": an["score"]})


# -------------------------------------------------------------- prédiction
def wr_to_offset(wr: float) -> float:
    """Winrate relatif sur une carte -> écart en points Elo (composition sans historique d'équipe)."""
    return 400 * math.log10(wr / (1 - wr))


def map_pred(A: Side, B: Side, map_id: int) -> dict:
    w = CACHE.weights
    e = w.get("d_elo", 0) * (A.elo - B.elo)
    mp = w.get("d_map", 0) * (A.map_off[map_id] - B.map_off[map_id]) + w.get("d_wr", 0) * (A.wr[map_id] - B.wr[map_id])
    f = w.get("d_form", 0) * (A.form - B.form)
    return {"p": elo_p(e + mp + f), "e": e, "mp": mp, "f": f}


def simulate_veto(p_a: dict[int, float], best_of: int) -> dict:
    pool = [m["map_id"] for m in CACHE.map_pool]
    steps, played = [], []
    for s in VETO_SEQ[best_of]:
        who, act = s.split(" ")
        if len(pool) <= 1:
            break
        score = (lambda m: p_a[m]) if who == "A" else (lambda m: 1 - p_a[m])
        best = max(pool, key=score) if act == "pick" else min(pool, key=score)
        pool.remove(best)
        steps.append({"side": who.lower(), "action": act, "map_id": best})
        if act == "pick":
            played.append(best)
    if pool:
        steps.append({"side": None, "action": "decider", "map_id": pool[0]})
        played.append(pool[0])
    return {"steps": steps, "played": played}


def series_pred(A: Side, B: Side, best_of: int) -> dict:
    p_a = {m["map_id"]: map_pred(A, B, m["map_id"])["p"] for m in CACHE.map_pool}
    v = simulate_veto(p_a, best_of)
    need = (best_of + 1) // 2
    states = {(0, 0): 1.0}
    out: dict[tuple, float] = {}
    for mid in v["played"]:
        p = p_a[mid]
        nx: dict[tuple, float] = {}
        for (a, b), val in states.items():
            if a == need or b == need:
                out[(a, b)] = out.get((a, b), 0) + val
                continue
            nx[(a + 1, b)] = nx.get((a + 1, b), 0) + val * p
            nx[(a, b + 1)] = nx.get((a, b + 1), 0) + val * (1 - p)
        states = nx
    for k, val in states.items():
        out[k] = out.get(k, 0) + val
    win = sum(val for (a, _), val in out.items() if a == need)
    parts = [map_pred(A, B, m) for m in v["played"]]
    dist = sorted(({"score": f"{a}-{b}", "a": a, "b": b, "p": val} for (a, b), val in out.items()),
                  key=lambda x: (x["b"] - x["a"]))
    top = max(dist, key=lambda x: x["p"]) if dist else None
    return {
        "p_a": win, "best_of": best_of, "distribution": dist, "likely_score": top["score"] if top else None,
        "veto": [{**s, "p_a": p_a[s["map_id"]] if s["action"] != "ban" else None} for s in v["steps"]],
        "map_probabilities": p_a,
        "factors": {"level": mean(x["e"] for x in parts), "map_pool": mean(x["mp"] for x in parts),
                    "form": mean(x["f"] for x in parts)},
    }


def side_public(s: Side) -> dict:
    return {"key": s.key, "name": s.name, "tag": s.tag, "elo": round(s.elo), "elo_label": s.elo_label,
            "form": s.form, "composition": s.composition, "team": s.team,
            "winrates": {str(k): v for k, v in s.wr.items()},
            "players": [{"player": _slim(p["player"]), "agent_id": p["agent_id"]} for p in s.players]}


def _slim(p: dict) -> dict:
    keys = ("player_id", "ign", "country_code", "role", "rating", "acs", "kast_pct", "team_id", "team_tag", "team_name",
            "is_free_agent", "rookie", "rounds_played", "status")
    return {k: p.get(k) for k in keys}


def h2h(con: sqlite3.Connection, a: int, b: int, n: int = 5) -> list[dict]:
    ms = con.execute("""SELECT m.match_id, m.match_date, m.team1_id, m.team2_id, m.team1_score, m.team2_score,
                               m.winner_team_id, t1.name AS team1, t2.name AS team2, COALESCE(e.name, m.event_label) AS event
                        FROM matches m JOIN teams t1 ON t1.team_id = m.team1_id JOIN teams t2 ON t2.team_id = m.team2_id
                        LEFT JOIN events e ON e.event_id = m.event_id
                        WHERE m.status = 'final' AND m.is_forfeit = 0 AND
                              ((m.team1_id = ? AND m.team2_id = ?) OR (m.team1_id = ? AND m.team2_id = ?))
                        ORDER BY m.match_date DESC LIMIT ?""", (a, b, b, a, n)).fetchall()
    attach_maps(con, ms)
    return ms


def attach_maps(con: sqlite3.Connection, matches: list[dict]) -> None:
    if not matches:
        return
    ids = [m["match_id"] for m in matches]
    q = ",".join("?" * len(ids))
    by: dict[int, list] = {}
    for r in con.execute(f"""SELECT mm.match_id, gm.name AS map, mm.team1_score, mm.team2_score FROM match_maps mm
                             LEFT JOIN game_maps gm ON gm.map_id = mm.map_id WHERE mm.match_id IN ({q})
                             AND mm.team1_score IS NOT NULL ORDER BY mm.match_id, mm.map_number""", ids):
        by.setdefault(r["match_id"], []).append({"map": r["map"] or "?", "s1": r["team1_score"], "s2": r["team2_score"]})
    for m in matches:
        m["maps"] = by.get(m["match_id"], [])


# ------------------------------------------------------- note de composition
def analyse_draft(con: sqlite3.Connection, slots: list[dict], period: int = DEFAULT_PERIOD) -> dict:
    P = CACHE.period(period)
    filled = [dict(s, i=i) for i, s in enumerate(slots) if s.get("player_id")]
    parts = {"firepower": 0.0, "entry": 0.0, "utility": 0.0, "clutch": 0.0, "balance": 100.0}
    alerts: list[dict] = []
    if not filled:
        return {"score": 0, "parts": parts, "alerts": [{"level": "info", "text": "Ajoutez des joueurs depuis la liste pour lancer l'analyse."}],
                "maps": {}, "avg": 0, "player_maps": {}}
    ps = [player_summary(con, s["player_id"], period) for s in filled]

    def pc(stat, p):
        v = P.pct(stat, p.get(stat))
        return 50.0 if v is None else v

    parts["firepower"] = mean((pc("rating", p) + pc("acs", p)) / 2 for p in ps)
    entries = sorted(((pc("fkpr", p) + pc("fdpr", p)) / 2 for p in ps), reverse=True)
    parts["entry"] = mean(entries[:2])
    parts["utility"] = mean((pc("apr", p) + pc("kast_pct", p)) / 2 for p in ps)
    parts["clutch"] = mean(pc("clutch_per100", p) for p in ps)

    agent_roles = [CACHE.agents.get(s.get("agent_id"), {}).get("role") for s in filled]
    bal = 100
    if len(filled) == 5 and None in agent_roles:
        alerts.append({"level": "warn", "text": "Choisissez un agent pour chaque slot pour vérifier l'équilibre des rôles."})
        bal -= 10
    elif len(filled) == 5:
        for role, pen, lvl, txt in (
            ("controller", 35, "crit", "Aucun contrôleur : pas de smokes pour exécuter ou retarder."),
            ("initiator", 20, "warn", "Aucun initiateur : peu d'info et de flashs pour ouvrir les sites."),
            ("sentinel", 20, "warn", "Aucune sentinelle : flanc et retakes fragiles."),
            ("duelist", 15, "warn", "Aucun duelliste : entrées sur site plus lentes."),
        ):
            if role not in agent_roles:
                bal -= pen
                alerts.append({"level": lvl, "text": txt})
    else:
        n = 5 - len(filled)
        alerts.append({"level": "info", "text": f"{n} slot{'s' if n > 1 else ''} vide{'s' if n > 1 else ''} : la note est provisoire."})
    seen: set[int] = set()
    for s in filled:
        a = s.get("agent_id")
        if a and a in seen:
            bal -= 30
            alerts.append({"level": "crit", "text": f"{CACHE.agents[a]['name']} est choisi deux fois."})
        if a:
            seen.add(a)
    no_pool = []
    for s, p in zip(filled, ps):
        pool = [x["agent_id"] for x in player_agent_pool(con, s["player_id"])]
        if not pool:
            no_pool.append(p.get("ign"))
        elif s.get("agent_id") and s["agent_id"] not in pool:
            bal -= 8
            alerts.append({"level": "warn", "text": f"{p.get('ign')} n'a pas joué {CACHE.agents[s['agent_id']]['name']} en match officiel référencé."})
    if no_pool:
        alerts.append({"level": "info", "text": f"Pool d'agents inconnu pour {', '.join(no_pool)} (agents disponibles seulement sur le circuit VCT)."})
    parts["balance"] = clamp(bal, 0, 100)
    for p in ps:
        if (p.get("rounds_played") or 0) < ROOKIE_ROUNDS:
            alerts.append({"level": "info", "text": f"{p.get('ign')} : {p.get('rounds_played') or 0} rounds sur la période, échantillon limité."})
    contracted = [p for p in ps if p.get("team_id")]
    if contracted:
        alerts.append({"level": "info", "text": "Sous contrat : " + ", ".join(
            f"{p['ign']} ({p.get('team_tag') or p.get('team_name')})" for p in contracted) + ". Transfert à négocier."})
    fa = [p for p in ps if p.get("is_free_agent")]
    if fa:
        alerts.append({"level": "ok", "text": f"{len(fa)} joueur{'s' if len(fa) > 1 else ''} sans équipe (probable) : recrutement possible sans indemnité."})
    if len(filled) == 5 and not any(a["level"] in ("crit", "warn") for a in alerts):
        alerts.insert(0, {"level": "ok", "text": "Rôles couverts et agents cohérents avec les pools des joueurs."})

    score = round((parts["firepower"] * 0.35 + parts["entry"] * 0.15 + parts["utility"] * 0.2 + parts["clutch"] * 0.1)
                  * (len(filled) / 5) + parts["balance"] * 0.2)
    rated = [p["rating"] for p in ps if p.get("rating") is not None]
    avg = mean(rated) if rated else 1.0
    pmaps = {}
    for s in filled:
        mr = player_map_ratings(con, s["player_id"])
        base = P.by_id.get(s["player_id"], {}).get("rating") or avg
        # rating par map, rétréci vers le rating global quand l'échantillon est faible
        pmaps[s["player_id"]] = {mid: (r["rating"] * r["maps"] + base * 3) / (r["maps"] + 3) for mid, r in mr.items()}
    maps = {}
    if len(filled) == 5:
        a, b = CACHE.elo_fit
        elo = a + b * (avg - 1) - (100 - parts["balance"]) * 1.5
        for m in CACHE.map_pool:
            wr = clamp(0.5 + (mean(pmaps[s["player_id"]].get(m["map_id"], avg) for s in filled) - avg) * 3, 0.25, 0.75)
            w = CACHE.weights
            maps[str(m["map_id"])] = elo_p(w.get("d_elo", 0) * (elo - CACHE.elo_reference) + w.get("d_map", 0) * wr_to_offset(wr))
    return {"score": score, "parts": parts, "alerts": alerts, "maps": maps, "avg": avg if rated else 0,
            "player_maps": pmaps, "players": [_slim(p) for p in ps]}
