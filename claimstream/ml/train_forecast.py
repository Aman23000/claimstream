"""Daily claims-volume forecasting: LSTM (PyTorch) vs SARIMA vs seasonal-naive baseline.

Why it matters: claims volume drives adjuster staffing and reserves. A model only earns its
complexity if it beats the simple baseline, so every model is scored on the same 60-day
hold-out with one-day-ahead (rolling-origin) forecasts.
"""
from __future__ import annotations

import json
import time
import warnings

import mlflow
import numpy as np
import pandas as pd
import psycopg
import torch
from statsmodels.tsa.statespace.sarimax import SARIMAX
from torch import nn

from claimstream.config import settings

warnings.filterwarnings("ignore")
torch.manual_seed(3)
np.random.seed(3)
LOOKBACK, TEST_DAYS, HORIZON = 28, 60, 30


def load_series() -> pd.Series:
    with psycopg.connect(settings.pg_dsn) as conn:
        rows = conn.execute("SELECT reported_ts::date AS d, COUNT(*) FROM claims WHERE source='history' "
                            "GROUP BY 1 ORDER BY 1").fetchall()
    s = pd.Series({pd.Timestamp(d): n for d, n in rows}, dtype=float).asfreq("D", fill_value=0.0)
    return s


def calendar(idx: pd.DatetimeIndex) -> np.ndarray:
    dow = np.eye(7)[idx.dayofweek]
    m = 2 * np.pi * idx.month / 12
    return np.column_stack([dow, np.sin(m), np.cos(m)])


class LSTMForecaster(nn.Module):
    def __init__(self, n_in: int, hidden: int = 48):
        super().__init__()
        self.lstm = nn.LSTM(n_in, hidden, num_layers=2, batch_first=True, dropout=0.1)
        self.head = nn.Sequential(nn.Linear(hidden + 9, 32), nn.ReLU(), nn.Linear(32, 1))

    def forward(self, seq, target_cal):
        out, _ = self.lstm(seq)
        return self.head(torch.cat([out[:, -1], target_cal], dim=1)).squeeze(1)


def make_windows(y_scaled: np.ndarray, cal: np.ndarray, start: int, end: int):
    X, C, Y = [], [], []
    for t in range(max(start, LOOKBACK), end):
        X.append(np.column_stack([y_scaled[t - LOOKBACK:t], cal[t - LOOKBACK:t]]))
        C.append(cal[t])
        Y.append(y_scaled[t])
    return (torch.tensor(np.array(X), dtype=torch.float32), torch.tensor(np.array(C), dtype=torch.float32),
            torch.tensor(np.array(Y), dtype=torch.float32))


def fit_lstm(y: np.ndarray, cal: np.ndarray, train_end: int, epochs: int = 120):
    mu, sd = y[:train_end].mean(), y[:train_end].std()
    ys = (y - mu) / sd
    X, C, Y = make_windows(ys, cal, 0, train_end)
    n_val = 45
    model = LSTMForecaster(n_in=1 + cal.shape[1])
    opt = torch.optim.Adam(model.parameters(), lr=3e-3, weight_decay=1e-5)
    best, best_state, patience = np.inf, None, 0
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(len(X) - n_val)
        for i in range(0, len(perm), 32):
            b = perm[i:i + 32]
            opt.zero_grad()
            loss = nn.functional.mse_loss(model(X[b], C[b]), Y[b])
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            v = nn.functional.mse_loss(model(X[-n_val:], C[-n_val:]), Y[-n_val:]).item()
        if v < best - 1e-4:
            best, best_state, patience = v, {k: t.clone() for k, t in model.state_dict().items()}, 0
        else:
            patience += 1
            if patience >= 15:            # early stopping on the validation window
                break
    model.load_state_dict(best_state)
    return model, mu, sd, ep + 1


def lstm_predict(model, y, cal, mu, sd, start, end) -> np.ndarray:
    X, C, _ = make_windows((y - mu) / sd, cal, start, end)
    model.eval()
    with torch.no_grad():
        return model(X, C).numpy() * sd + mu


def metrics(y, p) -> dict:
    return {"mae": float(np.mean(np.abs(y - p))), "mape": float(np.mean(np.abs(y - p) / np.maximum(y, 1)) * 100),
            "rmse": float(np.sqrt(np.mean((y - p) ** 2)))}


