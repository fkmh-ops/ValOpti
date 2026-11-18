"""Tests d'intégration sur la base générée (data/valopti.db). Lancer : pytest -q (depuis backend/)."""
from __future__ import annotations

import math
import sqlite3

import pytest
from fastapi.testclient import TestClient

from etl.audit import CHECKS, run
from valopti.db import DB_PATH
from valopti.main import app

pytestmark = pytest.mark.skipif(not DB_PATH.exists(), reason="lancer d'abord python -m etl.build_db")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------------ données
def test_blocking_quality_checks_pass():
    res = run(DB_PATH)
    failed = {c.code: res[c.code] for c in CHECKS if c.blocking and res[c.code] not in (0, None)}
    assert failed == {}


def test_derived_tables_consistent():
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    q = lambda s: con.execute(s).fetchone()[0]  # noqa: E731
    # un joueur « actif » a une équipe courante, un joueur « sans équipe » n'en a pas
    assert q("SELECT COUNT(*) FROM player_profile pp JOIN players p USING(player_id) WHERE pp.status='active' AND p.current_team_id IS NULL") == 0
    assert q("SELECT COUNT(*) FROM player_profile pp JOIN players p USING(player_id) WHERE pp.status<>'active' AND p.current_team_id IS NOT NULL") == 0
    # usages d'agents : somme = 1 par joueur
    assert q("SELECT COUNT(*) FROM (SELECT player_id, SUM(usage) s FROM player_agent_stats GROUP BY 1 HAVING ABS(s-1) > 1e-6)") == 0
    # snapshots : bornes plausibles
    assert q("SELECT COUNT(*) FROM player_stats_snapshot WHERE rating < 0 OR rating > 4 OR kast_pct > 100 OR kpr < 0") == 0
    # agents : tous les rôles renseignés et dans la liste attendue
    assert q("SELECT COUNT(*) FROM agents WHERE role NOT IN ('duelist','initiator','controller','sentinel')") == 0
    # pool de cartes : uniquement de vraies cartes
    import json
    pool = json.loads(q("SELECT value FROM meta WHERE key='map_pool'"))
    assert 5 <= len(pool) <= 7
    con.close()


# ---------------------------------------------------------------------- API
def test_meta_and_home(client):
    m = client.get("/api/meta").json()
    assert m["snapshot_date"] and len(m["agents"]) >= 27 and m["map_pool"]
    h = client.get("/api/home").json()
    assert len(h["top_teams"]) == 6
    assert all(t["tier"] != "Game Changers" for t in h["top_teams"])
    for r in h["recent"]:
        assert r["winner_team_id"] in (r["team1_id"], r["team2_id"])
        assert max(r["team1_score"], r["team2_score"]) <= 3


def test_players_filters_and_sort(client):
    r = client.get("/api/players", params={"role": "controller", "min_rounds": 300, "sort": "acs", "dir": "desc", "limit": 50}).json()
    assert r["total"] > 0
    items = r["items"]
    assert all(p["main_role"] == "controller" or p["role"] == "controller" for p in items)
    assert all(p["rounds_played"] >= 300 for p in items)
    acs = [p["acs"] for p in items]
    assert acs == sorted(acs, reverse=True)
    assert all(0 <= v <= 100 for p in items for v in p["pct"].values() if v is not None)
    fa = client.get("/api/players", params={"status": "free_agent", "limit": 20}).json()["items"]
    assert all(p["is_free_agent"] and p["team_id"] is None for p in fa)
    assert client.get("/api/players", params={"sort": "drop table"}).status_code == 422


def test_player_and_team_detail(client):
    pid = client.get("/api/players", params={"min_rounds": 400, "limit": 1}).json()["items"][0]["player_id"]
    p = client.get(f"/api/players/{pid}").json()
    assert p["stats"]["rounds_played"] >= 400
    assert len(p["form"]) <= 10
    assert client.get("/api/players/999999999").status_code == 404
    top = client.get("/api/rankings", params={"limit": 1}).json()[0]
    t = client.get(f"/api/teams/{top['team_id']}").json()
    assert t["world_rank"] == 1 and len(t["roster"]) >= 5
    assert {m["name"] for m in t["maps"]} == {m["name"] for m in client.get("/api/meta").json()["map_pool"]}


def test_rankings_regions(client):
    world = client.get("/api/rankings").json()
    assert [t["elo"] for t in world] == sorted((t["elo"] for t in world), reverse=True)
    assert all(t["tier"] != "Game Changers" for t in world)
    emea = client.get("/api/rankings", params={"region": "EMEA"}).json()
    assert emea and all(t["region"] == "EMEA" for t in emea)
    gc = client.get("/api/rankings", params={"region": "gc"}).json()
    assert all(t["tier"] == "Game Changers" for t in gc)


def test_search(client):
    hits = client.get("/api/search", params={"q": "sentinels"}).json()
    assert any(h["kind"] == "team" and h["label"] == "Sentinels" for h in hits)


