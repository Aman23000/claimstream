# Getting started

## Option 1: macOS, one command
```bash
git clone https://github.com/Aman23000/claimstream.git && cd claimstream
bash scripts/setup_mac.sh --start
```
The script installs Homebrew packages (Python 3.12, Java 21, PostgreSQL 16, Redis, libomp), starts the
database and Redis, builds a virtualenv, builds and tests the Java service, runs the data/ML pipeline, runs
the tests and starts the stack. It is idempotent: if anything fails, fix it and run it again.

> Homebrew itself needs your password to install, so install it first: https://brew.sh

## Option 2: Linux or macOS, manual
| Requirement | Version | Check |
|---|---|---|
| Python | 3.11+ | `python3 --version` |
| Java (JDK) | 17+ | `java -version` |
| PostgreSQL | 14+ (tested on 16) | `psql --version` |
| Redis | 6.2+ (tested on 7) | `redis-cli ping` |

```bash
python3 -m venv .venv && source .venv/bin/activate
make install                                   # Python dependencies
createdb claimstream                           # connection settings: .env.example
make rules                                     # build + test the Java rules service
java -jar rules-service/rules-service.jar &    # needed while training (rules baseline)
make pipeline                                  # download → DB → fraud model → Spark → forecast
kill %1                                        # stop the temporary rules service
make up                                        # start the full stack
```

## Option 3: Docker
```bash
make docker-up        # postgres, redis, kafka, rules, bootstrap job, processor, producer, api, dashboard
make docker-down
```

## Open it
| What | URL |
|---|---|
| Dashboard | http://localhost:8501 |
| API docs (OpenAPI) | http://localhost:8000/docs |
| Rules service health | http://localhost:8090/health |
| MLflow UI | `mlflow ui --backend-store-uri sqlite:///data/mlflow.db` → http://localhost:5000 |

## Day-to-day
```bash
make up       # start           make stop     # stop
make test     # unit tests      make test-all # + integration (stack running)
make help     # every target
```
