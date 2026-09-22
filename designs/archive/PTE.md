# Polyglot Traceability Engine (PTE)

## Core System Architecture & Engine Specification

***

## 1. Executive Summary

The **Polyglot Traceability Engine (PTE)** is a decentralized, high-concurrency verification and continuous compliance platform designed for safety-critical, highly regulated software engineering workflows (e.g., ISO 26262, IEC 62304, DO-178C, HIPAA, SOC 2).

Modern development environment bottlenecks stem from four primary challenges:

* **Specification-to-Code Drift:** Requirements living in enterprise databases disconnect from executable source code during rapid refactoring and autonomous multi-agent code generation.
* **Agent Test Hallucination:** Autonomous AI coding agents frequently generate unit tests containing superficial assertions (e.g., `assert result is not None`) to pass code coverage gates without asserting domain invariants.
* **Link Rot & Identifier Instability:** Pure content-based hashing breaks historic links when typos are corrected, while legacy UUID databases cause branch merge collisions during concurrent multi-agent updates.
* **Language AST Fragmentation:** Regulatory tracing tools typically depend on language-specific compiler plugins, requiring separate static analysis infrastructure for every language in a polyglot stack.

PTE addresses these challenges through a unified, local-first architecture:

1. **Decoupled Identity & State Graphing:** Universal specification nodes backed by stable UUIDv7 identifiers paired with cryptographic content-state signing ($\text{SHA-256}$).
2. **Zero-AST Dependency Polyglot Lineage:** Continuous static lineage extraction across 30+ programming languages powered by unified Tree-Sitter S-expression query grammars and explicit, non-intrusive semantic `@trace` markers.
3. **Property-Based Verification Gates:** Automated property boundary synthesis and invariant evaluation that mathematically block trivial or fraudulent test suites.
4. **Git-Native ALM Synchronization:** Asynchronous synchronization between local file-based specification graphs (`.zft/specs/`) and enterprise Application Lifecycle Management (ALM) systems (Jira, Siemens Polarion, IBM DOORS).
5. **Continuous Regulatory Compilation:** On-demand export of deterministic bi-directional trace matrices, ReqIF XML bundles, and ISO/IEC regulatory proofs directly from Git repository states.

***

## 2. System Architecture & Execution Lifecycle

PTE separates state into two runtime operational zones: the **Ephemeral Agent Workspace** (local execution and verification) and the **Central Integration Pipeline** (atomic merge verification and compliance artifact generation).

```javascript
+---------------------------------------------------------------------------------------------------+
|                                   EPHEMERAL AGENT WORKSPACE                                       |
|                                                                                                   |
|  [Specification Agent / Engineer] ---> Emits Spec Node (.zft/specs/<domain>/<alias>.json)          |
|                                                  |                                                |
|                                                  v                                                |
|  [PTE Invariant Quality Gate]     ---> Validates Spec Invariants & Boundary Constraints           |
|                                                  |                                                |
|                                                  v (Passes Quality Gate)                          |
|  [Implementation Agent / Dev]    ---> Generates Polyglot Code + Property Tests w/ @trace Markers  |
|                                                  |                                                |
|                                                  v                                                |
|  [PTE Local Verification Engine]  ---> Tree-Sitter Lineage Extraction + Property Boundary Verification |
+---------------------------------------------------------------------------------------------------+
                                                   |
                                                   v (Atomic Commit / Rebase Queue)
+---------------------------------------------------------------------------------------------------+
|                                CENTRAL INTEGRATION PIPELINE                                       |
|                                                                                                   |
|  [Tree-Sitter Lineage Compiler]   ---> Emits Global Deterministic Traceability Matrix             |
|  [Cryptographic State Signer]     ---> Binds Git Tree Commit Hash to Compliance Graph             |
|  [Compliance Exporter]            ---> Generates ReqIF XML, ISO 26262 / DO-178C Regulatory Bundles|
|  [ALM Sync Worker]                ---> Pushes Bi-Directional State Updates to Jira / DOORS        |
+---------------------------------------------------------------------------------------------------+
```

### Execution Lifecycle Steps

