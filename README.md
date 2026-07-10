# QingYin

QingYin is a multi-tenant, multi-provider realtime voice gateway for streaming ASR, TTS and realtime sessions. Business systems integrate with one canonical protocol while QingYin controls routing, admission, isolation, metering, observability and Provider adapters.

## Current Stage

The architecture and implementation baseline are complete. Engineering starts with M1: a Rust Gateway, canonical contracts, state/admission boundaries and a Scripted MockProvider. No production Provider, capacity figure or SLA is claimed by this repository yet.

## Documentation

- [Progressive documentation index](docs/INDEX.md)
- [System design index](docs/02-architecture/QingYin_系统设计目录与实施计划.md)
- [Implementation and GitHub governance](docs/04-delivery/QingYin_工程实施总计划与GitHub治理.md)
- [M1 Rust core runtime](docs/04-delivery/QingYin_M1_Rust核心骨架与运行规范.md)
- [Design freeze and implementation admission](docs/02-architecture/QingYin_设计冻结审阅与实现准入清单.md)

Formal contracts live in `contracts/openapi/` and `contracts/asyncapi/`. Before any API, schema or event change, update its fixture and compatibility evidence in the same pull request.

## Contribution Rules

Work only on task branches and merge through pull requests. The PR template requires design linkage, validation evidence, privacy/security review and cancellation/state-resource checks. `main` is protected with required CI and review rules described in the governance document.

Do not commit credentials, one-time tickets, Provider signatures, production configuration, real audio, full user transcripts or customer data. See [SECURITY.md](SECURITY.md).
