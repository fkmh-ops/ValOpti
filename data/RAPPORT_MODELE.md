# Backtest du modèle de prédiction ValOpti

- Entraînement : matchs avant le 2025-07-01 ; test : du 2025-07-01 au dernier match.
- Évaluation sur les matchs où les deux équipes ont au moins 10 matchs d'historique.
- Chaque prédiction n'utilise que l'information disponible avant le match.
- Log loss : plus bas = meilleur (0,693 = pile ou face). Brier : idem (0,25 = pile ou face).

## 1. Réglage de l'Elo (vainqueur du match, Elo seul)

| Variante | Matchs test | Log loss | Brier | Précision |
|---|--:|--:|--:|--:|
| actuel (K 40/24, marge 0,25) | 7956 | 0.6280 | 0.2189 | 64.8% |
| K 32/20 | 7956 | 0.6312 | 0.2205 | 64.4% |
| K 48/32 | 7956 | 0.6252 | 0.2175 | 65.1% |
| K 64/40 | 7956 | 0.6234 | 0.2164 | 65.2% |
| sans marge | 7956 | 0.6311 | 0.2204 | 64.3% |
| marge 0,5 | 7956 | 0.6260 | 0.2180 | 65.1% |
| marge 0,75 | 7956 | 0.6250 | 0.2173 | 65.2% |
| inactivité 90 j (-20 %) | 7956 | 0.6313 | 0.2206 | 64.4% |
| inactivité 180 j (-30 %) | 7956 | 0.6275 | 0.2188 | 65.0% |
| roster changé (-30 %) | 7956 | 0.6326 | 0.2211 | 63.9% |
| roster changé (-50 %) | 7956 | 0.6371 | 0.2231 | 63.5% |
| départ selon circuit | 7956 | 0.6255 | 0.2178 | 65.2% |
| combinaison retenue | 7956 | 0.6185 | 0.2143 | 65.7% |

## 2. Prédiction par map

Échantillon : 36634 maps d'entraînement, 7806 maps de test. Poids exprimés en points Elo : Δ = Σ poids × écart, puis p = 1 / (1 + 10^(−Δ/400)).

| Modèle | Poids | Log loss | Brier | Précision |
|---|---|--:|--:|--:|
| Modèle actuel (ancien Elo, poids 0,6 / 300 / 500) | — | 0.6849 | 0.2442 | 58.4% |
| Nouvel Elo seul (non ajusté) | — | 0.6956 | 0.2467 | 59.0% |
| Elo seul (ajusté) | d_elo 0.66 | 0.6723 | 0.2392 | 59.0% |
| Elo + winrate carte + forme | d_elo 0.573, d_wr 59.2, d_form 198 | 0.6681 | 0.2373 | 59.5% |
| Elo + winrate + forme + Elo par carte (K carte 8) | d_elo 0.582, d_wr 16.5, d_form 197, d_map 0.65 | 0.6676 | 0.2371 | 59.7% |
| Elo + forme + Elo par carte (K carte 8) | d_elo 0.587, d_form 198, d_map 0.736 | 0.6676 | 0.2371 | 59.7% |
| Elo + winrate + forme + Elo par carte (K carte 16) | d_elo 0.584, d_wr 8.55, d_form 197, d_map 0.407 | 0.6676 | 0.2371 | 59.7% |
| Elo + forme + Elo par carte (K carte 16) | d_elo 0.587, d_form 197, d_map 0.433 | 0.6676 | 0.2371 | 59.6% |
| Elo + winrate + forme + Elo par carte (K carte 32) | d_elo 0.587, d_wr -4.34, d_form 196, d_map 0.28 | 0.6676 | 0.2371 | 59.5% |
| Elo + forme + Elo par carte (K carte 32) | d_elo 0.585, d_form 196, d_map 0.273 | 0.6676 | 0.2371 | 59.5% |

## 3. Vainqueur de la série (veto connu, maps du match)

| Modèle | Séries | Log loss | Brier | Précision |
|---|--:|--:|--:|--:|
| Modèle actuel | 3149 | 0.6821 | 0.2385 | 61.9% |
| Nouveau : Elo + forme + Elo par carte (K carte 32) | 3149 | 0.6528 | 0.2284 | 62.9% |

## 4. Calibration par map (test)

Quand le modèle annonce p, l'équipe doit gagner avec une fréquence proche de p.

| Tranche | Actuel : maps | annoncé | réel | Nouveau : maps | annoncé | réel |
|---|--:|--:|--:|--:|--:|--:|
| 0%–10% | 50 | 7% | 28% | 19 | 8% | 32% |
| 10%–20% | 272 | 16% | 31% | 130 | 16% | 22% |
| 20%–30% | 654 | 26% | 37% | 446 | 26% | 35% |
| 30%–40% | 1096 | 35% | 46% | 1013 | 36% | 41% |
| 40%–50% | 1355 | 45% | 50% | 1715 | 45% | 48% |
| 50%–60% | 1570 | 55% | 54% | 2064 | 55% | 55% |
| 60%–70% | 1397 | 65% | 59% | 1444 | 65% | 63% |
| 70%–80% | 931 | 75% | 66% | 746 | 74% | 70% |
| 80%–90% | 403 | 84% | 71% | 217 | 84% | 74% |
| 90%–100% | 78 | 93% | 86% | 12 | 91% | 83% |

## 5. Paramètres retenus pour la production

Poids réappris sur toutes les maps éligibles (entraînement + test), écrits dans `backend/etl/model_params.json`.

```json
{
  "model_version": "elo-fitted-v2",
  "elo": {
    "k_new": 64,
    "k": 40,
    "n_new": 15,
    "margin": 0.5,
    "decay_days": 180,
    "decay_rate": 0.3,
    "roster_shrink": 0.0,
    "tier_init": {
      "VCT": 1700,
      "Challengers": 1600,
      "Game Changers": 1450,
      "Autre": 1450
    },
    "map_k": 32.0,
    "mean": 1500.0
  },
  "weights": {
    "d_elo": 0.5507712409592506,
    "d_form": 203.53680564405693,
    "d_map": 0.25385522912717823
  },
  "trained_on_maps": 44440
}
```