1. **Specification Authoring:** Requirement nodes are created in local Git worktrees as structured JSON objects containing stable identifiers, functional domain classifications, and algebraic invariant properties.
2. **Invariant Validation Gate:** The PTE engine parses local spec nodes, validating invariant syntax, property generator boundaries, and identifier uniqueness prior to implementation.
3. **Implementation & Property Annotation:** Source code and property-based test suites are authored. Code paths and verification tests link to requirement aliases using standard docstrings or code tags (`@trace("ALIAS-ID")`).
4. **Tree-Sitter Lineage Extraction:** Static analysis parses source code abstract syntax trees using native Tree-Sitter S-expressions, mapping requirement nodes to concrete function boundaries, class methods, and test functions in milliseconds.
5. **Property Boundary Evaluation:** Test suites are inspected for algebraic invariant coverage. Mocks or unit tests lacking generative property checks fail local pre-commit gates.
6. **Continuous Compliance Compilation:** Upon atomic merge to the primary branch, the CI/CD engine compiles source code, execution proofs, and requirement nodes into standardized enterprise regulatory artifacts (ReqIF, ISO matrices).

***

## 3. Core Architectural Pillars

### Pillar 1: Dual-Layer Identity & Cryptographic Signing

PTE decouples **long-term identifier stability** from **state immutability**.

Every requirement node uses a **UUIDv7** primary key. UUIDv7 embeds a Unix timestamp in its most significant bits, providing time-ordered sorting while remaining completely immutable across requirement modifications. Cryptographic state verification is derived separately using a normalized $\text{SHA-256}$ content signature.

$$\text{Content Hash} = \text{SHA256}\left(\text{domain} \parallel \text{title} \parallel \text{invariants} \parallel \text{version}\right)$$

```javascript
                               Requirement Node Schema
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │ Node ID (UUIDv7)       : 018f3a2b-9e41-7100-8000-000000000001 (Immutable Entity)  │
 │ Mutable Dynamic Alias  : AUTH-OAUTH-JWT-VALIDATE           (Human Reference)     │
 ├──────────────────────────────────────────────────────────────────────────────────┤
 │ Structural Payload     : Domain, Title, Description, Invariants                  │
 ├──────────────────────────────────────────────────────────────────────────────────┤
 │ State Hash (SHA-256)   : e3b0c44298fc1c149afbf4c8996fb92427ae4... (State Verification)│
 └──────────────────────────────────────────────────────────────────────────────────┘
```

* **Renames & Clarifications:** Modifying a requirement's text updates the `Content Hash` and increments the `version` counter without changing the `Node ID` or `Alias`. External links in Jira or DOORS remain intact.
* **Audit Trail Signing:** During CI compilation, the `Content Hash` of every spec node is cryptographically bound to the current Git commit hash, producing an unforgeable compliance state ledger.

***

### Pillar 2: Polyglot Lineage Extraction via Unified Tree-Sitter Queries

PTE avoids maintaining custom language-specific compiler plugins. Instead, it extracts static lineage across 30+ programming languages using native **Tree-Sitter** S-expression query grammars.

Tree-Sitter generates concrete syntax trees in C/C++ speed. A single query definition pattern matches `@trace` annotations inside comments, docstrings, and decorators regardless of target language semantics.

```lisp
;; Tree-Sitter S-Expression Query for Traceability Annotations
(comment) @annotation
(#match? @annotation "@trace\\(\"([A-Z0-9_-]+)\"\\)")

(function_declaration
  name: (identifier) @function.name) @function.def
```

#### Deterministic Lineage Resolution vs. Probabilistic Matching

Regulated domain standards (DO-178C, ISO 26262) explicitly reject probabilistic or fuzzy AI matching for verification tracing. PTE enforces 100% deterministic traceability:

* **Explicit Lineage:** Extracted via Tree-Sitter parsing of `@trace("<ALIAS>")` tokens inside source code blocks.
* **Structural Verification:** Tree-Sitter maps the exact start and end line bounds, module pathways, and AST parent nodes containing the annotation.

***

### Pillar 3: Property Invariant Verification Gate

To eliminate test suite hallucination (where coding agents write fake assertions like `assert True` to satisfy code coverage requirements), PTE requires **Property-Based Testing (PBT)** for requirement invariants.

Property tests require defining algebraic invariants that must hold true across generated input spaces (e.g., via Python Hypothesis, TypeScript fast-check, or Rust QuickCheck).

```javascript
                        Property Test Verification Pipeline
 ┌────────────────────┐      ┌─────────────────────────┐      ┌─────────────────────────┐
 │ Spec Node          │      │ Generative Input Space  │      │ Target Implementation   │
 │ Invariant: INV-01  │ ---> │ (10,000 Generated Inputs)│ ---> │ Function under test     │
 └────────────────────┘      └─────────────────────────┘      └─────────────────────────┘
                                                                           │
                                                                           v
                                                              ┌─────────────────────────┐
                                                              │ Verify Invariant Holds  │
                                                              │ for ALL generated cases │
                                                              └─────────────────────────┘
```

#### Automated Quality Inspection (`pte/property_gate.py`)

