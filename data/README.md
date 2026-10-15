# data/

Generated at runtime and git-ignored, apart from this file.

| Path | Created by | Contents |
|---|---|---|
| `freMTPL2freq.parquet`, `freMTPL2sev.parquet` | `make data` | Real policy and claim-amount data (CASdatasets) |
| `lake/bronze/` | `make bootstrap`, stream processor | Raw claims (Parquet history, JSONL live) and the policy snapshot |
| `lake/gold/` | `make batch` | Daily aggregates (Parquet, partitioned by month) |
| `models/` | `make train`, `make forecast` | Fraud model bundle, LSTM weights, metrics, back-test |
| `mlflow.db` | training jobs | MLflow tracking store (`mlflow ui --backend-store-uri sqlite:///data/mlflow.db`) |
