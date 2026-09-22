## Architecture: Dynamic Executable Contracts (DEC)

Instead of static JSON spec files and comment regexes, the Spec Agent emits **Executable Contract Interfaces (ECIs)**—compilable, strongly-typed spec stubs or property suites—that the Implementer Agent must directly implement and pass.

```javascript
┌─────────────────────────────────────────────────────────────────────────────────┐
│                               SPEC / AUDITOR AGENT                              │
│                                                                                 │
│   1. Generates Interface / Spec Stub (.zft/contracts/auth.contract.ts)          │
│   2. Defines Property Invariants & Edge Cases (Property Generator Tests)        │
└────────────────────────────────────┬────────────────────────────────────────────┘
                                     │
                                     ▼ Emits Interface + Test Harness
┌─────────────────────────────────────────────────────────────────────────────────┐
│                             IMPLEMENTER AGENT (LOOP)                            │
│                                                                                 │
│   1. Implements code directly targeting the Interface                           │
│   2. Runs Verification Loop against Spec Agent's Test Harness                   │
│   3. Refactors code until 100% Invariants + Coverage hold                        │
└────────────────────────────────────┬────────────────────────────────────────────┘
                                     │
                                     ▼ Signed Execution Ledger
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              MUTATION & COVERAGE GATE                           │
│                                                                                 │
│   1. Dynamic Mutation Test (Injects bugs into Implementer's code)               │
│   2. Verifies Spec Agent's tests actually catch the mutations                    │
│   3. Generates Cryptographic Attestation Manifest                               │
└─────────────────────────────────────────────────────────────────────────────────┘
```

***

## The Core Design Choices

### 1. Contract Definition: Interface Code vs. Static JSON Schema

* **Static JSON Schema (Competitor):** Spec agent writes JSON specs; Implementer writes code and adds `@trace` comments linking them.
* **Executable Contracts (Proposed):** Spec agent writes **type definitions and executable invariant tests directly in the target language** (or an IDL like Protobuf/Smithy).
* *Why this wins:* Agents communicate far better via concrete code and compiler errors than meta-comment annotations. The compiler enforces the contract structure before tests even run.

### 2. Lineage Extraction: AST Comment Tags vs. AST Symbol/Call-Graph Resolution

* **Comment Tags (**`@trace`**):** Relies on regex inside docstrings/comments.
* **Symbol Resolution (SCIP / Semantic AST):** The contract interface *is* the type. The lineage is automatically tracked by analyzing the language call-graph (e.g., `class TokenValidator implements AuthContract`).
* *Why this wins:* Zero string-matching maintenance. If the Implementer Agent renames an internal function, type resolution keeps the lineage intact without breaking trace links.

### 3. Verification Gate: Static AST Inspection vs. Dynamic Mutation Proof

* **Static AST Checks (Competitor):** Inspects code to see if `@given` or `assert` exist.
* **Dynamic Mutation Testing:** The pipeline injects intentional bugs (mutants) into the Implementer's generated code. If the Spec Agent's tests don't fail, the contract is considered *under-specified* or *fraudulent*.
* *Why this wins:* AI agents are notorious for generating code that passes basic assertions while missing boundary logic. Mutation testing forces the Spec Agent to write robust tests and the Implementer Agent to write complete logic.

***

## Architectural Trade-Off Analysis

| Dimension              | Option A: Declarative Text/JSON Contracts | Option B: Dynamic Executable Contracts (Proposed)    | Option C: Shared Memory / LLM-in-the-Loop Evaluator |
| ---------------------- | ----------------------------------------- | ---------------------------------------------------- | --------------------------------------------------- |
| **Contract Medium**    | JSON/YAML files + Comment annotations     | Code Interfaces + Property-Based Test Stubs          | Free-form natural language prompts + LLM Judge      |
| **Determinism**        | High (Static)                             | **100% (Compiler & Runtime Enforced)**               | Low (Probabilistic / Subject to Drift)              |
| **Agent Friction**     | High (Requires maintaining schema & tags) | **Low (Standard coding/compiling loop)**             | Very Low (Plain prompt exchanges)                   |
| **Verification Speed** | Fast ($\le 2\text{s}$)                    | Moderate (5–15s due to test compilation & mutation)  | Slow (API latency per evaluation call)              |
| **Audit Rigor**        | Low (Susceptible to fake assertions)      | **Cryptographic (Proves test execution & coverage)** | Poor (Non-repeatable evaluation)                    |

### Key Trade-Off Highlights

1. **Safety vs. Token Overhead (Execution Cost):**

* *Trade-off:* Running dynamic mutation tests and property generators on every agent iteration costs CPU time and token turns.
* *Mitigation:* Run fast compiler/type checks on local agent loops, and save deep mutation/property gates for the final PR merge gate.

2. **Polyglot Uniformity vs. Language Idioms:**

* *Trade-off:* Using native language interfaces (e.g., TypeScript `interface`, Rust `trait`) requires the Spec Agent to know target language syntax.
* *Mitigation:* Use an Interface Definition Language (IDL) like **Smithy** or **Protobuf** as the universal intermediate representation (IR) if building a strict polyglot system.

***

## Proposed Execution Workflow for A2A Collaboration

```javascript
1. [Spec Agent]      ──► Emits `contract_spec.proto` + `invariants.test.ts`
2. [Compiler]          ──► Generates type stubs for Implementer Agent
3. [Implementer Agent] ──► Fills in code implementation
4. [Quality Gate]      ──► Runs `invariants.test.ts` + Mutation Testing
5. [Spec Auditor]      ──► Signs off on Cryptographic Trace Manifest (Hash + UUIDv7)
```

By removing human-style comment tags (`@trace`) and focusing on **type-level interfaces + automated test harnesses**, the agents interact with mathematical rigor rather than string matching.

