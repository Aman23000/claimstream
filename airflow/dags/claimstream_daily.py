"""Airflow orchestration for the batch side of ClaimStream.

daily  02:00 UTC : Spark bronze->gold aggregation, then re-forecast claims volume
weekly Sun 03:00 : retrain the fraud model (out-of-time validated) and log it to MLflow

The streaming side (processor) runs continuously and is not scheduled by Airflow.
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

PROJECT = "/opt/claimstream"
DEFAULTS = {"owner": "data-eng", "retries": 2, "retry_delay": timedelta(minutes=10),
            "execution_timeout": timedelta(hours=1)}

with DAG("claimstream_daily", start_date=datetime(2026, 10, 1), schedule="0 2 * * *",
         catchup=False, default_args=DEFAULTS, tags=["claimstream"]) as daily:
    spark_gold = BashOperator(task_id="spark_daily_aggregates",
                              bash_command=f"cd {PROJECT} && python -m claimstream.batch.spark_daily")
    forecast = BashOperator(task_id="retrain_forecast",
                            bash_command=f"cd {PROJECT} && python -m claimstream.ml.train_forecast")
    spark_gold >> forecast

with DAG("claimstream_weekly_model", start_date=datetime(2026, 10, 1), schedule="0 3 * * 0",
         catchup=False, default_args=DEFAULTS, tags=["claimstream", "ml"]) as weekly:
    BashOperator(task_id="retrain_fraud_model",
                 bash_command=f"cd {PROJECT} && python -m claimstream.ml.train_fraud")