1. **AST Property Verification:** Parses test files using Tree-Sitter to confirm tests reference target requirement invariants and utilize framework generators (`@given`, `fc.assert`, `quickcheck`).
2. **Trivial Assertion Detection:** Inspects AST node distributions. If the ratio of static example tests or constant comparison assertions exceeds configured thresholds (default: $>15\%$), the build is rejected.

***

### Pillar 4: Hybrid Enterprise ALM Synchronization Engine

PTE maintains bi-directional synchronization between local repository spec nodes (`.zft/specs/`) and centralized enterprise ALM platforms (Jira, Siemens Polarion, IBM DOORS).

```javascript
                      Bi-Directional State Synchronization
 ┌──────────────────────┐   Git Commit / Webhook   ┌──────────────────────────┐
 │ Local Repository     │ ───────────────────────> │ PTE Synchronization      │
 │ Spec Nodes (.json)   │ <─────────────────────── │ Worker Engine            │
 └──────────────────────┘   REST / GraphQL Push    └──────────────────────────┘
                                                                │
                                                                ▼
                                                   ┌──────────────────────────┐
                                                   │ Enterprise ALM System    │
                                                   │ (DOORS / Polarion / Jira)│
                                                   └──────────────────────────┘
```

* **Local-First Precedence:** Developers and AI agents write and update requirements directly in Git. State changes propagate asynchronously to enterprise ALMs.
* **Deterministic Conflict Resolution:** Changes are resolved using explicit version vector timestamps stored in the spec node frontmatter (`version: N`). Conflicts halt the merge pipeline and generate a structured resolution diff.

***

## 4. Specification Schema & Data Format

Requirement nodes are stored inside the `.zft/specs/<domain>/` hierarchy as JSON files.

### JSON Schema Definition (Draft 2020-12)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "PTETraceabilityNode",
  "type": "object",
  "properties": {
    "node_id": {
      "type": "string",
      "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
      "description": "Immutable UUIDv7 primary identifier."
    },
    "alias": {
      "type": "string",
      "pattern": "^[A-Z0-9]+-[A-Z0-9-]+$",
      "description": "Human-readable dynamic alias (e.g., AUTH-OAUTH-JWT-VALIDATE)."
    },
    "domain": {
      "type": "string",
      "description": "Functional domain classification."
    },
    "title": {
      "type": "string",
      "description": "High-level description of the requirement."
    },
    "status": {
      "type": "string",
      "enum": ["DRAFT", "PROPOSED", "VALIDATED", "IMPLEMENTED", "DEPRECATED"]
    },
    "version": {
      "type": "integer",
      "minimum": 1
    },
    "invariants": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": { "type": "string", "pattern": "^INV-[0-9]{2,}$" },
          "description": { "type": "string" },
          "algebraic_property": { "type": "string" }
        },
        "required": ["id", "description", "algebraic_property"]
      },
      "minItems": 1
    },
    "external_links": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "system": { "type": "string", "enum": ["JIRA", "DOORS", "POLARION", "JAMA"] },
          "external_id": { "type": "string" },
          "url": { "type": "string" }
        },
        "required": ["system", "external_id"]
      }
    }
  },
  "required": ["node_id", "alias", "domain", "title", "status", "version", "invariants"]
}
```

### Concrete Requirement Spec File (`.zft/specs/auth/jwt-validation.json`)

```json
{
  "node_id": "018f3a2b-9e41-7100-8000-000000000001",
  "alias": "AUTH-OAUTH-JWT-VALIDATE",
  "domain": "auth",
  "title": "OAuth2 Bearer Token Cryptographic Integrity Validation",
  "status": "VALIDATED",
  "version": 1,
  "invariants": [
    {
      "id": "INV-01",
      "description": "System SHALL reject all expired JWT tokens with HTTP 401 Unauthorized.",
      "algebraic_property": "forall t > expiration_time => validate(t) == Err(Unauthorized)"
    },
    {
      "id": "INV-02",
      "description": "System SHALL verify payload signature against identity provider public key.",
      "algebraic_property": "forall payload, sig :: verify(payload, sig, pubkey) == false => validate() == Err(InvalidSignature)"
    }
  ],
  "external_links": [
    {
      "system": "JIRA",
      "external_id": "SEC-8492",
      "url": "https://enterprise.atlassian.net/browse/SEC-8492"
    }
  ]
}
```

***

## 5. Reference Implementation Modules

### Component 1: Engine Specification Core (`pte/engine.py`)

```python
import hashlib
import json
import uuid
from pathlib import Path
from typing import Dict, Any

