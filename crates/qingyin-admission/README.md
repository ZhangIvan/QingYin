# qingyin-admission

`qingyin-admission` owns deterministic overload decisions and the leak-free lifecycle of capacity and budget reservations. It does not implement HTTP handlers, Provider selection, or a production state backend.

## Module map

| Module | Responsibility |
| --- | --- |
| `model` | Actor-bound operation keys, immutable snapshots/dimensions, gates, pending handles, reservations, and terminal receipts |
| `store` | Generation-exact attempt transaction, reconciliation, idempotent renewal, and exactly-once terminal contracts |
| `service` | Fixed gate order, recoverable compensation, trusted lifecycle authority, and result post-validation |
| `error` | Stable sanitized internal failures |

## Fixed gate order

1. request rate
2. active sessions
3. Gateway bytes
4. Provider capacity
5. policy
6. budget

The service never queues an overloaded request. A request is permanently bound
to its verified actor, tenant, session, canonical request digest, reservation ID,
operation, and nonzero attempt generation. It deliberately does not parse HTTP
`Idempotency-Key`; M1-07 supplies the canonical 32-byte request digest.

The durable state machine is `unseen -> provisional -> committed ->
released|settled|expired`, with `provisional -> compensated|expired`. A dropped
future or uncertain compensation/commit returns the exact `AdmissionPending`
generation. Every reconciliation result, including compensated and expired,
carries or contains that same exact generation for service post-validation.
Callers reconcile it instead of starting ambiguous work. A stale generation
conflicts, preventing ABA reuse.

External clients may only cancel their exact actor-bound reservation with
`SessionCancel`, which fixes the outcome to `ClientCancelled`. Renew, internal
release, settlement, and tenant-filtered expiry reclaim require a tenant-bound
service account with `AdmissionManage`. Replaying a renewal ID never extends a
reservation twice and returns its current active record; only a new ID may
extend it.

TTL expiry invalidates an operation at the authoritative store boundary, but
capacity recovery is deliberately owned by exact reconciliation or bounded
tenant reclaim. Runtime integration must define, monitor, and alert on a
reclaimer SLO; before the sweep runs, expired records remain fail-closed and may
temporarily retain capacity. An expired operation identity is never reused.

M1-05 supplies a deterministic in-memory implementation in `qingyin-testkit`. Real Redis/PostgreSQL capacity state, Provider probes, pricing, and Gateway wiring remain later-stage work.
