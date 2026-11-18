from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response

from ..cache import CACHE
from ..db import get_db
from ..model import SLOT_ROLES, Side, analyse_draft, composition_side, h2h, series_pred, side_public, team_side
from ..schemas import CompositionIn, DraftIn, PredictIn, SideIn

router = APIRouter(tags=["draft et prédictions"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _check_slots(con: sqlite3.Connection, slots) -> None:
    pids = [s.player_id for s in slots if s.player_id]
    if pids:
        q = ",".join("?" * len(pids))
        found = {r["player_id"] for r in con.execute(f"SELECT player_id FROM players WHERE player_id IN ({q})", pids)}
        missing = set(pids) - found
        if missing:
            raise HTTPException(422, f"joueur(s) inconnu(s) : {sorted(missing)}")
    for s in slots:
        if s.agent_id and s.agent_id not in CACHE.agents:
            raise HTTPException(422, f"agent inconnu : {s.agent_id}")


@router.post("/draft/analyse")
def draft_analyse(body: DraftIn, con: sqlite3.Connection = Depends(get_db)):
    _check_slots(con, body.slots)
    res = analyse_draft(con, [s.model_dump() for s in body.slots], body.period)
    res.pop("player_maps", None)
    return res


# ---------------------------------------------------------------- compositions
def _load_comp(con: sqlite3.Connection, cid: int) -> dict:
    c = con.execute("SELECT * FROM compositions WHERE composition_id = ?", (cid,)).fetchone()
    if not c:
        raise HTTPException(404, "composition introuvable")
    slots = [{"player_id": None, "agent_id": None} for _ in SLOT_ROLES]
    for s in con.execute("SELECT slot_index, player_id, agent_id FROM composition_slots WHERE composition_id = ?", (cid,)):
        slots[s["slot_index"]] = {"player_id": s["player_id"], "agent_id": s["agent_id"]}
    c["slots"] = slots
    return c


def _with_names(con: sqlite3.Connection, comps: list[dict]) -> list[dict]:
    ids = {s["player_id"] for c in comps for s in c["slots"] if s["player_id"]}
    names = {}
    if ids:
        q = ",".join("?" * len(ids))
        names = {r["player_id"]: r["ign"] for r in con.execute(f"SELECT player_id, ign FROM players WHERE player_id IN ({q})", list(ids))}
    for c in comps:
        for s in c["slots"]:
            s["ign"] = names.get(s["player_id"])
    return comps


@router.get("/compositions")
def list_compositions(con: sqlite3.Connection = Depends(get_db)):
    ids = [r["composition_id"] for r in con.execute("SELECT composition_id FROM compositions ORDER BY updated_at DESC")]
    return _with_names(con, [_load_comp(con, i) for i in ids])


def _write_slots(con: sqlite3.Connection, cid: int, body: CompositionIn) -> None:
    con.execute("DELETE FROM composition_slots WHERE composition_id = ?", (cid,))
    con.executemany("INSERT INTO composition_slots VALUES (?,?,?,?,?)",
                    [(cid, i, SLOT_ROLES[i], s.player_id, s.agent_id) for i, s in enumerate(body.slots)])


@router.post("/compositions", status_code=201)
def create_composition(body: CompositionIn, con: sqlite3.Connection = Depends(get_db)):
    _check_slots(con, body.slots)
    score = analyse_draft(con, [s.model_dump() for s in body.slots])["score"]
    now = _now()
    with con:
        # même nom = mise à jour (comportement de la maquette)
        ex = con.execute("SELECT composition_id FROM compositions WHERE name = ?", (body.name,)).fetchone()
        if ex:
            cid = ex["composition_id"]
            con.execute("UPDATE compositions SET updated_at=?, score=?, notes=? WHERE composition_id=?", (now, score, body.notes, cid))
        else:
            cid = con.execute("INSERT INTO compositions(name, created_at, updated_at, score, notes) VALUES (?,?,?,?,?)",
                              (body.name, now, now, score, body.notes)).lastrowid
        _write_slots(con, cid, body)
    return {**_with_names(con, [_load_comp(con, cid)])[0], "updated": bool(ex)}


@router.put("/compositions/{cid}")
def update_composition(cid: int, body: CompositionIn, con: sqlite3.Connection = Depends(get_db)):
    _load_comp(con, cid)
    _check_slots(con, body.slots)
    score = analyse_draft(con, [s.model_dump() for s in body.slots])["score"]
    with con:
        con.execute("UPDATE compositions SET name=?, updated_at=?, score=?, notes=? WHERE composition_id=?",
                    (body.name, _now(), score, body.notes, cid))
        _write_slots(con, cid, body)
    return _with_names(con, [_load_comp(con, cid)])[0]


@router.delete("/compositions/{cid}", status_code=204)
def delete_composition(cid: int, con: sqlite3.Connection = Depends(get_db)):
    _load_comp(con, cid)
    with con:
        con.execute("UPDATE predictions SET side_a_comp_id = NULL WHERE side_a_comp_id = ?", (cid,))
        con.execute("UPDATE predictions SET side_b_comp_id = NULL WHERE side_b_comp_id = ?", (cid,))
        con.execute("DELETE FROM compositions WHERE composition_id = ?", (cid,))
    return Response(status_code=204)


# ----------------------------------------------------------------- prédictions
def _side(con: sqlite3.Connection, s: SideIn) -> Side | dict:
    if s.kind == "team":
        if not s.team_id:
            raise HTTPException(422, "team_id requis")
        side = team_side(con, s.team_id)
        if not side:
            raise HTTPException(404, f"équipe {s.team_id} introuvable")
        return side
    if s.kind == "composition":
        c = _load_comp(con, s.composition_id or 0)
        return composition_side(con, c["name"], c["slots"], f"composition:{c['composition_id']}")
    if not s.slots or len(s.slots) != 5:
        raise HTTPException(422, "5 slots requis pour la composition en cours")
    _check_slots(con, s.slots)
    return composition_side(con, s.name or "Composition en cours", [x.model_dump() for x in s.slots], "draft")


@router.post("/predict")
def predict(body: PredictIn, con: sqlite3.Connection = Depends(get_db)):
    A, B = _side(con, body.a), _side(con, body.b)
    for x in (A, B):
        if isinstance(x, dict):
            raise HTTPException(422, f"La composition « {x['name']} » n'a pas 5 joueurs.")
    if A.key == B.key:
        raise HTTPException(422, "Choisissez deux équipes différentes.")
    res = series_pred(A, B, body.best_of)
    res["a"], res["b"] = side_public(A), side_public(B)
    res["h2h"] = h2h(con, A.team["team_id"], B.team["team_id"]) if A.team and B.team else []
    res["model_version"] = CACHE.model_version
    res["weights"] = CACHE.weights
    if body.save:
        if "draft" in (body.a.kind, body.b.kind):
            raise HTTPException(422, "Sauvegardez la composition avant de journaliser la prédiction.")
        with con:
            pid = con.execute("""INSERT INTO predictions(created_at, side_a_team_id, side_a_comp_id, side_b_team_id, side_b_comp_id,
                                 best_of, p_side_a, predicted_score, model_version, factors_json) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                              (_now(), body.a.team_id if body.a.kind == "team" else None,
                               body.a.composition_id if body.a.kind == "composition" else None,
                               body.b.team_id if body.b.kind == "team" else None,
                               body.b.composition_id if body.b.kind == "composition" else None,
                               body.best_of, res["p_a"], res["likely_score"], CACHE.model_version,
                               json.dumps(res["factors"]))).lastrowid
            con.executemany("INSERT INTO prediction_maps VALUES (?,?,?,?,?,?)",
                            [(pid, i + 1, s["action"], s["side"], s["map_id"], s["p_a"]) for i, s in enumerate(res["veto"])])
        res["prediction_id"] = pid
    return res
