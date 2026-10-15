"""ClaimStream operations dashboard (Streamlit). Reads everything through the REST API.

Run:  streamlit run dashboard/app.py      (API_URL defaults to http://127.0.0.1:8000)
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

API = os.getenv("API_URL", "http://127.0.0.1:8000")

# Validated categorical palette (fixed order) + reserved status colours + recessive chrome
S1, S2, S3, S4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
CRIT, SERIOUS, GOOD = "#d03b3b", "#ec835a", "#0ca30c"
INK, INK2, MUTED, GRID, BASE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
RISK_COLOR = {"HIGH": CRIT, "MEDIUM": SERIOUS, "LOW": GOOD}

st.set_page_config(page_title="ClaimStream", page_icon="🛡️", layout="wide")
st.markdown("""
<style>
  .block-container {padding-top: 1.6rem; max-width: 1400px;}
  [data-testid="stMetricValue"] {font-size: 1.7rem;}
  [data-testid="stMetric"] {background: #fcfcfb; border: 1px solid rgba(11,11,11,0.10);
                            border-radius: 10px; padding: 12px 16px;}
  .pill {display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.8rem;
         font-weight:600; color:#fff;}
</style>""", unsafe_allow_html=True)


@st.cache_data(ttl=4, show_spinner=False)
def get(path: str, **params):
    r = httpx.get(f"{API}{path}", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def style(fig: go.Figure, height: int = 300, title: str | None = None, legend: bool = False) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=40 if title else 10, b=8), title=dict(text=title, x=0,
        font=dict(size=14, color=INK)), paper_bgcolor="#fcfcfb", plot_bgcolor="#fcfcfb",
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", color=INK2, size=12),
        showlegend=legend, legend=dict(orientation="h", y=1.08, x=0, font=dict(color=INK2)),
        hovermode="x unified", hoverlabel=dict(bgcolor="white", font_color=INK))
    fig.update_xaxes(showgrid=False, linecolor=BASE, tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=BASE, tickfont=dict(color=MUTED))
    return fig


def pill(level: str) -> str:
    icon = {"HIGH": "▲", "MEDIUM": "●", "LOW": "✓"}[level]
    return f'<span class="pill" style="background:{RISK_COLOR[level]}">{icon} {level}</span>'


# ------------------------------------------------------------------ header
try:
    health = get("/health")
except Exception as e:
    st.error(f"API not reachable at {API} - start it with `make api`. ({e})")
    st.stop()

left, right = st.columns([2, 3])
left.markdown("## 🛡️ ClaimStream")
left.caption("Real-time insurance claims intelligence · fraud scoring · forecasting")
badges = " ".join(f"{'🟢' if v == 'ok' else '🔴'} {k}" for k, v in health.items() if k != "status")
right.markdown(f"<div style='text-align:right;padding-top:18px;color:{INK2}'>{badges}</div>",
               unsafe_allow_html=True)

tab_live, tab_alerts, tab_fc, tab_port, tab_models, tab_score = st.tabs(
    ["⚡ Live operations", "🚨 Fraud alerts", "📈 Forecast", "🗺️ Portfolio", "🧪 Models", "🔍 Score a claim"])

# ------------------------------------------------------------------ live
with tab_live:
    auto = st.toggle("Auto-refresh every 5 s", value=True)
    if auto:
        st_autorefresh(interval=5000, key="live_refresh")
    window = st.segmented_control("Window", ["15 min", "60 min", "6 h"], default="60 min")
    minutes = {"15 min": 15, "60 min": 60, "6 h": 360}[window or "60 min"]
    live = get("/metrics/live", minutes=minutes)
    ser = pd.DataFrame(live["series"])
    ser["minute"] = pd.to_datetime(ser["minute"])
    t = live["totals"]
    n = int(t.get("claims", 0))
    high = int(t.get("risk_HIGH", 0))
    last5 = ser.tail(5)["claims"].sum() / 5 if len(ser) else 0

    c = st.columns(6)
    c[0].metric("Claims scored", f"{n:,}")
    c[1].metric("Amount claimed", f"${t.get('amount', 0):,.0f}")
    c[2].metric("High-risk alerts", f"{high:,}", f"{(high / n * 100 if n else 0):.2f}% of claims",
                delta_color="off")
    c[3].metric("Throughput", f"{last5:.0f} / min", "last 5 min avg", delta_color="off")
    p95 = live["latency_ms"]["p95"]
    c[4].metric("Scoring latency p95", f"{p95:.0f} ms" if p95 else "—",
                f"p50 {live['latency_ms']['p50']:.0f} ms" if live["latency_ms"]["p50"] else None, delta_color="off")
    c[5].metric("Consumer lag", f"{live['consumer_lag']:,}", "messages waiting", delta_color="off")

    g1, g2 = st.columns([2, 1])
    fig = go.Figure(go.Scatter(x=ser["minute"], y=ser["claims"], mode="lines", line=dict(color=S1, width=2),
                               fill="tozeroy", fillcolor="rgba(42,120,214,0.10)", name="Claims / min",
                               hovertemplate="%{y} claims<extra></extra>"))
    g1.plotly_chart(style(fig, 280, "Claims per minute"), use_container_width=True)
    fig = go.Figure(go.Bar(x=ser["minute"], y=ser["high_risk"], marker=dict(color=CRIT, cornerradius=4),
                           name="High-risk / min", hovertemplate="%{y} high-risk<extra></extra>"))
    g2.plotly_chart(style(fig, 280, "▲ High-risk alerts per minute"), use_container_width=True)

    reg = pd.Series(live["regions_live"], dtype=float).sort_values().tail(12)
    fig = go.Figure(go.Bar(x=reg.values, y=reg.index, orientation="h", marker=dict(color=S1, cornerradius=4),
                           text=reg.astype(int), textposition="outside", textfont=dict(color=INK2),
                           hovertemplate="%{y}: %{x} claims<extra></extra>"))
    st.plotly_chart(style(fig, 360, "Live claims by region (top 12)"), use_container_width=True)

# ------------------------------------------------------------------ alerts
with tab_alerts:
    data = get("/alerts", limit=200)
    al = pd.DataFrame(data["alerts"])
    st.caption(f"{len(al)} most recent high-risk claims · source: {data['source']} · "
               "an alert fires when the ML score is above the operating threshold OR the rules score ≥ 60")
    if al.empty:
        st.info("No high-risk alerts yet - start the producer (`make produce`).")
    else:
        al["rules"] = al["rules_hit"].apply(lambda r: ", ".join(r) if isinstance(r, list) else r)
        view = al[["claim_id", "reported_ts", "region", "claim_type", "channel", "amount",
                   "model_score", "rule_score", "rules"]].copy()
        st.dataframe(view, hide_index=True, use_container_width=True, height=380, column_config={
            "amount": st.column_config.NumberColumn("Amount", format="$%.0f"),
            "model_score": st.column_config.ProgressColumn("ML score", min_value=0, max_value=1, format="%.2f"),
            "rule_score": st.column_config.ProgressColumn("Rules score", min_value=0, max_value=100, format="%d"),
            "reported_ts": st.column_config.DatetimeColumn("Reported", format="MMM D, HH:mm:ss")})
        a1, a2 = st.columns(2)
        rules = al["rules_hit"].explode().dropna().value_counts().sort_values()
        fig = go.Figure(go.Bar(x=rules.values, y=rules.index, orientation="h",
                               marker=dict(color=S2, cornerradius=4), hovertemplate="%{y}: %{x}<extra></extra>"))
        a1.plotly_chart(style(fig, 300, "Which red-flag rules fire on alerts"), use_container_width=True)
        fig = go.Figure(go.Histogram(x=al["amount"], nbinsx=30, marker=dict(color=S1, line=dict(color="#fcfcfb", width=2)),
                                     hovertemplate="$%{x}: %{y} alerts<extra></extra>"))
        a2.plotly_chart(style(fig, 300, "Alert amounts"), use_container_width=True)

        st.markdown("#### Investigate a claim")
        cid = st.selectbox("Claim", al["claim_id"].tolist())
        if cid:
            d = get(f"/claims/{cid}")
            k = st.columns(4)
            k[0].markdown(f"**Risk** {pill(d['risk_level'])}", unsafe_allow_html=True)
            k[1].markdown(f"**Amount** ${float(d['amount']):,.2f}")
            k[2].markdown(f"**Policy start** {d['policy_start']}")
            k[3].markdown(f"**Bonus-malus** {d['bonus_malus']} · **Driver age** {d['driv_age']}")
            st.json(d, expanded=False)

# ------------------------------------------------------------------ forecast
with tab_fc:
    fc = get("/forecast")
    bt = pd.DataFrame(fc["backtest"])
    m = get("/models")["metrics"].get("forecast", {})
    k = st.columns(3)
    for col, (name, label) in zip(k, [("seasonal_naive", "Seasonal naive (baseline)"), ("sarima", "SARIMA"),
                                      ("lstm", "LSTM (PyTorch)")]):
        if name in m:
            col.metric(label, f"MAE {m[name]['mae']:.1f} claims/day", f"MAPE {m[name]['mape']:.1f}%", delta_color="off")
    if not bt.empty:
        bt["date"] = pd.to_datetime(bt["date"])
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=bt.date, y=bt.actual, name="Actual", mode="lines+markers",
                                 line=dict(color=INK, width=2), marker=dict(size=5)))
        for name, colr, dash in (("sarima", S1, "solid"), ("lstm", S2, "solid"), ("seasonal_naive", MUTED, "dot")):
            fig.add_trace(go.Scatter(x=bt.date, y=bt[name], name=name.replace("_", " ").upper()
                                     if name != "seasonal_naive" else "Seasonal naive",
                                     mode="lines", line=dict(color=colr, width=2, dash=dash)))
        st.plotly_chart(style(fig, 340, "Back-test: one-day-ahead forecasts on the last 60 days", legend=True),
                        use_container_width=True)
    f = pd.DataFrame(fc["forecast"])
    if not f.empty:
        f["forecast_date"] = pd.to_datetime(f["forecast_date"])
        choice = st.radio("Forward forecast model", ["sarima", "lstm"], horizontal=True,
                          format_func=lambda x: x.upper())
        g = f[f.model == choice]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=pd.concat([g.forecast_date, g.forecast_date[::-1]]),
                                 y=pd.concat([g.yhat_hi, g.yhat_lo[::-1]]), fill="toself",
                                 fillcolor="rgba(42,120,214,0.15)", line=dict(width=0), name="95% interval",
                                 hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=g.forecast_date, y=g.yhat, name="Forecast", mode="lines+markers",
                                 line=dict(color=S1, width=2), marker=dict(size=6)))
        st.plotly_chart(style(fig, 320, f"Next 30 days - expected claims per day ({choice.upper()})", legend=True),
                        use_container_width=True)
        st.caption("Used for adjuster staffing: the upper band is the capacity to plan for.")

# ------------------------------------------------------------------ portfolio
with tab_port:
    st.caption("Historical book (2 years of claims). The live demo stream is excluded here because it replays "
               "at accelerated speed, so its daily totals are not real volumes.")
    days = st.select_slider("History (days)", options=[30, 90, 180, 365, 730], value=180)
    dd = pd.DataFrame(get("/kpis/daily", days=days))
    if not dd.empty:
        dd["claim_date"] = pd.to_datetime(dd["claim_date"])
        for col in ("n_claims", "total_amount", "avg_amount", "fraud_rate"):
            dd[col] = pd.to_numeric(dd[col])
        dd["ma7"] = dd["n_claims"].rolling(7, min_periods=1).mean()
        fig = go.Figure()
        fig.add_trace(go.Bar(x=dd.claim_date, y=dd.n_claims, name="Daily claims",
                             marker=dict(color="rgba(42,120,214,0.35)")))
        fig.add_trace(go.Scatter(x=dd.claim_date, y=dd.ma7, name="7-day average", line=dict(color=S1, width=2)))
        st.plotly_chart(style(fig, 320, "Claims reported per day", legend=True), use_container_width=True)
        p1, p2 = st.columns(2)
        fig = go.Figure(go.Scatter(x=dd.claim_date, y=dd["avg_amount"].rolling(7, min_periods=1).mean(),
                                   line=dict(color=S3, width=2), hovertemplate="$%{y:,.0f}<extra></extra>"))
        p1.plotly_chart(style(fig, 280, "Average claim amount (7-day avg, $)"), use_container_width=True)
        fig = go.Figure(go.Scatter(x=dd.claim_date, y=dd["fraud_rate"].rolling(14, min_periods=1).mean() * 100,
                                   line=dict(color=S2, width=2), hovertemplate="%{y:.2f}%<extra></extra>"))
        p2.plotly_chart(style(fig, 280, "Confirmed fraud rate (14-day avg, %)"), use_container_width=True)
    rg = pd.DataFrame(get("/regions"))
    if not rg.empty:
        st.markdown("#### Region league table")
        for col in ("total_amount", "avg_amount", "pct_of_cost", "high_risk_rate"):
            rg[col] = pd.to_numeric(rg[col])
        st.dataframe(rg, hide_index=True, use_container_width=True, column_config={
            "total_amount": st.column_config.NumberColumn("Total cost", format="$%.0f"),
            "avg_amount": st.column_config.NumberColumn("Avg claim", format="$%.0f"),
            "pct_of_cost": st.column_config.ProgressColumn("Share of cost", format="%.1f%%", min_value=0,
                                                           max_value=float(rg.pct_of_cost.max())),
            "high_risk_rate": st.column_config.NumberColumn("High-risk rate", format="%.4f")})

# ------------------------------------------------------------------ models
with tab_models:
    md = get("/models")
    fraud = md["metrics"].get("fraud", {})
    current = next((v for v, mm in fraud.items() if mm.get("is_current")), None)
    if current:
        mm = fraud[current]
        st.markdown(f"**Fraud model** `{current}` · out-of-time test (claims after 2026-06-01) · "
                    f"base fraud rate {mm['fraud_base_rate']:.2%}")
        k = st.columns(4)
        k[0].metric("PR-AUC (ML)", f"{mm['model_pr_auc']:.3f}", f"rules only {mm['rules_pr_auc']:.3f}", delta_color="off")
        k[1].metric("ROC-AUC (ML)", f"{mm['model_roc_auc']:.3f}", f"rules only {mm['rules_roc_auc']:.3f}", delta_color="off")
        k[2].metric("Precision, top 1% flagged", f"{mm['model_precision_top1pct']:.0%}",
                    f"recall {mm['model_recall_top1pct']:.0%}", delta_color="off")
        k[3].metric("Recall, top 3% flagged", f"{mm['model_recall_top3pct']:.0%}",
                    f"rules only {mm['rules_recall_top3pct']:.0%}", delta_color="off")
        m1, m2 = st.columns(2)
        fig = go.Figure(go.Bar(x=["Rules engine", "ML model"], y=[mm["rules_pr_auc"], mm["model_pr_auc"]],
                               marker=dict(color=[MUTED, S1], cornerradius=4), width=0.5,
                               text=[f"{mm['rules_pr_auc']:.2f}", f"{mm['model_pr_auc']:.2f}"],
                               textposition="outside", textfont=dict(color=INK)))
        fig.add_hline(y=mm["fraud_base_rate"], line=dict(color=BASE, dash="dot"))
        m1.plotly_chart(style(fig, 300, "Precision-recall AUC (higher is better; dotted = random guessing)"),
                        use_container_width=True)
        imp = pd.Series(md["fraud_feature_importance"]).sort_values().tail(10)
        fig = go.Figure(go.Bar(x=imp.values / imp.values.sum(), y=imp.index, orientation="h",
                               marker=dict(color=S1, cornerradius=4), hovertemplate="%{y}: %{x:.1%}<extra></extra>"))
        fig.update_xaxes(tickformat=".0%")
        m2.plotly_chart(style(fig, 300, "What drives the fraud score (share of gain)"), use_container_width=True)
    mix = pd.DataFrame(md["live_risk_mix"])
    hist = pd.DataFrame(md["score_histogram"])
    if not mix.empty:
        st.markdown("#### Live monitoring")
        h1, h2 = st.columns(2)
        fig = go.Figure(go.Bar(x=(hist.bucket - 1) * 0.05, y=hist.n, marker=dict(color=S1, line=dict(color="#fcfcfb", width=2)),
                               hovertemplate="score %{x:.2f}-: %{y} claims<extra></extra>"))
        fig.update_yaxes(type="log")
        h1.plotly_chart(style(fig, 280, "Live score distribution (log scale) - watch for drift"), use_container_width=True)
        mix["observed_fraud_rate"] = pd.to_numeric(mix["observed_fraud_rate"])
        order = ["LOW", "MEDIUM", "HIGH"]
        mix = mix.set_index("risk_level").reindex(order).dropna(how="all").reset_index()
        fig = go.Figure(go.Bar(x=mix.risk_level, y=mix.observed_fraud_rate * 100,
                               marker=dict(color=[RISK_COLOR[r] for r in mix.risk_level], cornerradius=4),
                               text=[f"{v:.1f}%" for v in mix.observed_fraud_rate * 100], textposition="outside",
                               textfont=dict(color=INK)))
        h2.plotly_chart(style(fig, 280, "Observed fraud rate by risk band (%) - is the ranking holding?"),
                        use_container_width=True)

# ------------------------------------------------------------------ what-if scoring
with tab_score:
    st.markdown("Score a hypothetical claim against the live model and rules **without saving it**.")
    with st.form("score"):
        a, b, c3 = st.columns(3)
        policy_id = a.number_input("Policy ID", value=1, step=1)
        amount = b.number_input("Amount ($)", value=2500.0, step=100.0)
        ctype = c3.selectbox("Claim type", ["collision", "theft", "glass", "liability", "fire"])
        a, b, c3 = st.columns(3)
        channel = a.selectbox("Channel", ["web", "app", "phone", "agent"])
        delay = b.slider("Days between loss and report", 0, 120, 2)
        hour = c3.slider("Hour reported (UTC)", 0, 23, 14)
        go_btn = st.form_submit_button("Score claim", type="primary")
    if go_btn:
        rep = datetime.now(timezone.utc).replace(hour=hour, minute=0, second=0, microsecond=0)
        body = {"claim_id": f"CLM-whatif-{uuid.uuid4().hex[:8]}", "policy_id": int(policy_id),
                "loss_ts": (rep - timedelta(days=delay)).isoformat(), "reported_ts": rep.isoformat(),
                "amount": amount, "claim_type": ctype, "channel": channel}
        r = httpx.post(f"{API}/score", json=body, timeout=10)
        if r.status_code != 200:
            st.error(r.json().get("detail", r.text))
        else:
            s = r.json()
            k = st.columns(4)
            k[0].markdown(f"### {pill(s['risk_level'])}", unsafe_allow_html=True)
            k[1].metric("ML fraud probability", f"{s['model_score']:.1%}")
            k[2].metric("Rules score", f"{s['rule_score']} / 100")
            k[3].metric("Latency", f"{s['latency_ms']:.0f} ms")
            st.write("**Rules fired:** " + (", ".join(s["rules_hit"]) or "none"))