def main() -> None:
    t0 = time.time()
    s = load_series()
    y, idx = s.to_numpy(), s.index
    cal = calendar(idx)
    n_tr = len(y) - TEST_DAYS
    y_te = y[n_tr:]
    res: dict[str, dict] = {}

    res["seasonal_naive"] = metrics(y_te, y[n_tr - 7:len(y) - 7])

    exog = cal[:, 7:]
    sar = SARIMAX(y[:n_tr], exog=exog[:n_tr], order=(1, 0, 1), seasonal_order=(1, 0, 1, 7),
                  trend="c").fit(disp=False)
    sar_full = sar.apply(y, exog=exog)                     # same params, all data -> 1-step forecasts
    p_sar = sar_full.get_prediction(start=n_tr, end=len(y) - 1).predicted_mean
    res["sarima"] = metrics(y_te, p_sar)

    model, mu, sd, epochs = fit_lstm(y, cal, n_tr)
    p_lstm = lstm_predict(model, y, cal, mu, sd, n_tr, len(y))
    res["lstm"] = {**metrics(y_te, p_lstm), "epochs": epochs}

    best = min(("sarima", "lstm", "seasonal_naive"), key=lambda k: res[k]["mae"])
    print(json.dumps(res, indent=2), "\nbest:", best)

    # ---- 30-day forecast from the end of history (recursive), with 95% intervals
    fut_idx = pd.date_range(idx[-1] + pd.Timedelta(days=1), periods=HORIZON, freq="D")
    fut_cal = calendar(fut_idx)
    sar_all = SARIMAX(y, exog=exog, order=(1, 0, 1), seasonal_order=(1, 0, 1, 7), trend="c").fit(disp=False)
    fc = sar_all.get_forecast(HORIZON, exog=fut_cal[:, 7:])
    sar_mean, sar_ci = fc.predicted_mean, fc.conf_int(alpha=0.05)

    lstm_resid_sd = float(np.std(y_te - p_lstm))
    yy, cc = np.concatenate([y, np.zeros(HORIZON)]), np.vstack([cal, fut_cal])
    for h in range(HORIZON):
        t = len(y) + h
        yy[t] = lstm_predict(model, yy, cc, mu, sd, t, t + 1)[0]
    lstm_fc = yy[len(y):]

    rows = []
    for i, d in enumerate(fut_idx):
        rows.append((d.date(), "sarima", float(sar_mean[i]), float(sar_ci[i, 0]), float(sar_ci[i, 1])))
        band = 1.96 * lstm_resid_sd * np.sqrt(1 + i / 7)   # widen with horizon
        rows.append((d.date(), "lstm", float(lstm_fc[i]), float(lstm_fc[i] - band), float(lstm_fc[i] + band)))
    with psycopg.connect(settings.pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM forecasts")
        cur.executemany("INSERT INTO forecasts (forecast_date, model, yhat, yhat_lo, yhat_hi) VALUES (%s,%s,%s,%s,%s)", rows)
        for name, m in res.items():
            for k, v in m.items():
                cur.execute("INSERT INTO model_metrics (model_name, version, metric, value) VALUES (%s,%s,%s,%s) "
                            "ON CONFLICT (model_name, version, metric) DO UPDATE SET value=EXCLUDED.value",
                            ("forecast", name, k, float(v)))
    # Back-test predictions for the dashboard chart
    bt = pd.DataFrame({"date": idx[n_tr:], "actual": y_te, "seasonal_naive": y[n_tr - 7:len(y) - 7],
                       "sarima": p_sar, "lstm": p_lstm})
    settings.model_dir.mkdir(parents=True, exist_ok=True)
    bt.to_csv(settings.model_dir / "forecast_backtest.csv", index=False)
    torch.save(model.state_dict(), settings.model_dir / "lstm_forecaster.pt")

    mlflow.set_tracking_uri(settings.mlflow_uri)
    mlflow.set_experiment("claimstream-forecast")
    with mlflow.start_run(run_name="daily-volume"):
        mlflow.log_params({"lookback": LOOKBACK, "test_days": TEST_DAYS, "lstm_hidden": 48, "lstm_layers": 2})
        for name, m in res.items():
            mlflow.log_metrics({f"{name}_{k}": v for k, v in m.items()})
    (settings.model_dir / "forecast_metrics.json").write_text(json.dumps({**res, "best": best}, indent=2))
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
