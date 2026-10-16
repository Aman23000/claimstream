# Model card: claims fraud scorer

| | |
|---|---|
| **Model** | LightGBM gradient-boosted trees, binary classifier (`claimstream/ml/train_fraud.py`) |
| **Version format** | `fraud-lgbm-YYYYMMDDHHMM`, logged to MLflow experiment `claimstream-fraud` |
| **Output** | Probability that a claim is fraudulent, combined with the rules score into LOW / MEDIUM / HIGH |
| **Serving** | In-process in the stream processor and in `POST /score`; p50 about 5 ms with warm caches |

## Intended use
Triage: rank incoming claims so investigators review the riskiest first. **Not** for automatically denying
claims. A HIGH score means "look at this", not "this is fraud".

## Training data
About 67K historical claims, 2.3% labelled fraud. Policies and claim amounts are real (freMTPL2);
timing, channel and fraud labels are simulated (see [data.md](../data.md)).

## Features (18), shared by training and serving through `ml/features.py`
Amount (log, and relative to the region median) · days since policy start · reporting delay · prior claims
on the policy in the last 90 days · number of policies sharing the payout account · night-time report flag ·
driver age · bonus-malus · vehicle age · channel (one-hot) · claim type (one-hot).

## Evaluation: out-of-time
Trained on claims reported before 2026-06-01, tested on 13,089 later claims (2.19% fraud).

| Metric | Model | Rules engine |
|---|---:|---:|
| PR-AUC | **0.363** | 0.112 |
| ROC-AUC | **0.892** | 0.801 |
| Precision / recall, top 1% flagged | 56% / 26% | — |
| Recall, top 3% flagged | **44%** | 25% |
| Operating threshold (precision ≥ 50%) | 0.286 → recall 29% | — |

**Most important features (gain):** night-time reporting, reporting delay, days since policy start, amount
relative to region, absolute amount, driver age.

**Live check:** on the streaming replay, 39% of HIGH alerts were true fraud vs 1.1% of LOW.

## Limitations and risks
- **Simulated labels.** Real fraud is more varied and adversarial; expect lower real-world performance.
- **Proxy features.** Driver age and region can correlate with protected characteristics. A real deployment
  needs a fairness review (alert rates by group) and legal sign-off on each feature.
- **Drift.** Fraudsters adapt. Monitor the score distribution (dashboard → Models) and retrain weekly.
- **Label delay.** Real fraud outcomes arrive months later; the out-of-time test assumes labels are known.
