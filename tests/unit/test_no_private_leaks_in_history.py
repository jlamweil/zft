import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True)


def _history_objects():
    """Yield (object_hash, type, path_or_None) for every object in history.

    Only objects that carry a path in `rev-list --objects` are file blobs (trees
    and commits never carry a path), so the path presence disambiguates blobs
    from tree/commit objects without a second object query.
    """
    try:
        out = _git("rev-list", "--all", "--objects")
    except subprocess.CalledProcessError:
        return
    for line in out.splitlines():
        parts = line.split(" ", 1)
        oid = parts[0]
        path = parts[1] if len(parts) > 1 else None
        yield oid, path


def _patterns():
    cod = "trace" + "agent"
    zdrv = "zcode-" + "remote-driver"
    loc = "<" + "LOCAL>"
    midwave = "zcode-midwave-" + r"[0-9]+"
    infra_host = "g" + "aia"
    email_local = "j" + "lam@"
    patterns = [
        (re.compile(r"/ho" + r"me/[A-Za-z0-9._-]+"), "owner home path"),
        (re.compile(r"\b" + re.escape(cod) + r"\b", re.IGNORECASE), "pre-rename package name"),
        (re.compile(re.escape("TRAC" + "EAGENT") + r"_", re.IGNORECASE), "legacy env-var prefix"),
        (re.compile(re.escape("dev-" + cod + "-zcode"), re.IGNORECASE), "pre-rename marketplace"),
        (re.compile(re.escape("tet" + "hys"), re.IGNORECASE), "box hostname"),
        (re.compile(re.escape("yug" + "uer" + "ten"), re.IGNORECASE), "box hostname"),
        (re.compile(r"\b" + re.escape(infra_host) + r"\b", re.IGNORECASE), "infra host"),
        (re.compile(re.escape("ntfy") + r"\.sh"), "notification host"),
        (re.compile(re.escape(zdrv), re.IGNORECASE), "private driver repo"),
        (re.compile(midwave), "private run id"),
        (re.compile(re.escape(loc)), "local sentinel"),
        (re.compile(re.escape(email_local)), "owner email local-part"),
        (re.compile(r"\b(?:INT|WQ)-0[0-9]{2,}\b"), "internal identifier"),
    ]
    return patterns


def _scan(data, scope):
    bad = []
    for pat, label in _patterns():
        if pat.search(data):
            bad.append(f"{scope}: {label} matched {pat.pattern!r}")
    return bad


def test_no_private_identifiers_in_history_blobs():
    bad = []
    seen = set()
    for oid, path in _history_objects():
        if not path:
            continue
        if oid in seen:
            continue
        seen.add(oid)
        try:
            blob = _git("cat-file", "blob", oid)
        except subprocess.CalledProcessError:
            continue
        for pat, label in _patterns():
            if pat.search(blob):
                bad.append(f"blob {oid} ({path}): {label}")
    assert not bad, "private identifiers leaked in history blobs: %r" % bad[:10]


def test_no_private_identifiers_in_commit_metadata_and_messages():
    bad = []
    log = _git("log", "--all", "--format=%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B%x1e")
    for record in log.split("\x1e"):
        if not record.strip():
            continue
        oid, an, ae, cn, ce, body = record.split("\x1f", 5)
        for pat, label in _patterns():
            for hay, field in (
                (an, "author name"),
                (ae, "author email"),
                (cn, "committer name"),
                (ce, "committer email"),
                (body, "commit message"),
            ):
                if pat.search(hay):
                    bad.append(f"commit {oid[:12]} {field}: {label} ({pat.pattern!r})")
    assert not bad, "private identifiers leaked in commit metadata/messages: %r" % bad[:10]


def test_no_private_identifiers_in_annotated_tag_objects():
    bad = []
    tags = _git("for-each-ref", "refs/tags", "--format=%(refname:short) %(objecttype)")
    for line in tags.splitlines():
        name, otype = line.split(" ", 1)
        if otype != "tag":
            continue
        tag_obj = _git("for-each-ref", f"refs/tags/{name}", "--format=%(objectname)")
        obj = _git("cat-file", "tag", tag_obj.strip())
        for pat, label in _patterns():
            if pat.search(obj):
                bad.append(f"tag {name}: {label} ({pat.pattern!r})")
            if pat.search(tag_obj):
                bad.append(f"tag {name} target: {label} ({pat.pattern!r})")
    assert not bad, "private identifiers leaked in annotated tag objects: %r" % bad[:10]


def test_no_pre_rename_paths_in_history():
    cod = "trace" + "agent"

    def _cond(p):
        p = (p or "").lower()
        return (
            "trace" in p and "agent" in p
            or "." + cod in p
            or "contracts/" + cod in p
        )

    bad = [p for _oid, p in _history_objects() if p and _cond(p)]
    assert not bad, "pre-rename paths present in history trees: %r" % bad[:10]
