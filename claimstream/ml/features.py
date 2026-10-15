"""Fraud-model features. ONE definition used for both training and real-time scoring,
so the model never sees features computed differently online vs offline (training/serving skew).
"""
from __future__ import annotations

import math
from typing import Mapping

import pandas as pd

CHANNELS = ["web", "app", "phone", "agent"]
CLAIM_TYPES = ["collision", "theft", "glass", "liability", "fire"]

FEATURES = [
    "log_amount", "log_amount_vs_region", "days_since_policy_start", "report_delay_days",
    "policy_claims_90d", "shared_bank_policies", "report_hour_night", "driv_age",
    "bonus_malus", "veh_age",
    *[f"channel_{c}" for c in CHANNELS], *[f"type_{t}" for t in CLAIM_TYPES],
]


def build_features(raw: Mapping) -> dict[str, float]:
    """raw needs: amount, region_median_amount, loss_ts, reported_ts, policy_start,
    policy_claims_90d, shared_bank_policies, driv_age, bonus_malus, veh_age, channel, claim_type."""
    loss = pd.Timestamp(raw["loss_ts"])
    reported = pd.Timestamp(raw["reported_ts"])
    start = pd.Timestamp(raw["policy_start"])
    if start.tzinfo is None and loss.tzinfo is not None:
        start = start.tz_localize(loss.tzinfo)
    hour = reported.tz_convert("UTC").hour if reported.tzinfo else reported.hour
    f = {
        "log_amount": math.log1p(float(raw["amount"])),
        "log_amount_vs_region": math.log(float(raw["amount"]) / max(float(raw["region_median_amount"]), 1.0)),
        "days_since_policy_start": max((loss - start).days, 0),
        "report_delay_days": max((reported - loss).total_seconds() / 86400.0, 0.0),
        "policy_claims_90d": float(raw["policy_claims_90d"]),
        "shared_bank_policies": float(raw["shared_bank_policies"]),
        "report_hour_night": 1.0 if 0 <= hour < 5 else 0.0,
        "driv_age": float(raw["driv_age"]),
        "bonus_malus": float(raw["bonus_malus"]),
        "veh_age": float(raw["veh_age"]),
    }
    for c in CHANNELS:
        f[f"channel_{c}"] = 1.0 if raw["channel"] == c else 0.0
    for t in CLAIM_TYPES:
        f[f"type_{t}"] = 1.0 if raw["claim_type"] == t else 0.0
    return f


def build_feature_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Vectorised equivalent of build_features for training (tested for parity)."""
    loss = pd.to_datetime(raw["loss_ts"], utc=True)
    reported = pd.to_datetime(raw["reported_ts"], utc=True)
    start = pd.to_datetime(raw["policy_start"]).dt.tz_localize("UTC")
    out = pd.DataFrame(index=raw.index)
    amt = raw["amount"].astype(float)
    out["log_amount"] = (amt + 1).map(math.log)
    out["log_amount_vs_region"] = (amt / raw["region_median_amount"].astype(float).clip(lower=1.0)).map(math.log)
    out["days_since_policy_start"] = (loss - start).dt.days.clip(lower=0)
    out["report_delay_days"] = ((reported - loss).dt.total_seconds() / 86400.0).clip(lower=0)
    out["policy_claims_90d"] = raw["policy_claims_90d"].astype(float)
    out["shared_bank_policies"] = raw["shared_bank_policies"].astype(float)
    out["report_hour_night"] = (reported.dt.hour < 5).astype(float)
    for col in ("driv_age", "bonus_malus", "veh_age"):
        out[col] = raw[col].astype(float)
    for c in CHANNELS:
        out[f"channel_{c}"] = (raw["channel"] == c).astype(float)
    for t in CLAIM_TYPES:
        out[f"type_{t}"] = (raw["claim_type"] == t).astype(float)
    return out[FEATURES]


# SQL that assembles the raw inputs for every historical claim (used for training).
TRAINING_SQL = """
WITH reg AS (
    SELECT p.region, percentile_cont(0.5) WITHIN GROUP (ORDER BY c.amount) AS region_median_amount
    FROM claims c JOIN policies p USING (policy_id)
    WHERE c.source = 'history'
    GROUP BY p.region
), bank AS (
    SELECT bank_account_hash, COUNT(*) AS shared_bank_policies
    FROM policies GROUP BY bank_account_hash
)
SELECT c.claim_id, c.amount, c.loss_ts, c.reported_ts, c.channel, c.claim_type, c.fraud_label,
       p.policy_start, p.driv_age, p.bonus_malus, p.veh_age, p.region,
       reg.region_median_amount, bank.shared_bank_policies,
       (SELECT COUNT(*) FROM claims c2
         WHERE c2.policy_id = c.policy_id
           AND c2.loss_ts <  c.loss_ts
           AND c2.loss_ts >= c.loss_ts - INTERVAL '90 days') AS policy_claims_90d
FROM claims c
JOIN policies p USING (policy_id)
JOIN reg USING (region)
JOIN bank USING (bank_account_hash)
WHERE c.source = 'history'
"""
