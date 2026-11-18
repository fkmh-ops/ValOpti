"""Moteur de notation partagé par l'ETL (production) et le backtest.

Rejoue l'historique chronologiquement. Pour chaque map jouée, les variables sont calculées
AVANT le match (aucune fuite d'information) :
  d_elo   : écart d'Elo d'équipe
  d_wr    : écart de winrate lissé sur la carte (12 mois glissants, +2 V / +4 maps)
  d_form  : écart de forme (rating moyen des 5 joueurs alignés sur leurs 5 maps précédentes)
  d_map   : écart d'Elo spécifique à la carte (décalage appris par équipe et par carte)
"""
from __future__ import annotations

import collections
import math
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date


def event_tier(name: str | None) -> str | None:
    if not name:
        return None
    e = name.lower()
    if "game changers" in e:
        return "Game Changers"
    if "challengers" in e or "ascension" in e:
        return "Challengers"
    if re.search(r"\bvct\b|champions tour|valorant champions\b|valorant masters|^masters ", e):
        return "VCT"
    return None


@dataclass
class EloCfg:
    k_new: float = 40          # K sur les n_new premiers matchs
    k: float = 24
    n_new: int = 15
    margin: float = 0.25       # majoration de K par map d'écart au-delà de 1
    decay_days: int = 0        # 0 = pas de retour vers la moyenne après inactivité
    decay_rate: float = 0.0    # part de l'écart à la moyenne perdue par période de decay_days
    roster_shrink: float = 0.0  # part de l'écart perdue si >= 3 joueurs changent
    tier_init: dict | None = None  # Elo de départ selon le circuit du 1er match
    map_k: float = 0.0         # K de l'Elo par carte (0 = désactivé)
    mean: float = 1500.0


@dataclass
class History:
    matches: list[tuple]                       # (match_id, date, t1, t2, winner, s1, s2, best_of, tier)
    maps: dict[int, list[tuple]]               # match_id -> [(map_id, winner, number)]
    lineup: dict[tuple[int, int], frozenset]   # (match_id, team) -> joueurs
    ratings: dict[int, list[tuple]]            # match_id -> [(player_id, team, rating)]


def load_history(con: sqlite3.Connection) -> History:
    con.row_factory = None
    matches = con.execute("""
        SELECT m.match_id, m.match_date, m.team1_id, m.team2_id, m.winner_team_id, m.team1_score, m.team2_score,
               m.best_of, e.name
        FROM matches m LEFT JOIN events e ON e.event_id = m.event_id
        WHERE m.status='final' AND m.is_forfeit=0 AND m.winner_team_id IS NOT NULL
          AND m.team1_id IS NOT NULL AND m.team2_id IS NOT NULL AND m.match_date IS NOT NULL
        ORDER BY m.match_date, m.match_id""").fetchall()
    matches = [(*r[:8], event_tier(r[8])) for r in matches]
    maps: dict[int, list] = collections.defaultdict(list)
    for mid, map_id, w, num in con.execute("""SELECT match_id, map_id, winner_team_id, map_number FROM match_maps
                                              WHERE winner_team_id IS NOT NULL ORDER BY match_id, map_number"""):
        maps[mid].append((map_id, w, num))
    lineup: dict[tuple, set] = collections.defaultdict(set)
    ratings: dict[int, list] = collections.defaultdict(list)
    for mid, pid, tid, r in con.execute("""SELECT mm.match_id, s.player_id, s.team_id, s.rating FROM player_map_stats s
                                           JOIN match_maps mm USING(match_map_id) ORDER BY mm.match_id, mm.map_number"""):
        lineup[(mid, tid)].add(pid)
        if r is not None:
            ratings[mid].append((pid, tid, r))
    return History(matches, maps, {k: frozenset(v) for k, v in lineup.items()}, ratings)


def elo_p(d: float) -> float:
    return 1 / (1 + 10 ** (-d / 400))


@dataclass
class State:
    elo: dict = field(default_factory=dict)
    n: collections.Counter = field(default_factory=collections.Counter)
    last: dict = field(default_factory=dict)            # team -> date du dernier match
    lineup: dict = field(default_factory=dict)          # team -> dernier roster connu
    map_off: dict = field(default_factory=lambda: collections.defaultdict(float))   # (team, map) -> décalage
    map_res: dict = field(default_factory=lambda: collections.defaultdict(collections.deque))  # (team, map) -> (date, won)
    pform: dict = field(default_factory=lambda: collections.defaultdict(lambda: collections.deque(maxlen=5)))
    hist: dict = field(default_factory=lambda: collections.defaultdict(list))   # team -> [(date, 'W'/'L', match_id)]
    match_samples: list = field(default_factory=list)   # niveau match : (match_id, date, y, d_elo, n1, n2, tier)


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(a) - date.fromisoformat(b)).days


