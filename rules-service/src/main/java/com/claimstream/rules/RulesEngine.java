package com.claimstream.rules;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Deterministic SIU (special investigations unit) red-flag rules.
 *
 * Rules are transparent and auditable, which is why insurers run them next to the ML model:
 * an investigator can see exactly which rule fired, and compliance can sign off on each one.
 */
public final class RulesEngine {

    public record Result(int score, List<String> rules) {}

    private RulesEngine() {}

    public static Result evaluate(Map<String, Object> f) {
        int score = 0;
        List<String> hit = new ArrayList<>();

        double daysSinceStart = num(f, "days_since_policy_start");
        double amountRatio = Math.exp(num(f, "log_amount_vs_region"));
        double prior90d = num(f, "policy_claims_90d");
        double delay = num(f, "report_delay_days");
        double sharedBank = num(f, "shared_bank_policies");
        boolean night = num(f, "report_hour_night") >= 1.0;
        boolean web = num(f, "channel_web") >= 1.0;

        if (daysSinceStart < 30) { score += 30; hit.add("EARLY_CLAIM"); }
        if (amountRatio > 4.0)   { score += 25; hit.add("HIGH_AMOUNT_FOR_REGION"); }
        if (prior90d >= 2)       { score += 30; hit.add("MULTIPLE_RECENT_CLAIMS"); }
        else if (prior90d >= 1)  { score += 15; hit.add("RECENT_PRIOR_CLAIM"); }
        if (delay > 30)          { score += 15; hit.add("LATE_REPORTING"); }
        if (sharedBank >= 3)     { score += 30; hit.add("SHARED_PAYOUT_ACCOUNT"); }
        if (night && web)        { score += 10; hit.add("NIGHT_WEB_SUBMISSION"); }

        return new Result(Math.min(score, 100), hit);
    }

    private static double num(Map<String, Object> f, String key) {
        Object v = f.get(key);
        if (v == null) throw new IllegalArgumentException("missing field: " + key);
        if (v instanceof Number n) return n.doubleValue();
        if (v instanceof Boolean b) return b ? 1.0 : 0.0;
        return Double.parseDouble(v.toString());
    }
}
