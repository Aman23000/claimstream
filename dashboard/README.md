# Dashboard (Streamlit)

Reads **only** through the REST API (`API_URL`, default `http://127.0.0.1:8000`). It never touches the database directly.

| Tab | Shows |
|---|---|
| ⚡ Live operations | Claims scored, amount, alert rate, throughput, latency p95, consumer lag; per-minute charts; live claims by region (auto-refreshes every 5 s) |
| 🚨 Fraud alerts | Latest HIGH-risk claims with ML and rules scores; which rules fire; drill-down into one claim |
| 📈 Forecast | Back-test of all models against actuals; 30-day forecast with a 95% interval |
| 🗺️ Portfolio | Daily volume with a 7-day average, average claim amount, fraud rate, region league table |
| 🧪 Models | Model vs rules metrics, feature importance, live score distribution, observed fraud rate by risk band |
| 🔍 Score a claim | What-if form; scores a hypothetical claim without saving it |

```bash
streamlit run dashboard/app.py              # http://localhost:8501
python scripts/screenshots.py               # regenerate docs/img/*.png (Playwright)
```
