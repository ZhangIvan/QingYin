# Contributing to QingYin

1. Read the task's linked design, contract and fixture before changing code.
2. Create a branch named `feat/<stage>-<task>`, `fix/<stage>-<issue>`, `docs/<scope>` or `chore/<scope>`.
3. Keep a pull request scoped to one independently reviewable change.
4. Run the relevant format, contract, unit, integration and security checks locally.
5. Complete every applicable item in the pull request template and request review.

Public API, state/migration, authorization, ticket, Provider, rate-limit, metering and deletion changes require explicit compatibility, failure-path and rollback discussion. Do not merge a change that bypasses canonical contracts, tenant context, Admission, State Repository or Provider traits.

## Comment Convention

Use short comments to explain intent and constraints that code cannot show directly: protocol invariants, security boundaries, ownership/lifetime, cancellation, concurrency, resource release, compatibility decisions and non-obvious tradeoffs. Public modules and exported APIs need orienting documentation. Do not add comments that merely repeat the next line of code; keep comments current in the same pull request as the behavior they describe.

Start documentation from [docs/INDEX.md](docs/INDEX.md). The required repository workflow and stage plan are defined in [QingYin_工程实施总计划与GitHub治理.md](docs/04-delivery/QingYin_工程实施总计划与GitHub治理.md).
