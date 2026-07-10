# qingyin-state

`qingyin-state` is the storage-semantic boundary for QingYin. It deliberately contains no PostgreSQL, Redis, HTTP, WebSocket, Provider SDK, or runtime dependency.

## Module map

| Module | Responsibility |
| --- | --- |
| `error` | Sanitized state errors and affected entity categories |
| `model` | Tenant-scoped session, reservation, outbox, and TTL value types |
| `store` | Async durable transaction and ephemeral TTL traits |
| `time` | Monotonic time used only for TTL and timeout decisions |

## Invariants

- Every state key includes the full organization/workspace/project/environment scope.
- Session transitions use the canonical state machine and reject terminal rewrites.
- A durable transaction exposes either all staged changes or none of them.
- Reservation and outbox inserts are idempotent only when the same identity carries identical content.
- TTL checks use store-owned monotonic time; values are absent at the exact expiry boundary.
- TTL compare-and-take provides the primitive required for later single-use ticket consumption; compare-and-extend supports race-safe heartbeat renewal.
- Errors never include stored payloads or tenant identifiers.

M1-03 supplies deterministic in-memory implementations from `qingyin-testkit`. Real PostgreSQL and Redis adapters are separate later work and must pass the same contract suite.
