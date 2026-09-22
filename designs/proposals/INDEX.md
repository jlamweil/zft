| ID | Title | Version | Status | Target baseline | Date | Summary |
|----|-------|---------|--------|-----------------|------|---------|
| P-001 | Dispatch‑enforcement layer | v1 | PROPOSED | designs/ARCHITECTURE.md (v0) | 2026‑09‑10 | Add pre‑dispatch gate and post‑task verdict to enforce contract use for writer lanes. |
| P-002 | Gate conformance execution | v1 | PROPOSED | designs/ARCHITECTURE.md (v0) | 2026‑09‑10 | Make L1 execute clause properties / require oracle, fixing Gap 001. |
| P-003 | Status & drift reconciliation | v1 | PROPOSED | designs/ARCHITECTURE.md (v0) | 2026‑09‑10 | Record factual corrections: clause count, implementation status, missing files, undocumented tier, etc. |
| P-004 | ISO / conformance direction | v1 | PROPOSED | designs/ARCHITECTURE.md (v0) | 2026‑09‑10 | Introduce independent‑verification tier and tool‑confidence manifest to satisfy ISO 26262, DO‑330, etc. |
| P-005 | Conformance mechanism (oracle‑first, contract‑pinned) | v2 | PROPOSED | designs/ARCHITECTURE.md (v0) | 2026‑09‑10 | Gate‑executed, contract‑pinned consumer oracle; anti‑theater verified; closes Gap 001. |
| P-006 | Runtime & performance architecture | v2 | PROPOSED | designs/ARCHITECTURE.md (v0) | 2026‑09‑10 | Ignore‑set + extraction cache, batched verification, single L1 call; check 14.7 s → ≈ 0.5 s. |
| P-007 | Reverse coverage & non‑code anchors | v1 | PROPOSED | designs/ARCHITECTURE.md (v0) | 2026‑09‑10 | Baseline‑diff reverse coverage (24 flags, 0 FP) + Markdown `@trace` anchors. |
| P-008 | Gate self‑verification & tool confidence | v1 | PROPOSED | designs/ARCHITECTURE.md (v0) | 2026‑09‑10 | Permanent Gap‑001 self‑test + gate/tool manifest hashed into the attestation. |
| P-009 | Interchange: ReqIF 1.2 import/export & ALM sync | v1 | PROPOSED | designs/ARCHITECTURE.md (v0) | 2026‑09‑10 | ReqIF import/export (identity‑stable) + halt‑on‑conflict ALM merge; makes `ATT‑EXTERNAL‑IMPORT` real. |
| P-010 | AI‑level requirements (adopt findings as clauses) | v1 | PROPOSED | designs/ARCHITECTURE.md (v0) | 2026‑09‑10 | Codify the verified loop findings as 10 `ai-conduct` clauses, deferred to v1. |
| P-011 | Human↔AI contract: signed approval & subjective quarantine | v1 | PROPOSED | designs/ARCHITECTURE.md (v0) | 2026‑09‑10 | Human identity + signed VALIDATED transition + subjective‑clause quarantine. |