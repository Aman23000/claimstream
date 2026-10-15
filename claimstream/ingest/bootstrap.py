"""Create the schema, load real policies, and backfill two years of claim history.

Writes to PostgreSQL (operational store, via COPY) and to a date-partitioned Parquet lake
(bronze layer) that the Spark batch job reads.
"""
from __future__ import annotations

import io
import time

import pandas as pd
import psycopg

from claimstream.config import ROOT, settings
from claimstream.ingest.simulator import SimConfig, load_policies, simulate_claims

HISTORY_START, HISTORY_END = "2024-10-01", "2026-10-01"

POLICY_COLS = ["policy_id", "policy_start", "exposure", "veh_power", "veh_age", "driv_age",
               "bonus_malus", "veh_brand", "veh_gas", "area", "density", "region", "bank_account_hash"]
CLAIM_COLS = ["claim_id", "policy_id", "loss_ts", "reported_ts", "amount", "claim_type",
              "channel", "source", "fraud_label"]


def copy_df(cur, table: str, df: pd.DataFrame, cols: list[str]) -> None:
    buf = io.StringIO()
    df[cols].to_csv(buf, index=False, header=False)
    buf.seek(0)
    with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv)") as cp:
        while chunk := buf.read(1 << 20):
            cp.write(chunk)


def main() -> None:
    t = time.time()
    pol = load_policies(settings.data_dir / "freMTPL2freq.parquet")
    sev = pd.read_parquet(settings.data_dir / "freMTPL2sev.parquet")["ClaimAmount"].to_numpy()
    sev = sev[sev < 200_000]
    claims = simulate_claims(pol, sev, HISTORY_START, HISTORY_END, SimConfig())
    print(f"policies {len(pol):,} | claims {len(claims):,} | fraud rate {claims.fraud_label.mean():.2%}")

    with psycopg.connect(settings.pg_dsn, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS claim_scores, dead_letters, claims, policies, daily_claims, "
                    "forecasts, model_metrics CASCADE")
        cur.execute((ROOT / "sql" / "schema.sql").read_text())
        copy_df(cur, "policies", pol, POLICY_COLS)
        copy_df(cur, "claims", claims, CLAIM_COLS)
        cur.execute((ROOT / "sql" / "reporting_views.sql").read_text())
        cur.execute("ANALYZE")
        conn.commit()

    lake = settings.lake_dir / "bronze" / "claims"
    lake.mkdir(parents=True, exist_ok=True)
    claims.assign(claim_date=claims["reported_ts"].dt.date.astype(str)).to_parquet(
        lake, partition_cols=["claim_date"], index=False,
        coerce_timestamps="us", allow_truncated_timestamps=True)  # Spark reads microseconds
    pol.to_parquet(settings.lake_dir / "bronze" / "policies.parquet", index=False)
    print(f"bootstrap done in {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
