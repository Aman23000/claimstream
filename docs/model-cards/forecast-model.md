# Model card: daily claims-volume forecaster

| | |
|---|---|
| **Purpose** | Forecast claims reported per day, 30 days ahead, for adjuster staffing |
| **Candidates** | Seasonal naive (same day last week) · SARIMA(1,0,1)(1,0,1)₇ with month terms · 2-layer LSTM (PyTorch, 28-day lookback, calendar features, early stopping) |
| **Code** | `claimstream/ml/train_forecast.py`, logged to MLflow experiment `claimstream-forecast` |
| **Output** | `forecasts` table: point forecast plus 95% interval per day per model |

## Evaluation
Rolling-origin, one-day-ahead forecasts over the final 60 days (every model scored on identical days).

| Model | MAE | MAPE | RMSE |
|---|---:|---:|---:|
| Seasonal naive | 12.6 | 11.5% | 15.3 |
| **SARIMA** | **8.7** | 8.1% | **11.0** |
| LSTM | 8.8 | **7.9%** | 11.3 |

**Decision:** SARIMA is the default. The LSTM matches it but costs more to train, tune and explain. With
only about 730 daily points and simple weekly seasonality, deep learning has no edge. Both stay in the
pipeline so the comparison re-runs every day.

## Limitations
- Intervals assume the residuals stay stable; holidays and catastrophe events (storms) aren't modelled.
- Volume only, not cost. A severity forecast would be needed for reserving.
