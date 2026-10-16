# `claimstream` Python package

| Module | Role |
|---|---|
| `config.py` | All settings from environment variables |
| `common/events.py` | `ClaimEvent` v1 contract (Pydantic) |
| `common/bus.py` | `EventBus` interface → `RedisStreamBus`, `KafkaBus` |
| `ingest/download.py` | Fetch freMTPL2 → Parquet |
| `ingest/simulator.py` | Claim timing, channels and fraud patterns on real policies |
| `ingest/bootstrap.py` | Schema + `COPY` load + bronze Parquet lake |
| `stream/producer.py` | Live load generator (rate, burstiness, malformed share) |
| `stream/processor.py` | Consumer-group workers: validate → persist → score → metrics → ack |
| `stream/scoring.py` | Enrichment (cache-aside), model, rules client, circuit breaker |
| `batch/spark_daily.py` | PySpark bronze → silver → gold |
| `ml/features.py` | **Single** feature definition for training and serving |
| `ml/train_fraud.py` | Out-of-time fraud model + rules benchmark + MLflow |
| `ml/train_forecast.py` | Seasonal naive vs SARIMA vs LSTM |
| `api/main.py` | FastAPI app |

Each module is runnable: `python -m claimstream.<package>.<module>`.
