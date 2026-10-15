"""Event-bus abstraction with two interchangeable backends.

* RedisStreamBus - Redis Streams + consumer groups (default; what runs in the local demo)
* KafkaBus       - Apache Kafka via kafka-python (set EVENT_BUS=kafka; see docker-compose.yml)

Both give at-least-once delivery: a message is acknowledged only after it is durably
processed, so a crashed worker's messages are redelivered. The processor's writes are
idempotent (ON CONFLICT DO NOTHING), which makes redelivery safe.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import redis

from claimstream.config import settings

Message = tuple[str, dict[str, Any]]


class EventBus(ABC):
    @abstractmethod
    def publish(self, topic: str, event: dict[str, Any]) -> None: ...

    @abstractmethod
    def consume(self, topic: str, group: str, consumer: str, count: int = 50,
                block_ms: int = 1000) -> list[Message]: ...

    @abstractmethod
    def ack(self, topic: str, group: str, ids: list[str]) -> None: ...

    def lag(self, topic: str, group: str) -> int:  # pragma: no cover - backend specific
        return -1


class RedisStreamBus(EventBus):
    def __init__(self, url: str | None = None, maxlen: int = 500_000):
        self.r = redis.Redis.from_url(url or settings.redis_url, decode_responses=True)
        self.maxlen = maxlen

    def ensure_group(self, topic: str, group: str) -> None:
        try:
            self.r.xgroup_create(topic, group, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def publish(self, topic: str, event: dict[str, Any]) -> None:
        self.r.xadd(topic, {"v": json.dumps(event, default=str)}, maxlen=self.maxlen, approximate=True)

    def consume(self, topic, group, consumer, count=50, block_ms=1000):
        # First reclaim messages another worker took but never acked (crashed > 30s ago).
        _, claimed, _ = self.r.xautoclaim(topic, group, consumer, min_idle_time=30_000, count=count)
        msgs = [(mid, json.loads(f["v"])) for mid, f in claimed if f]
        if len(msgs) < count:
            resp = self.r.xreadgroup(group, consumer, {topic: ">"}, count=count - len(msgs), block=block_ms)
            for _, entries in resp or []:
                msgs += [(mid, json.loads(f["v"])) for mid, f in entries]
        return msgs

    def ack(self, topic, group, ids):
        if ids:
            self.r.xack(topic, group, *ids)

    def lag(self, topic, group) -> int:
        for g in self.r.xinfo_groups(topic):
            if g["name"] == group:
                return int(g.get("lag") or 0) + int(g.get("pending") or 0)
        return 0


class KafkaBus(EventBus):  # pragma: no cover - exercised with docker-compose, not in unit tests
    def __init__(self, bootstrap: str | None = None):
        from kafka import KafkaConsumer, KafkaProducer
        self._consumer_cls = KafkaConsumer
        self.bootstrap = bootstrap or settings.kafka_bootstrap
        self.producer = KafkaProducer(bootstrap_servers=self.bootstrap, acks="all", linger_ms=5,
                                      value_serializer=lambda v: json.dumps(v, default=str).encode())
        self._consumers: dict[tuple[str, str, str], Any] = {}

    def publish(self, topic, event):
        self.producer.send(topic, key=str(event.get("policy_id", "")).encode(), value=event)

    def _consumer(self, topic, group, consumer):
        key = (topic, group, consumer)
        if key not in self._consumers:
            self._consumers[key] = self._consumer_cls(
                topic, bootstrap_servers=self.bootstrap, group_id=group, client_id=consumer,
                enable_auto_commit=False, auto_offset_reset="earliest",
                value_deserializer=lambda b: json.loads(b.decode()))
        return self._consumers[key]

    def consume(self, topic, group, consumer, count=50, block_ms=1000):
        c = self._consumer(topic, group, consumer)
        batch = c.poll(timeout_ms=block_ms, max_records=count)
        return [(f"{r.partition}:{r.offset}", r.value) for recs in batch.values() for r in recs]

    def ack(self, topic, group, ids):
        for (t, g, _), c in self._consumers.items():
            if t == topic and g == group:
                c.commit()


def get_bus() -> EventBus:
    return KafkaBus() if settings.bus == "kafka" else RedisStreamBus()
