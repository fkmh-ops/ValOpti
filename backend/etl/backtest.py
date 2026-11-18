"""Backtest du modèle de prédiction sur l'historique réel.

Chaque match est prédit avec l'information disponible avant lui uniquement.
  - entraînement : matchs avant SPLIT ; test : matchs à partir de SPLIT
  - évaluation sur les matchs où les deux équipes ont au moins MIN_N matchs d'historique
    (comme dans l'application, qui ne classe que ces équipes)

Étapes :
  1. réglage de l'Elo (variantes : K, marge, inactivité, changement de roster, départ selon le circuit)
  2. comparaison des modèles par map : actuel (poids fixés à la main), Elo seul, régressions logistiques
  3. évaluation au niveau série (après veto connu) et calibration
Sorties : etl/model_params.json (lu par build_db et l'API) et data/RAPPORT_MODELE.md

Usage : python -m etl.backtest
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import asdict, replace
from pathlib import Path

from etl.ratings import (EloCfg, accuracy, brier, calibration, elo_p, fit_logistic, load_history, log_loss,
                         series_p, simulate)

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "valopti.db"
PARAMS = Path(__file__).with_name("model_params.json")
REPORT = ROOT / "data" / "RAPPORT_MODELE.md"
SPLIT = "2025-07-01"
MIN_N = 10
LN = math.log(10) / 400   # conversion points Elo -> logit
CURRENT = {"d_elo": 0.6, "d_wr": 300.0, "d_form": 500.0}   # modèle de la maquette


def metrics(ps, ys) -> dict:
    return {"n": len(ys), "log_loss": log_loss(ps, ys), "brier": brier(ps, ys), "accuracy": accuracy(ps, ys)}


def pred(sample: dict, w: dict) -> float:
    return elo_p(sum(w[k] * sample[k] for k in w))


def eligible(s) -> bool:
    return s["n1"] >= MIN_N and s["n2"] >= MIN_N


def elo_eval(h, cfg: EloCfg) -> tuple[dict, list]:
    st, maps = simulate(h, cfg, collect=True)
    test = [m for m in st.match_samples if m[1] >= SPLIT and m[4] >= MIN_N and m[5] >= MIN_N]
    return metrics([elo_p(m[3]) for m in test], [m[2] for m in test]), maps


def main():
    t0 = time.time()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    h = load_history(con)
    con.close()
    print(f"historique : {len(h.matches)} matchs ({time.time() - t0:.0f}s)")
    lines: list[str] = []

    # ------------------------------------------------------------ 1. Elo
    base = EloCfg()
    variants = {
        "actuel (K 40/24, marge 0,25)": base,
        "K 32/20": replace(base, k_new=32, k=20),
        "K 48/32": replace(base, k_new=48, k=32),
        "K 64/40": replace(base, k_new=64, k=40),
        "sans marge": replace(base, margin=0.0),
        "marge 0,5": replace(base, margin=0.5),
        "marge 0,75": replace(base, margin=0.75),
        "inactivité 90 j (-20 %)": replace(base, decay_days=90, decay_rate=0.2),
        "inactivité 180 j (-30 %)": replace(base, decay_days=180, decay_rate=0.3),
        "roster changé (-30 %)": replace(base, roster_shrink=0.3),
        "roster changé (-50 %)": replace(base, roster_shrink=0.5),
        "départ selon circuit": replace(base, tier_init={"VCT": 1700, "Challengers": 1600, "Game Changers": 1450, "Autre": 1450}),
    }
    res = {}
    for name, cfg in variants.items():
        res[name], _ = elo_eval(h, cfg)
        print(f"  Elo {name:32s} logloss {res[name]['log_loss']:.4f}  acc {res[name]['accuracy']:.3f}")
    ref = res["actuel (K 40/24, marge 0,25)"]["log_loss"]
    # combinaison gloutonne des variantes qui améliorent
    best_cfg, best_ll = base, ref
    for name in sorted(variants, key=lambda n: res[n]["log_loss"]):
        if res[name]["log_loss"] >= ref:
            continue
        v = variants[name]
        trial = replace(best_cfg, **{k: getattr(v, k) for k in asdict(v) if getattr(v, k) != getattr(base, k)})
        m, _ = elo_eval(h, trial)
        if m["log_loss"] < best_ll - 1e-5:
            best_cfg, best_ll = trial, m["log_loss"]
            print(f"  + {name} -> {best_ll:.4f}")
    res["combinaison retenue"], _ = elo_eval(h, best_cfg)

    lines += ["# Backtest du modèle de prédiction ValOpti", "",
              f"- Entraînement : matchs avant le {SPLIT} ; test : du {SPLIT} au dernier match.",
              f"- Évaluation sur les matchs où les deux équipes ont au moins {MIN_N} matchs d'historique.",
              "- Chaque prédiction n'utilise que l'information disponible avant le match.",
              "- Log loss : plus bas = meilleur (0,693 = pile ou face). Brier : idem (0,25 = pile ou face).", "",
              "## 1. Réglage de l'Elo (vainqueur du match, Elo seul)", "",
              "| Variante | Matchs test | Log loss | Brier | Précision |", "|---|--:|--:|--:|--:|"]
    lines += [f"| {k} | {v['n']} | {v['log_loss']:.4f} | {v['brier']:.4f} | {v['accuracy']:.1%} |" for k, v in res.items()]

    # ----------------------------------------------- 2. modèles par map
    map_k_res = {}
    samples_by_k = {}
    for mk in (0.0, 8.0, 16.0, 32.0):
        _, s = simulate(h, replace(best_cfg, map_k=mk), collect=True)
        samples_by_k[mk] = s
    _, S_cur = simulate(h, base, collect=True)        # modèle réellement en production : ancien Elo + anciens poids
    test_cur = [s for s in S_cur if s["date"] >= SPLIT and eligible(s)]
    feats_sets = {
        "Elo seul (ajusté)": ["d_elo"],
        "Elo + winrate carte + forme": ["d_elo", "d_wr", "d_form"],
        "Elo + winrate + forme + Elo par carte": ["d_elo", "d_wr", "d_form", "d_map"],
        "Elo + forme + Elo par carte": ["d_elo", "d_form", "d_map"],
    }
    rows = []
    cands = []
    for mk, S in samples_by_k.items():
        train = [s for s in S if s["date"] < SPLIT and eligible(s)]
        test = [s for s in S if s["date"] >= SPLIT and eligible(s)]
        ys = [s["y"] for s in test]
        if mk == 0.0:
            rows.append(("Modèle actuel (ancien Elo, poids 0,6 / 300 / 500)", None,
                         metrics([pred(s, CURRENT) for s in test_cur], [s["y"] for s in test_cur])))
            rows.append(("Nouvel Elo seul (non ajusté)", None, metrics([pred(s, {"d_elo": 1.0}) for s in test], ys)))
        for name, fs in feats_sets.items():
            if "d_map" in fs and mk == 0.0:
                continue
            if "d_map" not in fs and mk != 0.0:
                continue
            X = [[s[f] * LN for f in fs] for s in train]
            w = dict(zip(fs, fit_logistic(X, [s["y"] for s in train])))
            m = metrics([pred(s, w) for s in test], ys)
            label = name + (f" (K carte {mk:g})" if mk else "")
            rows.append((label, w, m))
            cands.append((label, w, m, mk, fs))
        map_k_res[mk] = (len(train), len(test))
    # parcimonie : parmi les modèles à moins de 0,001 du meilleur, le moins de variables ;
    # l'Elo par carte est requis pour que le veto simulé distingue les cartes
    top = min(c[2]["log_loss"] for c in cands)
    ok = [c for c in cands if c[2]["log_loss"] <= top + 0.001 and "d_map" in c[4]]
    best = min(ok or cands, key=lambda c: (len(c[4]), c[2]["log_loss"]))
    print("modèle retenu :", best[0], best[2])

    lines += ["", "## 2. Prédiction par map", "",
              f"Échantillon : {map_k_res[0.0][0]} maps d'entraînement, {map_k_res[0.0][1]} maps de test. "
              "Poids exprimés en points Elo : Δ = Σ poids × écart, puis p = 1 / (1 + 10^(−Δ/400)).", "",
              "| Modèle | Poids | Log loss | Brier | Précision |", "|---|---|--:|--:|--:|"]
    for label, w, m in rows:
        ws = ", ".join(f"{k} {v:.3g}" for k, v in w.items()) if w else "—"
        lines.append(f"| {label} | {ws} | {m['log_loss']:.4f} | {m['brier']:.4f} | {m['accuracy']:.1%} |")

    # ------------------------------------------------ 3. séries + calibration
    label, w_best, _, mk_best, fs_best = best
    S0, Sb = S_cur, samples_by_k[mk_best]

    def series_eval(S, w):
        by: dict[int, list] = {}
        for s in S:
            if s["date"] >= SPLIT and eligible(s) and s["bo"] in (1, 3, 5):
                by.setdefault(s["match_id"], []).append(s)
        ps, ys = [], []
        for mid, ss in by.items():
            ss.sort(key=lambda s: s["num"])
            wins1 = sum(s["y"] for s in ss)
            need = (ss[0]["bo"] + 1) // 2
            if max(wins1, len(ss) - wins1) != need:
                continue      # maps manquantes
            ps.append(series_p([pred(s, w) for s in ss], ss[0]["bo"]))
            ys.append(int(wins1 == need))
        return ps, ys

    pc, yc = series_eval(S0, CURRENT)
    pb, yb = series_eval(Sb, w_best)
    lines += ["", "## 3. Vainqueur de la série (veto connu, maps du match)", "",
              "| Modèle | Séries | Log loss | Brier | Précision |", "|---|--:|--:|--:|--:|"]
    for lab, (p_, y_) in (("Modèle actuel", (pc, yc)), (f"Nouveau : {label}", (pb, yb))):
        m = metrics(p_, y_)
        lines.append(f"| {lab} | {m['n']} | {m['log_loss']:.4f} | {m['brier']:.4f} | {m['accuracy']:.1%} |")

    test_c = [s for s in S0 if s["date"] >= SPLIT and eligible(s)]
    test_b = [s for s in Sb if s["date"] >= SPLIT and eligible(s)]
    cal_c = calibration([pred(s, CURRENT) for s in test_c], [s["y"] for s in test_c])
    cal_b = calibration([pred(s, w_best) for s in test_b], [s["y"] for s in test_b])
    lines += ["", "## 4. Calibration par map (test)", "",
              "Quand le modèle annonce p, l'équipe doit gagner avec une fréquence proche de p.", "",
              "| Tranche | Actuel : maps | annoncé | réel | Nouveau : maps | annoncé | réel |", "|---|--:|--:|--:|--:|--:|--:|"]
    cb = {round(x[0], 1): x for x in cal_b}
    for lo, hi, n, mp, my in cal_c:
        b = cb.get(round(lo, 1))
        lines.append(f"| {lo:.0%}–{hi:.0%} | {n} | {mp:.0%} | {my:.0%} | "
                     + (f"{b[2]} | {b[3]:.0%} | {b[4]:.0%} |" if b else "— | — | — |"))

    # --------------------------------------- poids de production (toutes données)
    allS = [s for s in Sb if eligible(s)]
    w_prod = dict(zip(fs_best, fit_logistic([[s[f] * LN for f in fs_best] for s in allS], [s["y"] for s in allS])))
    params = {
        "model_version": "elo-fitted-v2",
        "elo": asdict(replace(best_cfg, map_k=mk_best)),
        "weights": w_prod,
        "trained_on_maps": len(allS),
        "backtest": {"split": SPLIT, "min_matches": MIN_N, "model": label,
                     "map_test": best[2], "map_test_current": rows[0][2],
                     "series_test": metrics(pb, yb), "series_test_current": metrics(pc, yc)},
    }
    PARAMS.write_text(json.dumps(params, indent=2, ensure_ascii=False), encoding="utf-8")
    lines += ["", "## 5. Paramètres retenus pour la production", "",
              "Poids réappris sur toutes les maps éligibles (entraînement + test), écrits dans `backend/etl/model_params.json`.", "",
              "```json", json.dumps({k: params[k] for k in ("model_version", "elo", "weights", "trained_on_maps")},
                                    indent=2, ensure_ascii=False), "```", ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"rapport : {REPORT}  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
