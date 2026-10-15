# ADR 0002: Run a transparent rules engine alongside the ML model

**Status:** accepted

## Context
Fraud teams need explainable, auditable decisions. Compliance signs off on individual rules, and
investigators need to see *why* a claim was flagged. ML catches combinations the rules miss, but a score
alone is hard to defend.

## Decision
Score every claim with both. The rules live in a separate Java service so they can be owned and released
independently and audited in isolation. An alert fires if *either* signal is confident (see
`docs/architecture.md`, Risk banding). The rules engine is also the baseline the model must beat.

## Consequences
- On the out-of-time test, the model is 3.2× better than the rules on PR-AUC (0.36 vs 0.11); the rules still
  explain most alerts.
- One extra network hop per claim, mitigated by a 500 ms timeout and a circuit breaker.
