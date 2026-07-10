# qingyin-testkit

`qingyin-testkit` contains deterministic implementations of QingYin interface crates. It is never a production state backend.

## M1-03 state fakes

| Type | Purpose |
| --- | --- |
| `VirtualClock` | Explicit monotonic time advancement without sleeping |
| `InMemoryStateStore` | Snapshot transaction fake with optimistic commit conflicts |
| `InMemoryTtlStore` | Tenant-scoped TTL map with exact expiry and conditional take |

The fakes favor observable correctness over storage efficiency: durable transactions clone a small test snapshot so uncommitted mutations cannot leak. Tests that pass against these fakes still require separate PostgreSQL/Redis integration evidence before production acceptance.
