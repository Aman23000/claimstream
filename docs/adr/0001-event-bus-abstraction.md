# ADR 0001: One event-bus interface over Redis Streams and Kafka

**Status:** accepted

## Context
The pipeline needs durable, replayable, consumer-group semantics. Kafka is the production standard but
heavy to run on a laptop or in CI. Redis Streams offers consumer groups, pending-entry lists and
`XAUTOCLAIM` with a single lightweight binary.

## Decision
Put a small `EventBus` interface (`publish`, `consume`, `ack`, `lag`) in front of both backends and choose
one with `EVENT_BUS`. Use Redis Streams by default for local runs and tests; use Kafka in docker-compose.

## Consequences
- The processor code doesn't depend on the broker.
- The interface is lowest-common-denominator: it doesn't expose Kafka-specific features such as
  exactly-once transactions or compacted topics.
- Delivery is at-least-once on both backends, which is why writes must be idempotent.