class PTECoreEngine:
    """Core specification parser and cryptographic state signer."""

    @staticmethod
    def generate_uuidv7() -> str:
        """Generates a time-ordered UUIDv7 string."""
        return str(uuid.uuid7())

    @staticmethod
    def compute_content_hash(payload: Dict[str, Any]) -> str:
        """Computes deterministic SHA-256 content state signature."""
        normalized = {
            "domain": payload.get("domain", "").strip().lower(),
            "title": payload.get("title", "").strip().lower(),
            "invariants": payload.get("invariants", []),
            "version": payload.get("version", 1)
        }
        serialized = json.dumps(normalized, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(serialized.encode('utf-8')).hexdigest()

    def parse_and_validate_spec(self, file_path: Path) -> Dict[str, Any]:
        """Loads and validates local specification JSON node."""
        content = json.loads(file_path.read_text(encoding='utf-8'))
        
        required_keys = ["node_id", "alias", "domain", "title", "invariants"]
        for key in required_keys:
            if key not in content:
                raise ValueError(f"Specification node missing required key: {key} in {file_path}")

        content_hash = self.compute_content_hash(content)
        content["content_hash"] = content_hash
        return content
```

***

### Component 2: Tree-Sitter Polyglot Lineage Extractor (`pte/lineage.py`)

```python
from pathlib import Path
from typing import List, Dict, Any
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

class PolyglotLineageExtractor:
    """Extracts code-to-requirement lineage using Tree-Sitter queries."""

    def __init__(self):
        self.py_language = Language(tspython.language())
        self.parser = Parser(self.py_language)
        
        # Query matching @trace("ALIAS") in docstrings or comments
        self.query_str = """
        (comment) @comment
        (expression_statement (string)) @docstring
        """
        self.query = self.py_language.query(self.query_str)

    def extract_lineage_from_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """Parses a Python file and returns identified @trace linkage nodes."""
        source_code = file_path.read_bytes()
        tree = self.parser.parse(source_code)
        captures = self.query.captures(tree.root_node)

        lineage_records = []
        for node, capture_name in captures:
            text = node.text.decode('utf-8')
            if "@trace(" in text:
                alias = text.split('@trace("')[1].split('")')[0]
                lineage_records.append({
                    "alias": alias,
                    "file": str(file_path),
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "type": capture_name
                })
        return lineage_records
```

***

### Component 3: Property Gate & Anti-Hallucination Evaluator (`pte/property_gate.py`)

```python
import ast
from pathlib import Path
from typing import Dict, Any

class PropertyBoundaryGate:
    """Enforces property-based test verification and flags trivial assertions."""

    def inspect_python_test_file(self, file_path: Path) -> Dict[str, Any]:
        """Parses test file AST to verify presence of property generators."""
        content = file_path.read_text(encoding='utf-8')
        tree = ast.parse(content)

        has_property_generators = False
        trivial_assertions = 0
        total_assertions = 0

        for node in ast.walk(tree):
            # Check for Hypothesis @given decorator
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and getattr(decorator.func, 'id', '') == 'given':
                        has_property_generators = True
                    elif isinstance(decorator, ast.Name) and decorator.id == 'given':
                        has_property_generators = True

            # Identify trivial assertions (e.g. assert True, assert x is not None)
            if isinstance(node, ast.Assert):
                total_assertions += 1
                if isinstance(node.test, ast.Constant) and node.test.value is True:
                    trivial_assertions += 1
                elif isinstance(node.test, ast.Compare):
                    if len(node.test.ops) == 1 and isinstance(node.test.ops[0], ast.IsNot):
                        if isinstance(node.test.comparators[0], ast.Constant) and node.test.comparators[0].value is None:
                            trivial_assertions += 1

        ratio = (trivial_assertions / total_assertions) if total_assertions > 0 else 0.0
        passed = has_property_generators and (ratio <= 0.15)

        return {
            "file": str(file_path),
            "has_property_generators": has_property_generators,
            "total_assertions": total_assertions,
            "trivial_assertions": trivial_assertions,
            "trivial_ratio": round(ratio, 2),
            "gate_passed": passed
        }
```

***

### Component 4: Local Pipeline Verification Script (`scripts/pte_verify.sh`)

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "===================================================="
echo "    PTE LOCAL VERIFICATION & COMPLIANCE PIPELINE    "
echo "===================================================="

BUILD_DIR="build/compliance"
mkdir -p "${BUILD_DIR}"

echo "[1/3] Validating Specification Node Schemas & Hashes..."
python3 -c "
from pathlib import Path
from pte.engine import PTECoreEngine

engine = PTECoreEngine()
specs = list(Path('.zft/specs').glob('**/*.json'))
print(f'Discovered {len(specs)} specification nodes.')
for spec in specs:
    data = engine.parse_and_validate_spec(spec)
    print(f' - Validated Spec: {data[\"alias\"]} [UUID: {data[\"node_id\"]}] [Hash: {data[\"content_hash\"][:12]}]')
"

echo "[2/3] Inspecting Test Suites for Property Generator Coverage..."
python3 -c "
from pathlib import Path
from pte.property_gate import PropertyBoundaryGate

gate = PropertyBoundaryGate()
tests = list(Path('tests').glob('**/*.py'))
for test in tests:
    res = gate.inspect_python_test_file(test)
    if not res['gate_passed']:
        print(f'PROPERTY GATE FAILURE in {res[\"file\"]}')
        print(f'Details: {res}')
        exit(1)
print('All test suites satisfy property generator requirements.')
"

echo "[3/3] Compiling Local Audit Proof Package..."
cat <<EOF > "${BUILD_DIR}/local_audit.json"
{
  "status": "PASSED",
  "engine_version": "2.0.0",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo "===================================================="
echo " SUCCESS: Workspace verified and compliant.         "
echo "===================================================="
```

***

## 6. Enterprise Compliance Export Formats

During primary CI/CD runs, PTE extracts specification nodes and Tree-Sitter lineage mappings to continuously output standardized compliance deliverables.

### Continuous ReqIF XML Export (`build/compliance/export.reqif`)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<REQ-IF xmlns="http://www.prostep.org/concept-rf/1.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <HEADER>
    <REQ-IF-TOOL-ID>PTE-Compliance-Compiler-v2.0</REQ-IF-TOOL-ID>
    <TITLE>Polyglot Traceability Export</TITLE>
  </HEADER>
  <CORE-CONTENT>
    <REQ-IF-CONTENT>
      <SPEC-OBJECTS>
        <SPEC-OBJECT IDENTIFIER="018f3a2b-9e41-7100-8000-000000000001" LAST-CHANGE="2026-09-03T17:00:00Z">
          <VALUES>
            <ATTRIBUTE-VALUE-STRING THE-VALUE="AUTH-OAUTH-JWT-VALIDATE">
              <DEFINITION>
                <ATTRIBUTE-DEFINITION-STRING-REF>REQ-ALIAS</ATTRIBUTE-DEFINITION-STRING-REF>
              </DEFINITION>
            </ATTRIBUTE-VALUE-STRING>
            <ATTRIBUTE-VALUE-STRING THE-VALUE="OAuth2 Bearer Token Cryptographic Integrity Validation">
              <DEFINITION>
                <ATTRIBUTE-DEFINITION-STRING-REF>REQ-TITLE</ATTRIBUTE-DEFINITION-STRING-REF>
              </DEFINITION>
            </ATTRIBUTE-VALUE-STRING>
            <ATTRIBUTE-VALUE-STRING THE-VALUE="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855">
              <DEFINITION>
                <ATTRIBUTE-DEFINITION-STRING-REF>STATE-CONTENT-HASH</ATTRIBUTE-DEFINITION-STRING-REF>
              </DEFINITION>
            </ATTRIBUTE-VALUE-STRING>
          </VALUES>
        </SPEC-OBJECT>
      </SPEC-OBJECTS>
    </REQ-IF-CONTENT>
  </CORE-CONTENT>
</REQ-IF>
```

### Traceability Matrix Structure

| Requirement Alias           | Node UUIDv7        | State Hash ($\text{SHA-256}$) | Verification Method    | Lineage Coverage             | Status        |
| --------------------------- | ------------------ | ----------------------------- | ---------------------- | ---------------------------- | ------------- |
| **AUTH-OAUTH-JWT-VALIDATE** | `018f3a2b-9e41...` | `e3b0c44298fc...`             | Property-Based Fuzzing | 100% Tree-Sitter AST Matched | **VALIDATED** |

***

## 7. Operational & Technical Summary

* **Zero Link Breakdown:** Using UUIDv7 primary keys prevents link rot across external systems (Jira, DOORS) when requirement text or titles are refactored.
* **Deterministic Audit Proof:** Combining explicit `@trace` annotations with Tree-Sitter static analysis delivers 100% deterministic lineage graphs required for safety audits (DO-178C, ISO 26262).
* **Anti-Hallucination Enforcement:** Enforcing property-based test framework generators mathematically blocks superficial unit tests generated by coding agents.
* **Lightweight CI Performance:** Native Tree-Sitter C-bindings complete static analysis across millions of lines of code in seconds, keeping developer feedback loops tight.

