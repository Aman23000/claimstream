"""Live claim producer: replays simulated claims as if they were being reported right now.

Run:  python -m claimstream.stream.producer --rate 5 --malformed 0.005
"""
from __future__ import annotations

import argparse
import random
import time
from datetime import datetime, timezone

import pandas as pd

from claimstream.common.bus import get_bus
from claimstream.config import settings
from claimstream.ingest.simulator import SimConfig, simulate_claims


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, default=5.0, help="events per second")
    ap.add_argument("--limit", type=int, default=0, help="stop after N events (0 = run forever)")
    ap.add_argument("--malformed", type=float, default=0.005, help="share of bad events (exercise DLQ)")
    ap.add_argument("--seed", type=int, default=99)
    args = ap.parse_args()

    pol = pd.read_parquet(settings.lake_dir / "bronze" / "policies.parquet")
    sev = pd.read_parquet(settings.data_dir / "freMTPL2sev.parquet")["ClaimAmount"].to_numpy()
    pool = simulate_claims(pol, sev[sev < 200_000], "2026-10-01", "2027-10-01",
                           SimConfig(seed=args.seed), source="live").sample(frac=1, random_state=args.seed)
    bus, rng, sent = get_bus(), random.Random(args.seed), 0
    print(f"producer: {len(pool):,} events in pool, {args.rate}/s -> {settings.topic}", flush=True)
    interval = 1.0 / args.rate
    for row in pool.itertuples(index=False):
        now = datetime.now(timezone.utc)
        # Re-date the simulated claim to today but keep its time-of-day and reporting delay,
        # so behavioural signals (night submissions, late reports) survive the replay.
        orig = row.reported_ts
        reported = now.replace(hour=orig.hour, minute=orig.minute, second=orig.second, microsecond=0)
        if reported > now:
            reported -= pd.Timedelta(days=1)
        delay = row.reported_ts - row.loss_ts
        ev = {"schema_version": 1, "claim_id": row.claim_id, "policy_id": int(row.policy_id),
              "loss_ts": (reported - delay).isoformat(), "reported_ts": reported.isoformat(),
              "amount": float(row.amount), "claim_type": row.claim_type, "channel": row.channel,
              "fraud_label": bool(row.fraud_label)}
        if rng.random() < args.malformed:
            ev[rng.choice(["amount", "claim_type", "reported_ts"])] = rng.choice([-50, "spaceship", None])
        bus.publish(settings.topic, ev)
        sent += 1
        if args.limit and sent >= args.limit:
            break
        time.sleep(interval * rng.uniform(0.3, 1.7))   # bursty, not perfectly regular
    print(f"producer: sent {sent}", flush=True)


if __name__ == "__main__":
    main()
