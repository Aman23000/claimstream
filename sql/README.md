# SQL

| File | Contents |
|---|---|
| `schema.sql` | Tables with primary and foreign keys, `CHECK` constraints (positive amounts, report ≥ loss, valid risk levels) and indexes on the hot query paths (`policy_id, loss_ts`; `reported_ts`; `risk_level, scored_at`; payout-account hash) |
| `reporting_views.sql` | `v_fraud_alerts` (investigator queue) · `v_hourly_kpis` (24-hour rolling average with `AVG() OVER`) · `v_region_summary` (share of cost with `SUM() OVER ()`, `RANK()`) |

Both files are applied by `make bootstrap`.
