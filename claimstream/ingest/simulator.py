"""Claim simulator.

Policies and claim-size distribution are REAL (freMTPL2, 678K French motor policies and 26K
real claim amounts). Claim timing, channels and fraud are SIMULATED, because no public dataset
publishes fraud labels. The fraud patterns follow the red flags insurers' special investigation
units (SIUs) actually look for:

  early_claim     loss shortly after the policy starts
  inflated        amount far above typical for the region
  repeat          several claims on one policy in a short window
  late_report     loss reported long after it happened
  ring            several policies paying out to one shared bank account
  night_report    reported in the small hours (weak signal)

Legitimate claims also show these traits sometimes (noise), so detection isn't trivial.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

import numpy as np
import pandas as pd

CLAIM_TYPES = np.array(["collision", "theft", "glass", "liability", "fire"])
TYPE_P = np.array([0.52, 0.08, 0.22, 0.15, 0.03])
TYPE_SEV = {"collision": 1.0, "theft": 1.6, "glass": 0.35, "liability": 1.3, "fire": 2.2}
CHANNELS = np.array(["web", "app", "phone", "agent"])
CHANNEL_P = np.array([0.38, 0.27, 0.25, 0.10])


@dataclass
class SimConfig:
    base_frequency: float = 0.0737      # claims per policy-year, from the real data
    fraud_rate: float = 0.025
    n_rings: int = 60
    seed: int = 7


def load_policies(freq_parquet, seed: int = 7, n_rings: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.read_parquet(freq_parquet)
    pol = pd.DataFrame({
        "policy_id": df["IDpol"].astype("int64"),
        "exposure": df["Exposure"].clip(upper=1.0).astype("float32"),
        "veh_power": df["VehPower"], "veh_age": df["VehAge"], "driv_age": df["DrivAge"],
        "bonus_malus": df["BonusMalus"], "veh_brand": df["VehBrand"], "veh_gas": df["VehGas"],
        "area": df["Area"], "density": df["Density"], "region": df["Region"],
    })
    start = pd.Timestamp("2022-01-01")
    pol["policy_start"] = (start + pd.to_timedelta(rng.integers(0, 1700, len(pol)), unit="D")).date
    pol["bank_account_hash"] = [f"{int(x):016x}" for x in rng.integers(0, 2**62, len(pol))]
    # Fraud rings: small groups of policies sharing one payout account
    ring_ids = rng.choice(len(pol), size=n_rings * 6, replace=False)
    for r in range(n_rings):
        members = ring_ids[r * 6:(r + 1) * 6][: rng.integers(3, 7)]
        pol.loc[pol.index[members], "bank_account_hash"] = f"ring{r:04d}{uuid.uuid4().hex[:8]}"
    # Legit account sharing (families) so a shared account alone isn't proof of fraud
    fam = rng.choice(len(pol), size=4000, replace=False)
    pol.loc[pol.index[fam[1::2]], "bank_account_hash"] = pol.loc[pol.index[fam[0::2]], "bank_account_hash"].values
    return pol


def policy_risk(pol: pd.DataFrame) -> np.ndarray:
    """Relative claim frequency by rating factors (shape learned from the real data)."""
    bm = np.exp(0.018 * (pol["bonus_malus"].to_numpy() - 50))
    age = np.where(pol["driv_age"] < 21, 2.8, np.where(pol["driv_age"] < 26, 1.7, 1.0))
    dens = 1 + 0.06 * np.log1p(pol["density"].to_numpy()) / 3
    r = bm * age * dens
    return r / r.mean()


def simulate_claims(pol: pd.DataFrame, severities: np.ndarray, start: str, end: str,
                    cfg: SimConfig = SimConfig(), source: str = "history") -> pd.DataFrame:
    rng = np.random.default_rng(cfg.seed)
    t0, t1 = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    p_start = pd.to_datetime(pol["policy_start"]).dt.tz_localize("UTC")
    active_from = p_start.where(p_start > t0, t0)
    active_years = ((t1 - active_from).dt.days.clip(lower=0) / 365.25).to_numpy()
    lam = cfg.base_frequency * policy_risk(pol) * active_years
    n = rng.poisson(lam)
    idx = np.repeat(np.arange(len(pol)), n)
    if len(idx) == 0:
        return pd.DataFrame()
    P = pol.iloc[idx].reset_index(drop=True)
    af = active_from.iloc[idx].reset_index(drop=True)
    span = (t1 - af).dt.total_seconds().to_numpy()

    # Seasonality: more claims in winter months and on weekdays (accept-reject sampling)
    u = rng.random(len(P)) * span
    loss = af + pd.to_timedelta(u, unit="s")
    month_w = np.where(loss.dt.month.isin([11, 12, 1, 2]), 1.0, 0.85)
    dow_w = np.where(loss.dt.dayofweek >= 5, 0.8, 1.0)
    keep = rng.random(len(P)) < month_w * dow_w
    P, loss = P[keep].reset_index(drop=True), loss[keep].reset_index(drop=True)
    m = len(P)

    ctype = rng.choice(CLAIM_TYPES, size=m, p=TYPE_P)
    sev_mult = np.array([TYPE_SEV[t] for t in ctype])
    amount = rng.choice(severities, size=m) * sev_mult * rng.lognormal(0, 0.15, m)
    delay_days = rng.gamma(1.4, 2.2, m)                       # most reported within a week
    late_legit = rng.random(m) < 0.03                          # some honest late reports
    delay_days[late_legit] += rng.uniform(25, 90, late_legit.sum())
    channel = rng.choice(CHANNELS, size=m, p=CHANNEL_P)
    hour = rng.choice(24, size=m, p=_hour_profile())

    # ----- inject fraud -----
    ring = P["bank_account_hash"].str.startswith("ring").to_numpy()
    fraud = ring & (rng.random(m) < 0.75)
    extra = (~fraud) & (rng.random(m) < cfg.fraud_rate * 0.8)
    pattern = rng.choice(["early_claim", "inflated", "late_report", "night_report"], size=m,
                         p=[0.35, 0.35, 0.2, 0.1])
    fraud |= extra
    ps = pd.to_datetime(P["policy_start"]).dt.tz_localize("UTC")
    early = extra & (pattern == "early_claim") & (ps >= t0).to_numpy()
    loss = loss.where(~early, ps + pd.to_timedelta(rng.uniform(1, 25, m), unit="D"))
    infl = (extra & (pattern == "inflated")) | (fraud & ring & (rng.random(m) < 0.5))
    amount = np.where(infl, amount * rng.uniform(3, 8, m), amount)
    late = extra & (pattern == "late_report")
    delay_days = np.where(late, delay_days + rng.uniform(30, 100, m), delay_days)
    night = fraud & ((pattern == "night_report") | (rng.random(m) < 0.25))
    hour = np.where(night, rng.integers(0, 5, m), hour)
    channel = np.where(fraud & (rng.random(m) < 0.5), "web", channel)

    reported = (loss + pd.to_timedelta(delay_days, unit="D")).dt.floor("D") + pd.to_timedelta(
        hour * 3600 + rng.integers(0, 3600, m), unit="s")
    reported = reported.where(reported >= loss, loss + pd.Timedelta(minutes=30))
    out = pd.DataFrame({
        "claim_id": [f"CLM-{int(x):016x}" for x in rng.integers(0, 2**62, m)],
        "policy_id": P["policy_id"].to_numpy(),
        "loss_ts": loss, "reported_ts": reported,
        "amount": np.round(np.clip(amount, 25, 2_000_000), 2),
        "claim_type": ctype, "channel": channel, "source": source, "fraud_label": fraud,
    })
    # Repeat-claim fraud: duplicate some fraudulent claims on the same policy weeks later
    rep = out[out.fraud_label & (rng.random(m) < 0.15)].copy()
    shift = pd.to_timedelta(rng.uniform(10, 60, len(rep)), unit="D")
    rep["loss_ts"] = rep["loss_ts"] + shift
    rep["reported_ts"] = rep["reported_ts"] + shift
    rep["claim_id"] = [f"CLM-{uuid.uuid4().hex[:16]}" for _ in range(len(rep))]
    out = pd.concat([out, rep], ignore_index=True)
    # Claims not yet reported by the cut-off are unknown to the insurer (IBNR) -> excluded.
    out = out[(out.loss_ts >= t0) & (out.reported_ts < t1)]
    return out.sort_values("reported_ts").reset_index(drop=True)


def _hour_profile() -> np.ndarray:
    h = np.array([0.4, 0.3, 0.2, 0.2, 0.3, 0.6, 1.2, 2.2, 3.4, 4.2, 4.4, 4.2,
                  3.8, 4.0, 4.1, 3.9, 3.6, 3.2, 2.6, 2.0, 1.6, 1.2, 0.9, 0.6])
    return h / h.sum()
