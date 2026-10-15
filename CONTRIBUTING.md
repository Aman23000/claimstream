# Contributing

Thanks for taking a look! This is a portfolio project, but issues and pull requests are welcome.

## Development setup
```bash
make install            # Python deps (use a virtualenv, Python 3.11+)
make rules              # build + test the Java rules service (JDK 17+)
make pipeline           # data -> Postgres -> models -> Spark -> forecast
make up                 # run the stack locally
```
macOS users can run `bash scripts/setup_mac.sh --start` to do all of the above.

## Before opening a PR
```bash
pre-commit install      # once
make test               # unit tests
make test-all           # + integration tests (stack must be running)
ruff check claimstream dashboard tests scripts --select E,F,W --ignore E501
```

## Conventions
- **Commits** follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`, `ci:`.
- **Features**: `claimstream/ml/features.py` is the single source of truth for both training and
  serving. If you change it, retrain (`make train`) and keep `test_feature_parity_between_online_and_batch` green.
- **Event contract**: changes to `ClaimEvent` that aren't backward compatible must bump `schema_version`.
- **Config** comes only from environment variables (`claimstream/config.py`). Never hard-code hosts or credentials.
