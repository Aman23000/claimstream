# Testing

| Layer | Suite | What it proves | Needs |
|---|---|---|---|
| Unit | `tests/test_core.py` | Event contract accepts valid and rejects 8 kinds of invalid events · online and batch features are identical (no training/serving skew) · simulator invariants (time window, unique IDs, fraud rate, report ≥ loss) · circuit breaker opens and recovers | nothing |
| Unit (Java) | `rules-service/src/test/…/RulesEngineTest.java` | Each rule fires correctly, scores stack and cap at 100, missing fields are rejected, JSON round-trips | JDK |
| Integration | `tests/test_integration.py` | Redis Streams publish → consume → lag → ack · API health, validation (422), ingestion (202), unknown policy, KPI and forecast shapes | Postgres, Redis, a trained model |
| End to end | CI `pipeline` step | Real data download → Postgres → fraud model → Spark → forecast all succeed | CI service containers |

```bash
make test        # unit
make test-all    # unit + integration (run `make up` first)
make rules       # Java
```
Integration tests **skip themselves**, with a clear reason, when Redis or Postgres isn't reachable, so `pytest`
never fails just because services are down.
