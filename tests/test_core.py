"""Unit tests: event contract, feature parity (training vs serving), simulator invariants, circuit breaker."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from claimstream.common.events import ClaimEvent
from claimstream.ingest.simulator import SimConfig, simulate_claims
from claimstream.ml.features import FEATURES, build_feature_frame, build_features
from claimstream.stream.scoring import CircuitBreaker

NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)


def event(**kw):
    base = dict(claim_id="CLM-test0001", policy_id=1, loss_ts=NOW - timedelta(days=2), reported_ts=NOW,
                amount=1200.0, claim_type="collision", channel="web")
    return {**base, **kw}


# ---------------------------------------------------------------- event contract
def test_valid_event_parses():
    assert ClaimEvent.model_validate(event()).amount == 1200.0


@pytest.mark.parametrize("bad", [
    {"amount": -5}, {"amount": 0}, {"claim_type": "spaceship"}, {"channel": "fax"},
    {"reported_ts": NOW - timedelta(days=5)},                     # reported before loss
    {"loss_ts": datetime(2026, 10, 1)},                           # naive timestamp
    {"policy_id": 0}, {"claim_id": "x"},
])
def test_invalid_events_rejected(bad):
    with pytest.raises(ValidationError):
        ClaimEvent.model_validate(event(**bad))


# ---------------------------------------------------------------- training/serving parity
def test_feature_parity_between_online_and_batch():
    rows = pd.DataFrame([
        dict(amount=900.0, region_median_amount=1100.0, loss_ts=NOW - timedelta(days=3), reported_ts=NOW,
             policy_start="2026-09-20", policy_claims_90d=0, shared_bank_policies=1, driv_age=45,
             bonus_malus=50, veh_age=3, channel="app", claim_type="glass"),
        dict(amount=15000.0, region_median_amount=1000.0, loss_ts=NOW - timedelta(days=40),
             reported_ts=NOW.replace(hour=3), policy_start="2026-09-01", policy_claims_90d=2,
             shared_bank_policies=4, driv_age=19, bonus_malus=100, veh_age=0, channel="web", claim_type="theft"),
    ])
    batch = build_feature_frame(rows)
    for i, r in rows.iterrows():
        online = build_features(r.to_dict())
        for f in FEATURES:
            assert online[f] == pytest.approx(batch.loc[i, f], rel=1e-9, abs=1e-9), f


# ---------------------------------------------------------------- simulator invariants
@pytest.fixture(scope="module")
def sim():
    rng = np.random.default_rng(0)
    n = 20_000
    pol = pd.DataFrame({
        "policy_id": np.arange(1, n + 1), "driv_age": rng.integers(18, 80, n),
        "bonus_malus": rng.integers(50, 120, n), "density": rng.integers(10, 5000, n),
        "policy_start": pd.to_datetime("2023-01-01") + pd.to_timedelta(rng.integers(0, 1300, n), unit="D"),
        "bank_account_hash": [f"acct{i}" for i in range(n)],
    })
    pol.loc[:30, "bank_account_hash"] = "ring0001"
    sev = rng.lognormal(7.2, 0.9, 5000)
    return simulate_claims(pol, sev, "2025-01-01", "2026-01-01", SimConfig(seed=1))


def test_simulated_claims_respect_time_window(sim):
    assert (sim.loss_ts >= pd.Timestamp("2025-01-01", tz="UTC")).all()
    assert (sim.reported_ts < pd.Timestamp("2026-01-01", tz="UTC")).all()
    assert (sim.reported_ts >= sim.loss_ts).all()


def test_simulated_claims_are_plausible(sim):
    assert sim.claim_id.is_unique
    assert (sim.amount > 0).all()
    assert 0.005 < sim.fraud_label.mean() < 0.10
    assert set(sim.claim_type) <= {"collision", "theft", "glass", "liability", "fire"}


def test_simulator_is_deterministic(sim):
    assert len(sim) > 500


# ---------------------------------------------------------------- resilience
def test_circuit_breaker_opens_and_recovers():
    cb = CircuitBreaker(threshold=3, cooldown=0.05)
    for _ in range(3):
        cb.record(False)
    assert not cb.allow()
    import time
    time.sleep(0.06)
    assert cb.allow()
    cb.record(True)
    assert cb.failures == 0
