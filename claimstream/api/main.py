"""ClaimStream REST API (FastAPI).

Run:  uvicorn claimstream.api.main:app --port 8000      Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import json
import statistics
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd
import redis
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from claimstream.common.bus import get_bus
from claimstream.common.events import ClaimEvent
from claimstream.config import settings

STATE: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    STATE["pool"] = ConnectionPool(settings.pg_dsn, min_size=1, max_size=8, kwargs={"row_factory": dict_row})
    STATE["redis"] = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    STATE["bus"] = get_bus()
    yield
    STATE["pool"].close()


app = FastAPI(title="ClaimStream API", version="1.0.0", lifespan=lifespan,
              description="Real-time insurance claims intelligence: ingestion, fraud scoring, KPIs, forecasts.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])


def db():
    with STATE["pool"].connection() as conn:
        yield conn


def rds() -> redis.Redis:
    return STATE["redis"]


def jsonable(rows):
    return json.loads(json.dumps(rows, default=str))


@app.get("/health", tags=["ops"])
def health(conn=Depends(db), r=Depends(rds)):
    status = {"postgres": "ok", "redis": "ok", "rules_service": "ok"}
    try:
        conn.execute("SELECT 1")
    except Exception as e:  # pragma: no cover
        status["postgres"] = f"error: {e}"
    try:
        r.ping()
    except Exception as e:  # pragma: no cover
        status["redis"] = f"error: {e}"
    try:
        httpx.get(f"{settings.rules_url}/health", timeout=1).raise_for_status()
    except Exception:
        status["rules_service"] = "unavailable"
    status["status"] = "ok" if all(v == "ok" for v in status.values()) else "degraded"
    return status


@app.post("/claims", status_code=202, tags=["ingestion"])
def submit_claim(event: ClaimEvent):
    """Validate a claim event and publish it to the stream. Scoring happens asynchronously."""
    STATE["bus"].publish(settings.topic, json.loads(event.model_dump_json()))
    return {"accepted": True, "claim_id": event.claim_id}


@app.get("/claims/{claim_id}", tags=["claims"])
def get_claim(claim_id: str, conn=Depends(db)):
    row = conn.execute(
        "SELECT c.*, s.model_score, s.rule_score, s.rules_hit, s.risk_level, s.model_version, s.latency_ms, "
        "p.region, p.driv_age, p.bonus_malus, p.policy_start FROM claims c "
        "LEFT JOIN claim_scores s USING (claim_id) JOIN policies p USING (policy_id) WHERE c.claim_id=%s",
        (claim_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "claim not found")
    return jsonable(row)


@app.get("/metrics/live", tags=["kpis"])
def live_metrics(minutes: int = Query(60, ge=5, le=1440), r=Depends(rds)):
    """Per-minute throughput, amount and high-risk counts from Redis, plus latency percentiles."""
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    keys = [(now - timedelta(minutes=i)).strftime("%Y%m%d%H%M") for i in range(minutes - 1, -1, -1)]
    pipe = r.pipeline()
    for k in keys:
        pipe.get(f"cs:m:claims:{k}")
        pipe.get(f"cs:m:amount:{k}")
        pipe.get(f"cs:m:high:{k}")
    vals = pipe.execute()
    series = [{"minute": datetime.strptime(k, "%Y%m%d%H%M").replace(tzinfo=timezone.utc).isoformat(),
               "claims": int(vals[3 * i] or 0), "amount": float(vals[3 * i + 1] or 0),
               "high_risk": int(vals[3 * i + 2] or 0)} for i, k in enumerate(keys)]
    lat = [float(x) for x in r.lrange("cs:latency_ms", 0, -1)]
    totals = r.hgetall("cs:totals")
    lag = STATE["bus"].lag(settings.topic, "claims-processor") if r.exists(settings.topic) else 0
    return {
        "series": series,
        "totals": {k: float(v) for k, v in totals.items()},
        "latency_ms": {"p50": statistics.median(lat) if lat else None,
                       "p95": statistics.quantiles(lat, n=20)[18] if len(lat) >= 20 else None},
        "consumer_lag": lag,
        "regions_live": {k: int(v) for k, v in r.hgetall("cs:region_live").items()},
    }


@app.get("/alerts", tags=["fraud"])
def alerts(limit: int = Query(50, ge=1, le=200), r=Depends(rds), conn=Depends(db)):
    live = [json.loads(a) for a in r.lrange("cs:alerts", 0, limit - 1)]
    if live:
        return {"source": "live", "alerts": live}
    rows = conn.execute("SELECT * FROM v_fraud_alerts ORDER BY scored_at DESC LIMIT %s", (limit,)).fetchall()
    return {"source": "database", "alerts": jsonable(rows)}


@app.get("/kpis/daily", tags=["kpis"])
def daily(days: int = Query(120, ge=7, le=800), conn=Depends(db)):
    rows = conn.execute(
        "SELECT claim_date, SUM(n_claims) AS n_claims, SUM(total_amount) AS total_amount, "
        "SUM(total_amount)/NULLIF(SUM(n_claims),0) AS avg_amount, "
        "SUM(fraud_rate*n_claims)/NULLIF(SUM(n_claims),0) AS fraud_rate "
        "FROM daily_claims, (SELECT MAX(reported_ts)::date AS last_day FROM claims WHERE source='history') h "
        # Historical book only: the live demo replays at accelerated speed, so its daily totals aren't real volumes.
        "WHERE claim_date <= h.last_day AND claim_date >= h.last_day - %s "
        "GROUP BY claim_date ORDER BY claim_date", (days,)).fetchall()
    return jsonable(rows)


@app.get("/regions", tags=["kpis"])
def regions(conn=Depends(db)):
    return jsonable(conn.execute("SELECT * FROM v_region_summary ORDER BY cost_rank").fetchall())


@app.get("/forecast", tags=["forecasting"])
def forecast(conn=Depends(db)):
    fc = conn.execute("SELECT forecast_date, model, yhat, yhat_lo, yhat_hi FROM forecasts ORDER BY 1, 2").fetchall()
    bt_path = settings.model_dir / "forecast_backtest.csv"
    backtest = pd.read_csv(bt_path).to_dict("records") if bt_path.exists() else []
    return {"forecast": jsonable(fc), "backtest": backtest}


@app.get("/models", tags=["models"])
def models(conn=Depends(db)):
    rows = conn.execute("SELECT model_name, version, metric, value FROM model_metrics ORDER BY 1, 2, 3").fetchall()
    out: dict = {}
    for row in rows:
        out.setdefault(row["model_name"], {}).setdefault(row["version"], {})[row["metric"]] = row["value"]
    risk = conn.execute(
        "SELECT risk_level, COUNT(*) AS n, AVG(model_score) AS avg_score, "
        "AVG(c.fraud_label::int) AS observed_fraud_rate FROM claim_scores s JOIN claims c USING (claim_id) "
        "GROUP BY risk_level").fetchall()
    hist = conn.execute(
        "SELECT width_bucket(model_score, 0, 1, 20) AS bucket, COUNT(*) AS n FROM claim_scores GROUP BY 1 ORDER BY 1"
    ).fetchall()
    fm = settings.model_dir / "fraud_metrics.json"
    importance = json.loads(fm.read_text()).get("importance", {}) if fm.exists() else {}
    return {"metrics": out, "live_risk_mix": jsonable(risk), "score_histogram": jsonable(hist),
            "fraud_feature_importance": importance}


@app.post("/score", tags=["fraud"])
def score_now(event: ClaimEvent, conn=Depends(db)):
    """Score a claim synchronously WITHOUT persisting it (what-if analysis for investigators)."""
    from claimstream.stream.scoring import Scorer
    if "scorer" not in STATE:
        STATE["scorer"] = Scorer(STATE["redis"])
    try:
        return STATE["scorer"].score(conn, event)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
