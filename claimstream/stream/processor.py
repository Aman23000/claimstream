"""Multithreaded stream processor (consumer group).

Each worker thread: read a batch -> validate -> persist claim (idempotent) -> score -> persist
score -> update live metrics in Redis -> append to the bronze lake -> ACK. Invalid events go to a
dead-letter table + DLQ topic instead of blocking the stream.

Run:  python -m claimstream.stream.processor --workers 4
"""
from __future__ import annotations

import argparse
import json
import signal
import threading
import time
from datetime import datetime, timezone

import psycopg
import redis
from pydantic import ValidationError

from claimstream.common.bus import get_bus
from claimstream.common.events import ClaimEvent
from claimstream.config import settings
from claimstream.stream.scoring import Scorer, np_safe

GROUP = "claims-processor"
STOP = threading.Event()
STATS = {"processed": 0, "dead_letters": 0, "high": 0}
STATS_LOCK = threading.Lock()


def record_metrics(r: redis.Redis, ev: ClaimEvent, s: dict) -> None:
    minute = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    pipe = r.pipeline(transaction=False)
    for key, val in ((f"cs:m:claims:{minute}", 1), (f"cs:m:high:{minute}", int(s["risk_level"] == "HIGH"))):
        pipe.incrby(key, val)
        pipe.expire(key, 172800)
    pipe.incrbyfloat(f"cs:m:amount:{minute}", ev.amount)
    pipe.expire(f"cs:m:amount:{minute}", 172800)
    pipe.hincrby("cs:totals", "claims", 1)
    pipe.hincrbyfloat("cs:totals", "amount", ev.amount)
    pipe.hincrby("cs:totals", f"risk_{s['risk_level']}", 1)
    pipe.hincrby("cs:region_live", s["region"], 1)
    pipe.lpush("cs:latency_ms", s["latency_ms"])
    pipe.ltrim("cs:latency_ms", 0, 999)
    if s["risk_level"] == "HIGH":
        alert = {**s, "amount": ev.amount, "policy_id": ev.policy_id, "claim_type": ev.claim_type,
                 "channel": ev.channel, "reported_ts": ev.reported_ts.isoformat()}
        pipe.lpush("cs:alerts", json.dumps(alert, default=np_safe))
        pipe.ltrim("cs:alerts", 0, 199)
    pipe.execute()


def append_bronze(worker: str, events: list[dict]) -> None:
    if not events:
        return
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = settings.lake_dir / "bronze" / "claims_live" / f"claim_date={day}"
    path.mkdir(parents=True, exist_ok=True)
    with open(path / f"part-{worker}.jsonl", "a") as fh:
        for e in events:
            fh.write(json.dumps(e, default=str) + "\n")


def worker_loop(name: str, scorer: Scorer) -> None:
    bus = get_bus()
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    with psycopg.connect(settings.pg_dsn, autocommit=False) as conn:
        while not STOP.is_set():
            batch = bus.consume(settings.topic, GROUP, name, count=50, block_ms=1000)
            if not batch:
                continue
            ok_ids, bronze = [], []
            for msg_id, payload in batch:
                try:
                    ev = ClaimEvent.model_validate(payload)
                except ValidationError as e:
                    dead_letter(conn, bus, payload, e.errors(include_url=False))
                    ok_ids.append(msg_id)
                    continue
                try:
                    with conn.transaction():
                        cur = conn.execute(
                            "INSERT INTO claims (claim_id, policy_id, loss_ts, reported_ts, amount, claim_type,"
                            " channel, source, fraud_label) VALUES (%s,%s,%s,%s,%s,%s,%s,'live',%s)"
                            " ON CONFLICT (claim_id) DO NOTHING",
                            (ev.claim_id, ev.policy_id, ev.loss_ts, ev.reported_ts, ev.amount,
                             ev.claim_type, ev.channel, ev.fraud_label))
                        if cur.rowcount == 0:          # duplicate delivery -> already processed
                            ok_ids.append(msg_id)
                            continue
                        s = scorer.score(conn, ev)
                        conn.execute(
                            "INSERT INTO claim_scores (claim_id, model_score, rule_score, rules_hit, risk_level,"
                            " model_version, latency_ms) VALUES (%s,%s,%s,%s,%s,%s,%s)"
                            " ON CONFLICT (claim_id) DO NOTHING",
                            (s["claim_id"], s["model_score"], s["rule_score"], s["rules_hit"],
                             s["risk_level"], s["model_version"], s["latency_ms"]))
                    record_metrics(r, ev, s)
                    bronze.append({**payload, "risk_level": s["risk_level"], "model_score": s["model_score"]})
                    ok_ids.append(msg_id)
                    with STATS_LOCK:
                        STATS["processed"] += 1
                        STATS["high"] += s["risk_level"] == "HIGH"
                except ValueError as e:                # e.g. unknown policy -> business-rule failure
                    dead_letter(conn, bus, payload, str(e))
                    ok_ids.append(msg_id)
                # Other exceptions propagate: the message is NOT acked and will be redelivered.
            append_bronze(name, bronze)
            bus.ack(settings.topic, GROUP, ok_ids)


def dead_letter(conn, bus, payload, error) -> None:
    conn.execute("INSERT INTO dead_letters (payload, error) VALUES (%s, %s)",
                 (json.dumps(payload, default=str), json.dumps(error, default=str)))
    conn.commit()
    bus.publish(settings.dlq_topic, {"payload": payload, "error": str(error)})
    with STATS_LOCK:
        STATS["dead_letters"] += 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    bus = get_bus()
    if hasattr(bus, "ensure_group"):
        bus.ensure_group(settings.topic, GROUP)
    scorer = Scorer()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: STOP.set())
    threads = [threading.Thread(target=worker_loop, args=(f"w{i}", scorer), daemon=True)
               for i in range(args.workers)]
    for t in threads:
        t.start()
    print(f"processor started: {args.workers} workers, model {scorer.version}", flush=True)
    last, t_last = 0, time.time()
    while not STOP.is_set():
        time.sleep(10)
        with STATS_LOCK:
            done = STATS["processed"]
        rate = (done - last) / (time.time() - t_last)
        last, t_last = done, time.time()
        print(f"processed={done} rate={rate:.1f}/s high={STATS['high']} dlq={STATS['dead_letters']} "
              f"lag={bus.lag(settings.topic, GROUP)}", flush=True)
    for t in threads:
        t.join(timeout=5)


if __name__ == "__main__":
    main()
