# Data

## Sources

| Data | Real or simulated | Source |
|---|---|---|
| 677,991 motor policies with rating factors (driver age, vehicle, bonus-malus, region, density) | **Real** | freMTPL2freq, CASdatasets (Dutang & Charpentier) |
| 26,444 claim amounts (the claim-size distribution) | **Real** | freMTPL2sev, CASdatasets |
| Policy start dates, payout account hashes | Simulated | `ingest/simulator.py` |
| Claim timing, type, channel, reporting delay | Simulated, with seasonality and weekday effects | `ingest/simulator.py` |
| Fraud labels | Simulated (≈2.3% of claims) | `ingest/simulator.py` |

No public dataset publishes insurance fraud labels, so the fraud signal is simulated from
red flags that special-investigation units really use:

| Pattern | How it shows up | Honest-claim noise |
|---|---|---|
| Early claim | Loss within about 25 days of policy start | Rare |
| Inflated amount | 3–8× the typical amount for the region | Natural heavy tail |
| Late report | 30–100 extra days before reporting | 3% of honest claims are reported late |
| Fraud ring | 3–6 policies sharing one payout account | About 2,000 families legitimately share accounts |
| Repeat | The same policy claims again 10–60 days later | Normal repeat claims happen |
| Night web submission | Reported 00:00–05:00 through the web | Some honest night reports |

**What this means for the results:** the fraud metrics show that the pipeline, the features and the
evaluation method work. They don't measure real-world fraud detection rates.

## Volumes (default bootstrap)

- 2 years of history (2024-10-01 → 2026-09-30): about 67K claims, about 92 per day, 2.3% fraud
- Live replay pool: about 42K claims, streamed at a configurable rate (`--rate`)
