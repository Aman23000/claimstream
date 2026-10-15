"""Integration tests against real Redis / PostgreSQL / API. Skipped automatically if services are down.

Start the stack first (`make up` or `scripts/run_local.sh start`), then: pytest -m integration
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import redis

from claimstream.common.bus import RedisStreamBus
from claimstream.config import settings

pytestmark = pytest.mark.integration


def _redis_up() -> bool:
    try:
        return redis.Redis.from_url(settings.redis_url).ping()
    except Exception:
        return False


@pytest.mark.skipif(not _redis_up(), reason="redis not running")
def test_redis_stream_bus_roundtrip_and_ack():
    bus = RedisStreamBus(url=settings.redis_url.rsplit("/", 1)[0] + "/15")
    topic, group = f"test.{uuid.uuid4().hex[:6]}", "g"
    bus.ensure_group(topic, group)
    for i in range(5):
        bus.publish(topic, {"n": i})
    msgs = bus.consume(topic, group, "c1", count=10, block_ms=200)
    assert [m["n"] for _, m in msgs] == list(range(5))
    assert bus.lag(topic, group) == 5          # read but not yet acked -> still pending
    bus.ack(topic, group, [mid for mid, _ in msgs])
    assert bus.lag(topic, group) == 0
    bus.r.delete(topic)


@pytest.fixture(scope="module")
def client():
    try:
        import psycopg
        psycopg.connect(settings.pg_dsn, connect_timeout=2).close()
    except Exception:
        pytest.skip("postgres not running")
    from fastapi.testclient import TestClient
    from claimstream.api.main import app
    with TestClient(app) as c:
        yield c


def test_api_health(client):
    body = client.get("/health").json()
    assert body["postgres"] == "ok" and body["redis"] == "ok"


def test_api_rejects_invalid_claim(client):
    r = client.post("/claims", json={"claim_id": "CLM-bad", "amount": -1})
    assert r.status_code == 422


def test_api_accepts_valid_claim(client):
    now = datetime.now(timezone.utc)
    r = client.post("/claims", json={"claim_id": f"CLM-it-{uuid.uuid4().hex[:8]}", "policy_id": 1,
                                     "loss_ts": (now - timedelta(days=1)).isoformat(), "reported_ts": now.isoformat(),
                                     "amount": 500, "claim_type": "glass", "channel": "app"})
    assert r.status_code == 202 and r.json()["accepted"]


def test_api_score_unknown_policy_is_422(client):
    now = datetime.now(timezone.utc)
    r = client.post("/score", json={"claim_id": "CLM-it-unknown", "policy_id": 987654321,
                                    "loss_ts": (now - timedelta(days=1)).isoformat(), "reported_ts": now.isoformat(),
                                    "amount": 500, "claim_type": "glass", "channel": "app"})
    assert r.status_code == 422


def test_api_kpis_and_forecast_shapes(client):
    assert isinstance(client.get("/kpis/daily", params={"days": 30}).json(), list)
    fc = client.get("/forecast").json()
    assert {"forecast", "backtest"} <= fc.keys()
