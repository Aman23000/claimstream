-- Reporting views used by the API and dashboard

-- Open high-risk alerts, newest first, with the evidence an investigator needs
CREATE OR REPLACE VIEW v_fraud_alerts AS
SELECT c.claim_id, c.policy_id, p.region, c.claim_type, c.channel, c.amount,
       c.loss_ts, c.reported_ts, s.model_score, s.rule_score, s.rules_hit, s.risk_level,
       s.scored_at, s.model_version
FROM claims c
JOIN claim_scores s USING (claim_id)
JOIN policies p USING (policy_id)
WHERE s.risk_level = 'HIGH';

-- Hourly operational KPIs with a 24-hour rolling average (window functions)
CREATE OR REPLACE VIEW v_hourly_kpis AS
WITH hourly AS (
    SELECT date_trunc('hour', c.reported_ts) AS hour,
           COUNT(*)                          AS n_claims,
           SUM(c.amount)                     AS total_amount,
           AVG(s.model_score)                AS avg_score,
           COUNT(*) FILTER (WHERE s.risk_level = 'HIGH') AS n_high_risk
    FROM claims c
    LEFT JOIN claim_scores s USING (claim_id)
    GROUP BY 1
)
SELECT hour, n_claims, total_amount, avg_score, n_high_risk,
       AVG(n_claims) OVER (ORDER BY hour ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS n_claims_24h_avg
FROM hourly;

-- Region league table with share of total and rank
CREATE OR REPLACE VIEW v_region_summary AS
SELECT p.region,
       COUNT(*)                                              AS n_claims,
       SUM(c.amount)                                         AS total_amount,
       ROUND(AVG(c.amount), 2)                               AS avg_amount,
       ROUND(100.0 * SUM(c.amount) / SUM(SUM(c.amount)) OVER (), 2) AS pct_of_cost,
       RANK() OVER (ORDER BY SUM(c.amount) DESC)             AS cost_rank,
       ROUND(AVG(CASE WHEN s.risk_level = 'HIGH' THEN 1.0 ELSE 0 END), 4) AS high_risk_rate
FROM claims c
JOIN policies p USING (policy_id)
LEFT JOIN claim_scores s USING (claim_id)
GROUP BY p.region;
