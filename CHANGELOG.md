# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning: [SemVer](https://semver.org/).

## [1.0.0] - 2026-10-14
### Added
- Versioned claim event contract with validation and a dead-letter queue
- Event bus abstraction with Redis Streams (consumer groups, `XAUTOCLAIM` recovery) and Kafka backends
- Multithreaded stream processor: idempotent writes, enrichment with cache-aside, live metrics in Redis, bronze-lake append
- Java rules microservice (zero dependencies, thread-pool HTTP server) with unit tests and a circuit breaker on the caller side
- LightGBM fraud model with an out-of-time split, benchmarked against the rules engine and tracked in MLflow
- PySpark bronze → silver → gold batch job
- Claims-volume forecasting: LSTM (PyTorch) vs SARIMA vs seasonal-naive, rolling-origin back-test, 30-day forecast
- FastAPI service (ingestion, what-if scoring, KPIs, alerts, forecasts, model metrics)
- Streamlit dashboard: live ops, fraud triage, forecast, portfolio, model monitoring, what-if scoring
- Docker / docker-compose (with Kafka KRaft), GitHub Actions CI, Airflow DAGs, macOS setup script
