# Rules service (Java 21)

A deterministic, auditable fraud-rules engine served over HTTP. It has zero external dependencies:
the JDK `HttpServer`, a fixed thread pool and a small JSON parser.

| Rule | Condition | Points |
|---|---|---:|
| `EARLY_CLAIM` | loss within 30 days of policy start | 30 |
| `HIGH_AMOUNT_FOR_REGION` | amount > 4× the regional median | 25 |
| `MULTIPLE_RECENT_CLAIMS` / `RECENT_PRIOR_CLAIM` | ≥ 2 / 1 prior claims in 90 days | 30 / 15 |
| `LATE_REPORTING` | reported more than 30 days after the loss | 15 |
| `SHARED_PAYOUT_ACCOUNT` | ≥ 3 policies share the payout account | 30 |
| `NIGHT_WEB_SUBMISSION` | web submission between 00:00 and 05:00 | 10 |

The score is capped at 100.

```bash
make rules                                   # compile + run tests + package the jar
java -jar rules-service/rules-service.jar    # PORT=8090 THREADS=8 by default
curl -X POST localhost:8090/evaluate -d '{"days_since_policy_start":5,"log_amount_vs_region":1.8,
  "policy_claims_90d":0,"report_delay_days":3,"shared_bank_policies":4,"report_hour_night":1,"channel_web":1}'
# {"score":95,"rules":["EARLY_CLAIM","HIGH_AMOUNT_FOR_REGION","SHARED_PAYOUT_ACCOUNT","NIGHT_WEB_SUBMISSION"]}
```
Docker: `docker build -t claimstream-rules .`. The multi-stage build runs the tests before packaging.
