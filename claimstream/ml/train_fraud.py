"""Train the fraud-scoring model with an OUT-OF-TIME split and compare it to the rules engine.

Out-of-time (train on older claims, test on the most recent months) mirrors production:
the model will always score claims from the future, never a random shuffle of the past.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
import joblib
import lightgbm as lgb
import mlflow
import numpy as np
import pandas as pd
import psycopg
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score

from claimstream.config import settings
from claimstream.ml.features import FEATURES, TRAINING_SQL, build_feature_frame

CUTOFF = pd.Timestamp("2026-06-01", tz="UTC")
PARAMS = dict(objective="binary", n_estimators=400, learning_rate=0.03, num_leaves=31,
              min_child_samples=40, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
              reg_lambda=1.0, random_state=11, verbose=-1)


def load_training_frame() -> pd.DataFrame:
    with psycopg.connect(settings.pg_dsn) as conn:
        return pd.read_sql(TRAINING_SQL, conn)


def rule_scores(X: pd.DataFrame) -> np.ndarray:
    """Score rows with the Java rules service (the same service used in production)."""
    with httpx.Client(base_url=settings.rules_url, timeout=5) as client:
        def one(row):
            return client.post("/evaluate", json=row).json()["score"]
        with ThreadPoolExecutor(16) as ex:
            return np.array(list(ex.map(one, X.to_dict("records"))))


def precision_at_k(y, s, frac) -> tuple[float, float]:
    k = max(int(len(s) * frac), 1)
    top = np.argsort(-s)[:k]
    return float(y[top].mean()), float(y[top].sum() / y.sum())


def main() -> None:
    t = time.time()
    raw = load_training_frame()
    raw["reported_ts"] = pd.to_datetime(raw["reported_ts"], utc=True)
    X, y = build_feature_frame(raw), raw["fraud_label"].astype(int).to_numpy()
    tr, te = (raw["reported_ts"] < CUTOFF).to_numpy(), (raw["reported_ts"] >= CUTOFF).to_numpy()
    print(f"train {tr.sum():,} (fraud {y[tr].mean():.2%}) | test {te.sum():,} (fraud {y[te].mean():.2%})")

    model = lgb.LGBMClassifier(**PARAMS).fit(X[tr], y[tr])
    p = model.predict_proba(X[te])[:, 1]
    rules = rule_scores(X[te]) / 100.0

    m = {
        "model_pr_auc": average_precision_score(y[te], p),
        "model_roc_auc": roc_auc_score(y[te], p),
        "rules_pr_auc": average_precision_score(y[te], rules),
        "rules_roc_auc": roc_auc_score(y[te], rules),
        "fraud_base_rate": float(y[te].mean()),
    }
    m["model_precision_top1pct"], m["model_recall_top1pct"] = precision_at_k(y[te], p, 0.01)
    m["model_precision_top3pct"], m["model_recall_top3pct"] = precision_at_k(y[te], p, 0.03)
    m["rules_precision_top3pct"], m["rules_recall_top3pct"] = precision_at_k(y[te], rules + 1e-6 * p, 0.03)

    # Operating threshold: highest recall while keeping precision >= 50% (investigator capacity).
    prec, rec, thr = precision_recall_curve(y[te], p)
    ok = np.where(prec[:-1] >= 0.5)[0]
    threshold = float(thr[ok[np.argmax(rec[:-1][ok])]]) if len(ok) else 0.5
    m["high_risk_threshold"] = threshold
    m["recall_at_threshold"] = float(((p >= threshold) & (y[te] == 1)).sum() / y[te].sum())
    m["precision_at_threshold"] = float(y[te][p >= threshold].mean())

    version = datetime.now(timezone.utc).strftime("fraud-lgbm-%Y%m%d%H%M")
    importance = dict(sorted(zip(FEATURES, model.booster_.feature_importance("gain").round(1).tolist()),
                             key=lambda kv: -kv[1]))

    mlflow.set_tracking_uri(settings.mlflow_uri)
    mlflow.set_experiment("claimstream-fraud")
    with mlflow.start_run(run_name=version):
        mlflow.log_params({**PARAMS, "cutoff": str(CUTOFF.date()), "n_features": len(FEATURES)})
        mlflow.log_metrics(m)
        mlflow.log_dict(importance, "feature_importance.json")
        mlflow.lightgbm.log_model(model.booster_, name="model")

    settings.model_dir.mkdir(parents=True, exist_ok=True)
    # Final model refit on ALL history for serving; threshold comes from the out-of-time test.
    final = lgb.LGBMClassifier(**PARAMS).fit(X, y)
    joblib.dump({"model": final, "features": FEATURES, "version": version, "threshold": threshold},
                settings.model_dir / "fraud_model.joblib")

    with psycopg.connect(settings.pg_dsn) as conn, conn.cursor() as cur:
        for k, v in m.items():
            cur.execute("INSERT INTO model_metrics (model_name, version, metric, value) VALUES (%s,%s,%s,%s)",
                        ("fraud", version, k, float(v)))
        cur.execute("INSERT INTO model_metrics VALUES ('fraud', %s, 'is_current', 1)", (version,))
    (settings.model_dir / "fraud_metrics.json").write_text(json.dumps({"version": version, **m,
                                                                      "importance": importance}, indent=2))
    print(json.dumps(m, indent=2))
    print("top features:", list(importance)[:6], f"| {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
