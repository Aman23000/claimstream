"""Real-time enrichment + scoring for one claim: features -> ML model + Java rules -> risk level."""
from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx
import joblib
import numpy as np
import pandas as pd
import redis
from psycopg.rows import tuple_row

from claimstream.common.events import ClaimEvent
from claimstream.config import settings
from claimstream.ml.features import FEATURES, build_features

POLICY_TTL_S = 3600


class CircuitBreaker:
    """Stop calling a failing dependency for `cooldown` seconds after `threshold` consecutive errors."""

    def __init__(self, threshold: int = 5, cooldown: float = 30.0):
        self.threshold, self.cooldown = threshold, cooldown
        self.failures, self.open_until = 0, 0.0
        self._lock = threading.Lock()

    def allow(self) -> bool:
        return time.monotonic() >= self.open_until

    def record(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self.failures = 0
            else:
                self.failures += 1
                if self.failures >= self.threshold:
                    self.open_until = time.monotonic() + self.cooldown
                    self.failures = 0


class Scorer:
    """Thread-safe: share one instance; each worker passes its own DB connection."""

    def __init__(self, r: redis.Redis | None = None):
        bundle = joblib.load(settings.model_dir / "fraud_model.joblib")
        self.model, self.version, self.threshold = bundle["model"], bundle["version"], bundle["threshold"]
        self.r = r or redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self.http = httpx.Client(base_url=settings.rules_url, timeout=0.5)
        self.breaker = CircuitBreaker()
        self._medians: dict[str, float] = {}
        self._medians_at = 0.0

    # ---------------------------------------------------------------- lookups (cache-aside)
    def region_medians(self, conn) -> dict[str, float]:
        if time.monotonic() - self._medians_at > 600 or not self._medians:
            cached = self.r.hgetall("cs:region_median")
            if not cached:
                rows = _q(conn,
                    "SELECT p.region, percentile_cont(0.5) WITHIN GROUP (ORDER BY c.amount) "
                    "FROM claims c JOIN policies p USING (policy_id) WHERE c.source='history' "
                    "GROUP BY p.region").fetchall()
                cached = {reg: str(v) for reg, v in rows}
                self.r.hset("cs:region_median", mapping=cached)
                self.r.expire("cs:region_median", 86400)
            self._medians = {k: float(v) for k, v in cached.items()}
            self._medians_at = time.monotonic()
        return self._medians

    def policy(self, conn, policy_id: int) -> dict[str, Any] | None:
        key = f"cs:policy:{policy_id}"
        if (hit := self.r.get(key)) is not None:
            cached = json.loads(hit)
            try:                                   # never trust a cache entry blindly
                pd.Timestamp(cached["policy_start"])
                return cached
            except (KeyError, ValueError):
                self.r.delete(key)
        row = _q(conn,
            "SELECT p.policy_start, p.driv_age, p.bonus_malus, p.veh_age, p.region, p.bank_account_hash, "
            "(SELECT COUNT(*) FROM policies b WHERE b.bank_account_hash = p.bank_account_hash) "
            "FROM policies p WHERE p.policy_id = %s", (policy_id,)).fetchone()
        if row is None:
            return None
        pol = dict(zip(["policy_start", "driv_age", "bonus_malus", "veh_age", "region",
                        "bank_account_hash", "shared_bank_policies"], row))
        pol["policy_start"] = str(pol["policy_start"])
        self.r.set(key, json.dumps(pol), ex=POLICY_TTL_S)
        return pol

    # ---------------------------------------------------------------- scoring
    def score(self, conn, ev: ClaimEvent) -> dict[str, Any]:
        t0 = time.perf_counter()
        pol = self.policy(conn, ev.policy_id)
        if pol is None:
            raise ValueError(f"unknown policy_id {ev.policy_id}")
        prior = _q(conn,
            "SELECT COUNT(*) FROM claims WHERE policy_id=%s AND loss_ts < %s "
            "AND loss_ts >= %s - INTERVAL '90 days' AND claim_id <> %s",
            (ev.policy_id, ev.loss_ts, ev.loss_ts, ev.claim_id)).fetchone()[0]
        raw = {**ev.model_dump(), **pol, "policy_claims_90d": prior,
               "region_median_amount": self.region_medians(conn).get(pol["region"], 1500.0)}
        feats = build_features(raw)
        p = float(self.model.predict_proba(pd.DataFrame([feats], columns=FEATURES))[:, 1][0])
        rule_score, rules = self._rules(feats)
        if p >= self.threshold or rule_score >= 60:
            level = "HIGH"
        elif p >= self.threshold / 3 or rule_score >= 30:
            level = "MEDIUM"
        else:
            level = "LOW"
        return {"claim_id": ev.claim_id, "model_score": round(p, 5), "rule_score": rule_score,
                "rules_hit": rules, "risk_level": level, "model_version": self.version,
                "region": pol["region"], "latency_ms": round((time.perf_counter() - t0) * 1000, 2)}

    def _rules(self, feats: dict[str, float]) -> tuple[int, list[str]]:
        if not self.breaker.allow():
            return 0, ["RULES_UNAVAILABLE"]
        try:
            resp = self.http.post("/evaluate", json=feats)
            resp.raise_for_status()
            body = resp.json()
            self.breaker.record(True)
            return int(body["score"]), list(body["rules"])
        except (httpx.HTTPError, KeyError, ValueError):
            self.breaker.record(False)
            return 0, ["RULES_UNAVAILABLE"]


def _q(conn, sql: str, params=None):
    """Execute with tuple rows regardless of the connection's default row factory."""
    cur = conn.cursor(row_factory=tuple_row)
    cur.execute(sql, params)
    return cur


def np_safe(o):  # json default for numpy types
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    return str(o)
