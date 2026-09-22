"""Store kill-shard pins (2026-09-15 night cut, spec/store.py — 15 suspects).

spec/store.py is the read side of the contract store: where it indexes from,
what it keys on, where each node came from, and how it refuses are all
contract surface — the gates resolve load_contract on every check, and the
per-node provenance (_file) is what evidence refs cite. One pin per contract
fact, byte-exact where the fact is a message.
"""

import json

import pytest

from zft.spec.canon import canonical_hash
from zft.spec.store import Store, load_contract


def _mini_node(alias):
    return {"alias": alias, "title": alias, "status": "VALIDATED", "invariants": []}


def _seed(tmp_path):
    spec_dir = tmp_path / ".zft" / "specs" / "dsl"
    spec_dir.mkdir(parents=True)
    (spec_dir / "alpha.json").write_text(json.dumps(_mini_node("ALPHA")))
    (spec_dir / "beta.json").write_text(json.dumps(_mini_node("BETA")))


def test_store_root_round_trips_from_load(tmp_path):
    """The store keeps the root it loaded from — callers resolve manifests and
    contracts against store.root, so root=None (ctor or load tail) must red."""
    _seed(tmp_path)
    assert Store.load(tmp_path).root == tmp_path


def test_store_canonical_hash_of_is_content_hash_of_the_node(tmp_path):
    """canonical_hash_of(alias) is the content hash of that alias's node:
    equal to hashing the stored node, and differing across nodes."""
    _seed(tmp_path)
    store = Store.load(tmp_path)
    assert store.canonical_hash_of("ALPHA") == canonical_hash(store.nodes["ALPHA"])
    assert store.canonical_hash_of("ALPHA") != store.canonical_hash_of("BETA")


def test_store_records_relative_posix_provenance_per_node(tmp_path):
    """Every node carries its store-relative source path under "_file" — the
    exact key, the exact value; evidence refs cite it."""
    _seed(tmp_path)
    nodes = Store.load(tmp_path).nodes
    assert nodes["ALPHA"]["_file"] == ".zft/specs/dsl/alpha.json"
    assert nodes["BETA"]["_file"] == ".zft/specs/dsl/beta.json"


def test_store_node_without_alias_indexes_by_file_stem(tmp_path):
    """A node JSON with no alias field indexes under the file stem — the
    .get(alias, stem) default is the contract, not an implementation detail."""
    spec_dir = tmp_path / ".zft" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "anon.json").write_text(
        json.dumps({"title": "anon", "status": "VALIDATED", "invariants": []})
    )
    assert Store.load(tmp_path).aliases() == ["anon"]


def test_store_skips_stray_specs_tree_even_when_second_part_is_specs(tmp_path):
    """The .zft prefix is checked on parts[0]; a stray top-level specs/ tree
    whose second part is ALSO "specs" must stay un-indexed — only
    ".zft/specs/**" is clause store."""
    stray = tmp_path / "specs" / "specs"
    stray.mkdir(parents=True)
    (stray / "leak.json").write_text(json.dumps(_mini_node("LEAK")))
    _seed(tmp_path)
    assert Store.load(tmp_path).aliases() == ["ALPHA", "BETA"]


def test_load_contract_names_the_empty_contracts_dir(tmp_path):
    """The refusal is typed AND worded: no manifest under .zft/contracts is a
    FileNotFoundError with exactly this message (CLI surfacing and the gates'
    L0 failure text pin against this wording)."""
    (tmp_path / ".zft" / "contracts").mkdir(parents=True)
    with pytest.raises(
        FileNotFoundError,
        match=r"^no contract manifest under \.zft/contracts$",
    ):
        load_contract(tmp_path)
