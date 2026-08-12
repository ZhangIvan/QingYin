# qingyin-testkit

`qingyin-testkit` contains deterministic implementations of QingYin interface crates. It is never a production state backend.

## M1-03 state fakes

| Type | Purpose |
| --- | --- |
| `VirtualClock` | Explicit monotonic time advancement without sleeping |
| `InMemoryStateStore` | Snapshot transaction fake with optimistic commit conflicts |
| `InMemoryTtlStore` | Tenant-scoped TTL map with exact expiry and conditional take |

## M1-05 admission fake

`InMemoryAdmissionStore` provides an `Arc<Mutex<_>>` implementation of the
six-gate admission and reservation lifecycle. It uses `VirtualClock`, immutable
capacity/policy profiles, checked counters, exact authenticated operation keys,
globally unique nonzero attempt generations, and deterministic expiry
reclamation. Exact provisional retries remain `Pending`; reconciliation follows
the requested generation, while compensated retries allocate a new generation
without letting stale attempts observe or commit it.

Compensated and expired tombstones retain their exact original pending handle.
When a compensated retry advances, the retired tombstone moves into a
per-identity history capped at 1,024 generations. History is never evicted:
opening another generation fails closed once the cap is reached.

Repeating a renewal identifier never extends twice and returns the current
active reservation, including any later extension made with a different ID.
The per-reservation identifier set is bounded at 1,024 entries and discarded
on a terminal transition. Scoped reclaim processes only the requested tenant
and uses `(expiry, generation)` ordering, so bounded maintenance is
deterministic. Before reconciliation or reclaim runs, an expired record remains
fail-closed and may retain its claims; production integration therefore needs a
monitored reclaimer SLO.
The fake is intended for fail-fast order, rollback, idempotency, expiry,
renewal, terminal race, and tenant-isolation tests without wall-clock sleeps.

The fake preserves three scope rules that adapters must not weaken:

- Request-rate usage is principal-scoped inside the complete tenant scope. A
  provisional debit is refunded when its attempt is rejected or rolled back;
  after commit it remains consumed for the configured profile/window and is not
  returned by release, settlement, or expiry reclamation. A production adapter
  must implement the actual window/refill policy.
- Active-session usage is project-scoped by organization, workspace, and
  project. Environments under that project therefore share the same active
  limit; all reservation identities still include the environment for strict
  lifecycle isolation.
- Budget usage is keyed by the complete tenant scope plus the budget account.
  Equal account identifiers in different tenants never share a counter.

The fakes favor observable correctness over storage efficiency: durable transactions clone a small test snapshot so uncommitted mutations cannot leak. Tests that pass against these fakes still require separate PostgreSQL/Redis integration evidence before production acceptance.
