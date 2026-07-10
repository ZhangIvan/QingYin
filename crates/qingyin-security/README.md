# qingyin-security

`qingyin-security` is the trusted inner boundary for verified principals, explicit scopes, short-lived single-use session tickets, and secret-safe formatting.

## Module map

| Module | Responsibility |
| --- | --- |
| `principal` | Immutable tenant ownership, principal kind/role, explicit scope authorization |
| `secret` | Zeroizing secret strings and redacted values that never retain input |
| `ticket/model` | Ticket secret/digest, channel and binding types, fixed TTL policy |
| `ticket/codec` | OS entropy and HMAC-SHA256 ticket digest using a deployment pepper |
| `ticket/service` | Tenant-scoped issue, binding verification, atomic consume, and revoke |

## Trust rules

- Only a credential verifier may construct a `Principal`; request DTOs never supply tenant ownership.
- Roles do not grant permissions implicitly. Every command checks a closed `Scope` value.
- Ticket storage contains the HMAC digest key and structured binding metadata, never the raw ticket.
- A ticket is valid only for its exact tenant, session, principal digest, channel, optional client binding, and live TTL entry.
- A live record is `unused`; atomic compare-and-take removes it and returns `consumed`, while missing, expired, revoked, and replayed records remain indistinguishable.
- Consumption uses state revision plus atomic compare-and-take, so exactly one concurrent caller succeeds.
- Ticket and credential failures use non-oracular errors; logs receive only fixed redacted markers.

M1-04 does not implement an HTTP authentication middleware, credential database, KMS, OAuth/OIDC, or Provider credentials.
