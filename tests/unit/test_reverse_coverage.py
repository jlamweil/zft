"""WP-D2: baseline-diff reverse coverage — new unbound elements red the L2 gate."""
import json

from zft.gates.l2 import run_l2
from zft.lineage.extract import extract_bindings
from zft.lineage.matrix import list_all_elements, new_unbound_elements

ALIAS = "REV-D2"


def _seed(tmp_path, new_code: str) -> "object":
    spec = tmp_path / ".zft" / "specs" / "rev"
    spec.mkdir(parents=True)
    node = {
        "node_id": "018f3a2b-9e41-7100-8000-0000000000d2",
        "alias": ALIAS,
        "domain": "rev",
        "title": "reverse coverage",
        "status": "VALIDATED",
        "version": 1,
        "content_hash": "0" * 64,
        "invariants": [{
            "id": f"{ALIAS}-INV-01",
            "statement": "THE SYSTEM SHALL flag new unbound elements",
            "property": "new_unbound(x) == []",
            "check": {"kind": "test"},
        }],
        "external_links": [],
    }
    (spec / "rev-d2.json").write_text(json.dumps(node))
    contracts = tmp_path / ".zft" / "contracts"
    contracts.mkdir(parents=True)
    (contracts / "main.json").write_text(json.dumps({"meta": {"current_milestone": "v0"}}))

    src = tmp_path / "src"
    src.mkdir()
    (src / "bound.py").write_text(
        f'# @trace("{ALIAS}")\n'
        "def bound_fn():\n"
        "    return 1\n"
    )
    (src / "new.py").write_text(new_code)
    return tmp_path


def _baseline_excluding(tmp_path, excluded: str) -> list[str]:
    return [e for e in list_all_elements(tmp_path) if e != excluded]


def test_new_unbound_element_is_flagged(tmp_path):
    new_id = "src/new.py::new_unbound"
    _seed(tmp_path, "def new_unbound():\n    return 2\n")
    baseline = _baseline_excluding(tmp_path, new_id)
    baseline_file = tmp_path / ".zft" / "baseline" / "elements.json"
    baseline_file.parent.mkdir(parents=True)
    baseline_file.write_text(json.dumps({"elements": baseline}))

    elements = list_all_elements(tmp_path)
    bindings = extract_bindings(tmp_path)
    assert new_unbound_elements(elements, bindings, set(baseline)) == [new_id]

    verdict = run_l2(tmp_path)
    assert verdict.ok is False
    assert verdict.rejection["code"] == "L2_REVERSE_COVERAGE"
    assert verdict.rejection["fault"] == "implementation"


def test_new_bound_element_is_not_flagged(tmp_path):
    new_id = "src/new.py::new_bound"
    _seed(tmp_path, f'# @trace("{ALIAS}")\ndef new_bound():\n    return 2\n')
    baseline = _baseline_excluding(tmp_path, new_id)
    baseline_file = tmp_path / ".zft" / "baseline" / "elements.json"
    baseline_file.parent.mkdir(parents=True)
    baseline_file.write_text(json.dumps({"elements": baseline}))

    elements = list_all_elements(tmp_path)
    bindings = extract_bindings(tmp_path)
    assert new_unbound_elements(elements, bindings, set(baseline)) == []
    assert run_l2(tmp_path).ok


def test_missing_baseline_warns_direction_inert(tmp_path):
    """Absent baseline: the new-element direction silently skips — it must
    warn (vacuous, not complete), never flag and never pose as live."""
    _seed(tmp_path, "def new_unbound():\n    return 2\n")
    assert not (tmp_path / ".zft" / "baseline" / "elements.json").exists()
    verdict = run_l2(tmp_path)
    assert verdict.ok, "absent baseline skips the direction; it does not red the gate"
    assert any("TR-REVERSE-COVERAGE baseline absent" in w for w in verdict.warnings)


def test_seeded_baseline_clears_the_warning(tmp_path):
    _seed(tmp_path, "def new_unbound():\n    return 2\n")
    baseline_file = tmp_path / ".zft" / "baseline" / "elements.json"
    baseline_file.parent.mkdir(parents=True)
    baseline_file.write_text(json.dumps({"elements": list_all_elements(tmp_path)}))
    verdict = run_l2(tmp_path)
    assert verdict.ok
    assert not any("baseline absent" in w for w in verdict.warnings)


def test_baseline_command_writes_the_first_real_extraction(tmp_path, capsys):
    """`zft baseline` is the seeding act: one real extraction, written
    where run_l2's grandfathering direction reads it."""
    from zft.cli.main import main as cli_main
    from zft.gates.l2 import _load_baseline_elements

    _seed(tmp_path, "def new_unbound():\n    return 2\n")
    assert cli_main(["baseline", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    baseline_file = tmp_path / ".zft" / "baseline" / "elements.json"
    assert baseline_file.is_file()
    doc = json.loads(baseline_file.read_text())
    assert doc["elements"] == list_all_elements(tmp_path)
    assert out["elements"] == len(doc["elements"])
    assert _load_baseline_elements(tmp_path) == set(doc["elements"])
    verdict = run_l2(tmp_path)
    assert verdict.ok
    assert not any("baseline absent" in w for w in verdict.warnings)


def test_baseline_command_on_elementless_tree_warns_inline(tmp_path, capsys):
    """Zero extracted elements is honest but must not read as success silently:
    the report carries the warning in-band (one JSON line, machine-readable)."""
    from zft.cli.main import main as cli_main

    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli_main(["baseline", str(empty)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["elements"] == 0
    assert "warning" in out