# -------------------------------------------------------------------- modèle
def test_prediction_is_a_distribution(client):
    teams = client.get("/api/rankings", params={"limit": 2}).json()
    for bo in (1, 3, 5):
        r = client.post("/api/predict", json={"a": {"kind": "team", "team_id": teams[0]["team_id"]},
                                               "b": {"kind": "team", "team_id": teams[1]["team_id"]}, "best_of": bo}).json()
        assert abs(sum(d["p"] for d in r["distribution"]) - 1) < 1e-9
        need = (bo + 1) // 2
        assert abs(r["p_a"] - sum(d["p"] for d in r["distribution"] if d["a"] == need)) < 1e-9
        played = [s for s in r["veto"] if s["action"] != "ban"]
        assert len(played) == bo
        assert len({s["map_id"] for s in r["veto"]}) == len(r["veto"])  # chaque carte une seule fois
    same = client.post("/api/predict", json={"a": {"kind": "team", "team_id": teams[0]["team_id"]},
                                              "b": {"kind": "team", "team_id": teams[0]["team_id"]}})
    assert same.status_code == 422


def test_stronger_team_favoured(client):
    ranks = client.get("/api/rankings", params={"limit": 300}).json()
    a, b = ranks[0]["team_id"], ranks[-1]["team_id"]
    r = client.post("/api/predict", json={"a": {"kind": "team", "team_id": a}, "b": {"kind": "team", "team_id": b}}).json()
    assert r["p_a"] > 0.75


def test_draft_analysis_rules(client):
    agents = {a["name"]: a["agent_id"] for a in client.get("/api/meta").json()["agents"]}
    ids = [p["player_id"] for p in client.get("/api/players", params={"min_rounds": 400, "limit": 5}).json()["items"]]
    balanced = [agents[n] for n in ("Jett", "Sova", "Omen", "Killjoy", "Raze")]
    no_ctrl = [agents[n] for n in ("Jett", "Sova", "Neon", "Killjoy", "Raze")]
    a1 = client.post("/api/draft/analyse", json={"slots": [{"player_id": p, "agent_id": a} for p, a in zip(ids, balanced)]}).json()
    a2 = client.post("/api/draft/analyse", json={"slots": [{"player_id": p, "agent_id": a} for p, a in zip(ids, no_ctrl)]}).json()
    assert 0 <= a1["score"] <= 100 and a2["score"] < a1["score"]
    assert any("contrôleur" in x["text"] for x in a2["alerts"] if x["level"] == "crit")
    dup = client.post("/api/draft/analyse", json={"slots": [{"player_id": ids[0]}] * 2 + [{}] * 3})
    assert dup.status_code == 422


def test_composition_crud(client):
    ids = [p["player_id"] for p in client.get("/api/players", params={"min_rounds": 400, "limit": 5}).json()["items"]]
    body = {"name": "__test_pytest__", "slots": [{"player_id": p, "agent_id": None} for p in ids]}
    c = client.post("/api/compositions", json=body)
    assert c.status_code == 201
    cid = c.json()["composition_id"]
    try:
        assert any(x["composition_id"] == cid for x in client.get("/api/compositions").json())
        again = client.post("/api/compositions", json=body).json()     # même nom -> mise à jour
        assert again["composition_id"] == cid and again["updated"]
        r = client.post("/api/predict", json={"a": {"kind": "composition", "composition_id": cid},
                                               "b": {"kind": "team", "team_id": client.get("/api/rankings").json()[0]["team_id"]}})
        assert r.status_code == 200 and r.json()["a"]["composition"]
    finally:
        assert client.delete(f"/api/compositions/{cid}").status_code == 204
    assert client.delete(f"/api/compositions/{cid}").status_code == 404
    bad = client.post("/api/compositions", json={"name": "x", "slots": [{"player_id": 999999999}] + [{}] * 4})
    assert bad.status_code == 422


# ------------------------------------------------------- modèle appris (backtest)
def test_logistic_fit_recovers_known_weights():
    import random
    from etl.ratings import fit_logistic
    rnd = random.Random(0)
    X, y = [], []
    for _ in range(20000):
        a, b = rnd.gauss(0, 1), rnd.gauss(0, 1)
        p = 1 / (1 + math.exp(-(1.5 * a - 0.7 * b)))
        X.append([a, b])
        y.append(int(rnd.random() < p))
    w = fit_logistic(X, y)
    assert abs(w[0] - 1.5) < 0.1 and abs(w[1] + 0.7) < 0.1


def test_series_probability():
    from etl.ratings import series_p
    assert abs(series_p([0.5, 0.5, 0.5], 3) - 0.5) < 1e-12
    assert abs(series_p([0.6], 1) - 0.6) < 1e-12
    p = 0.6
    assert abs(series_p([p, p], 3) - (p * p + 2 * p * p * (1 - p))) < 1e-12   # BO3 plié en 2 maps : decider complété
    assert series_p([0.7] * 5, 5) > series_p([0.7] * 3, 3) > 0.7


def test_production_uses_learned_model(client):
    import json
    from pathlib import Path
    params = json.loads((Path(__file__).parents[1] / "etl" / "model_params.json").read_text(encoding="utf-8"))
    m = client.get("/api/meta").json()
    assert m["model_version"] == params["model_version"]
    assert m["model_weights"] == params["weights"]
    bt = params["backtest"]
    assert bt["series_test"]["log_loss"] < bt["series_test_current"]["log_loss"]   # le nouveau modèle bat l'ancien
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    assert con.execute("SELECT COUNT(*) FROM team_map_elo").fetchone()[0] > 1000
    con.close()
