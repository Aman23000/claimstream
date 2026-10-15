# ADR 0003: Validate models out-of-time, not with random splits

**Status:** accepted

## Context
In production, a model always scores claims from the future. A random train/test split leaks future
patterns (seasonality, drift, repeat claims on the same policy) into training and overstates performance.

## Decision
- **Fraud:** train on claims reported before 2026-06-01, test on later claims. The operating threshold is
  chosen on that test window, and the served model is refit on all history.
- **Forecasting:** rolling-origin, one-day-ahead back-test over the last 60 days. Every model, including
  the seasonal-naive baseline, is scored on exactly the same days.

## Consequences
The reported numbers are lower than a random split would give, and closer to what production would see.
This is also how we learned the LSTM doesn't beat SARIMA on this data, and that result is reported.
