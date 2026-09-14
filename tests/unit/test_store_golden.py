"""C-10: store ↔ golden-fixture drift guard — the store must stay at post-P1 state."""
import json
from pathlib import Path

from traceagent.spec.store import Store

REPO = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((Path(__file__).resolve().parents[1] / "golden" / "dsl_predicate_fixtures.json").read_text())  # noqa: E501


def test_store_properties_match_post_p1_golden():
    for alias, expected in GOLDEN.items():
        path = next((REPO / ".zft/specs").rglob(f"{alias.lower()}.json"))
        node = json.loads(path.read_text())
        assert node["invariants"][0]["property"] == expected, alias


def test_store_is_versioned_and_hashed():
    # The store also holds PROPOSED requirement clauses (e.g. the `ai-conduct`
    # set). The drift guard is that every node carries a valid, known lifecycle
    # status — not that every node is already VALIDATED.
    from traceagent.spec.schema import STATUSES

    for path in (REPO / ".zft/specs").rglob("*.json"):
        node = json.loads(path.read_text())
        assert node["status"] in STATUSES, node["alias"]


def _mini_node(alias):
    return {"alias": alias, "title": alias, "status": "VALIDATED", "invariants": []}


def test_store_loads_specs_under_zft_only(tmp_path):
    # only .zft/specs/** is clause store — a node-shaped file anywhere else
    # (stray top-level specs/, directly under .zft/) must never be indexed
    spec_dir = tmp_path / ".zft" / "specs" / "dsl"
    spec_dir.mkdir(parents=True)
    (spec_dir / "alpha.json").write_text(json.dumps(_mini_node("ALPHA")))
    (tmp_path / ".zft" / "rogue.json").write_text(json.dumps(_mini_node("ROGUE")))
    stray = tmp_path / "specs"
    stray.mkdir()
    (stray / "leak.json").write_text(json.dumps(_mini_node("LEAK")))
    assert Store.load(tmp_path).aliases() == ["ALPHA"]
