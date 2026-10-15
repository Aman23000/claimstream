"""Daily PySpark batch job: bronze lake (history Parquet + live JSONL) -> silver -> gold aggregates.

Gold outputs:
  * data/lake/gold/daily_claims   (Parquet, partitioned by month)  - analytics / forecasting input
  * Postgres daily_claims table   (upsert)                         - serves the API and dashboard

Runs locally with `python -m claimstream.batch.spark_daily`; on Databricks/EMR only the paths change.
"""
from __future__ import annotations

import time

import psycopg
from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F

from claimstream.config import settings

BRONZE = settings.lake_dir / "bronze"
GOLD = settings.lake_dir / "gold"


def spark() -> SparkSession:
    s = (SparkSession.builder.master("local[*]").appName("claimstream-daily")
         .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "8")
         .config("spark.sql.session.timeZone", "UTC").getOrCreate())
    s.sparkContext.setLogLevel("ERROR")
    return s


def main() -> None:
    t = time.time()
    s = spark()
    cols = ["claim_id", "policy_id", "loss_ts", "reported_ts", "amount", "claim_type", "channel", "fraud_label"]
    hist = s.read.parquet(str(BRONZE / "claims")).select(*cols)
    live_path = BRONZE / "claims_live"
    claims = hist
    if live_path.exists() and any(live_path.rglob("*.jsonl")):
        live = (s.read.json(str(live_path))
                .withColumn("loss_ts", F.to_timestamp("loss_ts"))
                .withColumn("reported_ts", F.to_timestamp("reported_ts"))
                .select(*cols))
        claims = hist.unionByName(live)

    policies = s.read.parquet(str(BRONZE / "policies.parquet")).select("policy_id", "region")

    # ---------- silver: dedupe on claim_id (at-least-once delivery can duplicate), enforce types
    w = Window.partitionBy("claim_id").orderBy(F.col("reported_ts").desc())
    silver = (claims.withColumn("rn", F.row_number().over(w)).filter("rn = 1").drop("rn")
              .filter(F.col("amount") > 0)
              .join(F.broadcast(policies), "policy_id", "left")
              .withColumn("claim_date", F.to_date("reported_ts")))

    # ---------- gold: daily by region with 7-day rolling mean
    daily = (silver.groupBy("claim_date", "region")
             .agg(F.count("*").alias("n_claims"),
                  F.round(F.sum("amount"), 2).alias("total_amount"),
                  F.round(F.avg("amount"), 2).alias("avg_amount"),
                  F.round(F.avg(F.col("fraud_label").cast("double")), 4).alias("fraud_rate")))
    roll = Window.partitionBy("region").orderBy("claim_date").rowsBetween(-6, 0)
    daily = daily.withColumn("n_claims_7d_avg", F.round(F.avg("n_claims").over(roll), 2))

    (daily.withColumn("month", F.date_format("claim_date", "yyyy-MM"))
     .write.mode("overwrite").partitionBy("month").parquet(str(GOLD / "daily_claims")))

    rows = daily.select("claim_date", "region", "n_claims", "total_amount", "avg_amount", "fraud_rate").collect()
    with psycopg.connect(settings.pg_dsn) as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO daily_claims VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (claim_date, region) DO UPDATE "
            "SET n_claims=EXCLUDED.n_claims, total_amount=EXCLUDED.total_amount, "
            "avg_amount=EXCLUDED.avg_amount, fraud_rate=EXCLUDED.fraud_rate",
            [tuple(r) for r in rows])
    print(f"silver claims={silver.count():,} | gold rows={len(rows):,} | {time.time() - t:.0f}s")
    s.stop()


if __name__ == "__main__":
    main()
