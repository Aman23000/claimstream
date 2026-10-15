"""Central configuration, read from environment variables (12-factor style)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    pg_dsn: str = os.getenv("PG_DSN", "postgresql://postgres@127.0.0.1:5432/claimstream")
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    bus: str = os.getenv("EVENT_BUS", "redis")            # "redis" (Redis Streams) or "kafka"
    kafka_bootstrap: str = os.getenv("KAFKA_BOOTSTRAP", "127.0.0.1:9092")
    topic: str = os.getenv("CLAIMS_TOPIC", "claims.v1")
    dlq_topic: str = os.getenv("CLAIMS_DLQ_TOPIC", "claims.v1.dlq")
    rules_url: str = os.getenv("RULES_URL", "http://127.0.0.1:8090")
    data_dir: Path = Path(os.getenv("DATA_DIR", ROOT / "data"))
    lake_dir: Path = Path(os.getenv("LAKE_DIR", ROOT / "data" / "lake"))
    model_dir: Path = Path(os.getenv("MODEL_DIR", ROOT / "data" / "models"))
    mlflow_uri: str = os.getenv("MLFLOW_TRACKING_URI", f"sqlite:///{ROOT / 'data' / 'mlflow.db'}")
    high_risk_threshold: float = float(os.getenv("HIGH_RISK_THRESHOLD", "0.60"))


settings = Settings()