def simulate(h: History, cfg: EloCfg, collect: bool = False) -> tuple[State, list[dict]]:
    st = State()
    samples: list[dict] = []
    for mid, d, t1, t2, w, s1, s2, bo, tier in h.matches:
        # ---- état des équipes avant le match
        for t in (t1, t2):
            if t not in st.elo:
                st.elo[t] = (cfg.tier_init or {}).get(tier or "Autre", cfg.mean) if cfg.tier_init else cfg.mean
            elif cfg.decay_days and t in st.last:
                gap = _days(d, st.last[t])
                if gap > cfg.decay_days:
                    f = (1 - cfg.decay_rate) ** (gap / cfg.decay_days)
                    st.elo[t] = cfg.mean + (st.elo[t] - cfg.mean) * f
            new = h.lineup.get((mid, t))
            old = st.lineup.get(t)
            if cfg.roster_shrink and new and old and len(new & old) <= 2:
                st.elo[t] = cfg.mean + (st.elo[t] - cfg.mean) * (1 - cfg.roster_shrink)
        ra, rb = st.elo[t1], st.elo[t2]

        if collect:
            st.match_samples.append((mid, d, int(w == t1), ra - rb, st.n[t1], st.n[t2], tier, bo))

            def form(t):
                vals = [sum(st.pform[p]) / len(st.pform[p]) for p in h.lineup.get((mid, t), ()) if st.pform[p]]
                return sum(vals) / len(vals) if vals else None

            def wr(t, m):
                q = st.map_res[(t, m)]
                while q and _days(d, q[0][0]) > 365:
                    q.popleft()
                return (sum(x[1] for x in q) + 2) / (len(q) + 4)

            f1, f2 = form(t1), form(t2)
            for map_id, mw, num in h.maps.get(mid, ()):
                if map_id is None:
                    continue
                samples.append({
                    "match_id": mid, "date": d, "bo": bo, "num": num, "y": int(mw == t1),
                    "n1": st.n[t1], "n2": st.n[t2], "tier": tier,
                    "d_elo": ra - rb, "d_wr": wr(t1, map_id) - wr(t2, map_id),
                    "d_form": (f1 - f2) if f1 is not None and f2 is not None else 0.0,
                    "d_map": st.map_off[(t1, map_id)] - st.map_off[(t2, map_id)],
                })

        # ---- mises à jour après le match
        ea = elo_p(ra - rb)
        sa = 1.0 if w == t1 else 0.0
        margin = 1.0 + cfg.margin * max(0, abs((s1 or 0) - (s2 or 0)) - 1)
        for t, r, s, e in ((t1, ra, sa, ea), (t2, rb, 1 - sa, 1 - ea)):
            k = (cfg.k_new if st.n[t] < cfg.n_new else cfg.k) * margin
            st.elo[t] = r + k * (s - e)
            st.n[t] += 1
            st.last[t] = d
            st.hist[t].append((d, "W" if w == t else "L", mid))
            if (mid, t) in h.lineup:
                st.lineup[t] = h.lineup[(mid, t)]
        for map_id, mw, _ in h.maps.get(mid, ()):
            if map_id is None:
                continue
            for t in (t1, t2):
                st.map_res[(t, map_id)].append((d, int(mw == t)))
            if cfg.map_k:
                pm = elo_p(ra - rb + st.map_off[(t1, map_id)] - st.map_off[(t2, map_id)])
                delta = cfg.map_k * ((1.0 if mw == t1 else 0.0) - pm)
                st.map_off[(t1, map_id)] += delta
                st.map_off[(t2, map_id)] -= delta
        for pid, _, r in h.ratings.get(mid, ()):
            st.pform[pid].append(r)
    return st, samples


# --------------------------------------------------------------- évaluation
def log_loss(ps, ys) -> float:
    eps = 1e-12
    return -sum(y * math.log(max(p, eps)) + (1 - y) * math.log(max(1 - p, eps)) for p, y in zip(ps, ys)) / len(ys)


def brier(ps, ys) -> float:
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ys)


def accuracy(ps, ys) -> float:
    return sum((p > 0.5) == bool(y) for p, y in zip(ps, ys) if p != 0.5) / max(1, sum(p != 0.5 for p in ps))


def calibration(ps, ys, bins: int = 10) -> list[tuple]:
    out = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = [(p, y) for p, y in zip(ps, ys) if lo <= p < hi or (b == bins - 1 and p == 1)]
        if sel:
            out.append((lo, hi, len(sel), sum(p for p, _ in sel) / len(sel), sum(y for _, y in sel) / len(sel)))
    return out


def fit_logistic(X: list[list[float]], y: list[int], l2: float = 1e-3, iters: int = 25) -> list[float]:
    """Régression logistique sans intercept (le modèle doit être symétrique A/B), Newton-Raphson."""
    k = len(X[0])
    w = [0.0] * k
    for _ in range(iters):
        g = [l2 * wi for wi in w]
        H = [[l2 if i == j else 0.0 for j in range(k)] for i in range(k)]
        for xi, yi in zip(X, y):
            z = sum(a * b for a, b in zip(w, xi))
            p = 1 / (1 + math.exp(-max(-35, min(35, z))))
            r = p - yi
            s = p * (1 - p)
            for a in range(k):
                g[a] += r * xi[a]
                for b in range(k):
                    H[a][b] += s * xi[a] * xi[b]
        step = _solve(H, g)
        w = [wi - si for wi, si in zip(w, step)]
        if max(abs(s) for s in step) < 1e-9:
            break
    return w


def _solve(A: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        for r in range(n):
            if r != c and M[c][c]:
                f = M[r][c] / M[c][c]
                M[r] = [x - f * y for x, y in zip(M[r], M[c])]
    return [M[i][n] / M[i][i] for i in range(n)]


def series_p(map_ps: list[float], best_of: int) -> float:
    """Probabilité de gagner la série. Les maps non jouées (série pliée avant le decider)
    prennent la probabilité moyenne des maps connues."""
    need = (best_of + 1) // 2
    avg = sum(map_ps) / len(map_ps)
    seq = list(map_ps) + [avg] * max(0, best_of - len(map_ps))
    states = {(0, 0): 1.0}
    win = 0.0
    for p in seq:
        nx: dict = collections.defaultdict(float)
        for (a, b), v in states.items():
            if a == need:
                win += v
                continue
            if b == need:
                continue
            nx[(a + 1, b)] += v * p
            nx[(a, b + 1)] += v * (1 - p)
        states = nx
    win += sum(v for (a, _), v in states.items() if a == need)
    return win
