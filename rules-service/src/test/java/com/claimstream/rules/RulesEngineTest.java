package com.claimstream.rules;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Unit tests, dependency-free (plain assertions + a tiny runner) so they run with just a JDK:
 *   javac -d out src/main/java/com/claimstream/rules/*.java src/test/java/com/claimstream/rules/*.java
 *   java -cp out com.claimstream.rules.RulesEngineTest
 */
public final class RulesEngineTest {

    private static int passed = 0;

    private static Map<String, Object> clean() {
        Map<String, Object> f = new HashMap<>();
        f.put("days_since_policy_start", 400.0);
        f.put("log_amount_vs_region", 0.0);
        f.put("policy_claims_90d", 0.0);
        f.put("report_delay_days", 2.0);
        f.put("shared_bank_policies", 1.0);
        f.put("report_hour_night", 0.0);
        f.put("channel_web", 0.0);
        return f;
    }

    static void cleanClaimScoresZero() {
        RulesEngine.Result r = RulesEngine.evaluate(clean());
        check(r.score() == 0 && r.rules().isEmpty(), "clean claim should score 0, got " + r);
    }

    static void earlyAndSharedAccountStack() {
        Map<String, Object> f = clean();
        f.put("days_since_policy_start", 5.0);
        f.put("shared_bank_policies", 4.0);
        RulesEngine.Result r = RulesEngine.evaluate(f);
        check(r.score() == 60, "expected 60, got " + r.score());
        check(r.rules().containsAll(List.of("EARLY_CLAIM", "SHARED_PAYOUT_ACCOUNT")), "rules " + r.rules());
    }

    static void scoreIsCappedAt100() {
        Map<String, Object> f = clean();
        f.put("days_since_policy_start", 1.0);
        f.put("log_amount_vs_region", Math.log(10));
        f.put("policy_claims_90d", 3.0);
        f.put("report_delay_days", 60.0);
        f.put("shared_bank_policies", 5.0);
        f.put("report_hour_night", 1.0);
        f.put("channel_web", 1.0);
        check(RulesEngine.evaluate(f).score() == 100, "score must cap at 100");
    }

    static void missingFieldIsRejected() {
        Map<String, Object> f = clean();
        f.remove("report_delay_days");
        try {
            RulesEngine.evaluate(f);
            check(false, "missing field should throw");
        } catch (IllegalArgumentException expected) {
            check(expected.getMessage().contains("report_delay_days"), "message names the field");
        }
    }

    static void jsonRoundTrip() {
        Map<String, Object> m = Json.parseObject("{\"a\": 1.5, \"b\": \"x\\\"y\", \"c\": true, \"d\": null}");
        check(((Double) m.get("a")) == 1.5 && "x\"y".equals(m.get("b")) && Boolean.TRUE.equals(m.get("c"))
                && m.containsKey("d"), "parsed " + m);
        check(Json.result(40, List.of("A", "B")).equals("{\"score\":40,\"rules\":[\"A\",\"B\"]}"), "serialise");
    }

    private static void check(boolean cond, String msg) {
        if (!cond) throw new AssertionError(msg);
        passed++;
    }

    public static void main(String[] args) {
        cleanClaimScoresZero();
        earlyAndSharedAccountStack();
        scoreIsCappedAt100();
        missingFieldIsRejected();
        jsonRoundTrip();
        System.out.println("RulesEngineTest: " + passed + " assertions passed");
    }
}
