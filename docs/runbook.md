# Operations runbook

## Processes (local mode)
| Process | Port | Log | Started by |
|---|---|---|---|
| Rules service (Java) | 8090 | `.run/rules.log` | `make up` |
| Stream processor | — | `.run/processor.log` | `make up` |
| API (uvicorn) | 8000 | `.run/api.log` | `make up` |
| Producer (load generator) | — | `.run/producer.log` | `make up` |
| Dashboard (Streamlit) | 8501 | `.run/dashboard.log` | `make up` |
| PostgreSQL / Redis | 5432 / 6379 | system | Homebrew / systemd / Docker |

PIDs live in `.run/*.pid`. `make stop` stops everything that `make up` started.

## Health checks
```bash
curl -s localhost:8000/health              # {"postgres":"ok","redis":"ok","rules_service":"ok","status":"ok"}
tail -3 .run/processor.log                 # processed=… rate=…/s high=… dlq=… lag=…
redis-cli XINFO GROUPS claims.v1           # consumer group lag + pending
psql -U postgres -d claimstream -c "SELECT risk_level, COUNT(*) FROM claim_scores GROUP BY 1"
```

## Incidents
| Symptom | Likely cause | Action |
|---|---|---|
| `lag` keeps growing | Processor slower than producer | Add workers (`WORKERS=8 make up`) or lower `RATE` |
| Many `RULES_UNAVAILABLE` tags | Rules service down; circuit breaker open | `tail .run/rules.log`; restart with `make stop && make up`. Scoring continues on the model alone |
| `dead_letters` growing fast | Upstream sending bad events | `SELECT error, COUNT(*) FROM dead_letters GROUP BY 1` to find which field breaks the contract |
| Dashboard: "API not reachable" | API process died | `tail .run/api.log`; check Postgres is up |
| Scoring errors after a schema change | Stale policy cache | `redis-cli --scan --pattern 'cs:policy:*' \| xargs redis-cli del` |
| Alert rate jumps suddenly | Score drift or a new fraud pattern | Models tab → score distribution; retrain with `make train` |

## Routine jobs
| Job | Schedule (Airflow) | Manual |
|---|---|---|
| Spark daily aggregates | daily 02:00 UTC | `make batch` |
| Forecast retrain | daily, after the Spark job | `make forecast` |
| Fraud model retrain | weekly, Sunday 03:00 UTC | `make train` (rules service must be up) |

## Full reset
```bash
make stop
redis-cli FLUSHDB
rm -rf data/lake data/models data/mlflow.db
make pipeline && make up
```
