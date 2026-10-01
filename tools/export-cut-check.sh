#!/usr/bin/env bash
# tools/export-cut-check.sh — the public-cut safety gate.
#
# Answers one question: is everything tracked in the cut safe to be public?
# Run it from the cut root (or pass the path) after syncing and pruning,
# before `git add`/commit/push.
#
# The lab never runs this on itself (the lab is private by definition); it is
# the gate for the *derived* repo only. ALLOWLIST below is the single source
# of truth for what may ship — keep it in sync with the rsync ship list in
# docs/PUBLISH-RUNBOOK.md; a mismatch fails loudly, by design, so a new
# public path has to be added here consciously rather than leaking out.
#
# Hard failures block the push. Warnings are machine-local context that is
# not a leak today but should be scrubbed so the next export is clean.
#
# Usage:  bash tools/export-cut-check.sh [--fix] [cut-root]
#   --fix  untrack (git rm --cached) every tracked path outside the
#          allowlist, then verify. Use it after pruning: it is how stray
#          internal docs that a previous blanket add committed get removed
#          from the cut for good.
# Exit:   0 = safe to push · 1 = leak found, do not push

set -uo pipefail

ROOT="${1:-.}"
FIX=0
[ "${1:-}" = "--fix" ] && { FIX=1; shift; ROOT="${1:-.}"; }
cd "$ROOT" || { echo "FATAL: cannot cd to $ROOT"; exit 1; }

ALLOWLIST=(
  src tests designs gates plugins .opencode
  .zft/specs .zft/contracts .zft/baseline
  .github/ISSUE_TEMPLATE .github/PULL_REQUEST_TEMPLATE.md
  .github/CONTRIBUTING.md .github/CODE_OF_CONDUCT.md .github/SECURITY.md
  oracle_ID-CONTENT-CHANGE.py oracle_TR-DETERMINISTIC-EXTRACTION.py
  oracle_CAPABILITY-CLASSIFICATION.py
  packages/opencode-zft
  README.md CHANGELOG.md CITATION.cff LICENSE pyproject.toml
  .pre-commit-config.yaml .pre-commit-hooks.yaml .gitignore CONTEXT.md
  docs/AI-REQUIREMENTS.md docs/BRANDING.md docs/ISO-CONFORMANCE.md
  docs/KNOWN-GAPS.md docs/POSITIONING.md docs/research docs/RUNBOOK.md
)

fails=0
warns=0
fail() { printf 'FAIL  %s\n' "$*"; fails=$((fails + 1)); }
warn() { printf 'WARN  %s\n' "$*"; warns=$((warns + 1)); }

# A path ships only if it is, or sits under, an allowlist entry.
ok() {
  local p="$1" a
  for a in "${ALLOWLIST[@]}"; do
    [ "$p" = "$a" ] && return 0
    case "$p" in "$a"/*) return 0 ;; esac
  done
  return 1
}

# Everything tracked or staged — i.e. what a commit would actually ship.
mapfile -t paths < <({ git ls-files; git diff --cached --name-only --diff-filter=d; } | sort -u)

if [ "$FIX" -eq 1 ]; then
  removed=0
  for p in "${paths[@]}"; do
    ok "$p" || { git rm -q --cached -- "$p" 2>/dev/null && removed=$((removed + 1)); }
  done
  echo "== 0/8  --fix untracked $removed path(s) outside the public set"
  mapfile -t paths < <({ git ls-files; git diff --cached --name-only --diff-filter=d; } | sort -u)
fi

echo "== 1/8  allowlist: every tracked/staged path is public-set"
for p in "${paths[@]}"; do
  ok "$p" || fail "outside the public set: $p (add it to the ship list or delete it)"
done
[ "$fails" -eq 0 ] && echo "  ok  $(printf '%s\n' "${paths[@]}" | grep -c .) paths, all inside the public set"

echo "== 2/8  no pre-rename paths"
for p in "${paths[@]}"; do
  case "$p" in
    *[Tt][Rr][Aa][Cc][Ee][Aa][Gg][Ee][Nn][Tt]*) fail "path names the pre-rename package: $p" ;;
  esac
done

echo "== 3/8  no TRACEAGENT_ env-var remnants (the rename dropped every fallback)"
if git grep -nIE 'TRACEAGENT_' >/tmp/eccgrep 2>/dev/null; then
  while IFS= read -r line; do fail "TRACEAGENT_ still referenced: $line"; done </tmp/eccgrep
else
  echo "  ok  none"
fi

echo "== 4/8  no machine paths or credential-shaped strings"
if git grep -nIE '/home/jlam|/home/lam/|jlam@|unistra|ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{40,}' >/tmp/eccgrep 2>/dev/null; then
  while IFS= read -r line; do fail "machine-local or secret-shaped: $line"; done </tmp/eccgrep
else
  echo "  ok  none"
fi

echo "== 5/8  warnings: machine context worth scrubbing"
# Hostnames of the owner's boxes. Harmless alone, but no public file should
# carry internal infrastructure context; promote these to FAIL once the
# 2026-09-22 comment scrub has been exported.
if git grep -niE 'tethys|yuguerten' >/tmp/eccgrep 2>/dev/null; then
  while IFS= read -r line; do warn "machine hostname in shipped content: $line"; done </tmp/eccgrep
fi
# The a1-compat module fallback in the lint-gate plugin. Intentional while
# anyone still runs the published 0.2.0a1 wheel; delete it once a1 users have
# migrated, so the rename leaves no trace at all.
if git grep -nF 'traceagent.cli.main' >/tmp/eccgrep 2>/dev/null; then
  while IFS= read -r line; do warn "intentional a1 fallback, migrate then remove: $line"; done </tmp/eccgrep
fi
[ "$warns" -eq 0 ] && echo "  ok  none"

echo "== 6/8  reverse-coverage baseline covers only this tree"
# Checked on disk as well as in the index: the baseline is force-added
# (the lab gitignores it), so an unstaged copy would otherwise slip past.
if [ -f .zft/baseline/elements.json ]; then
  if grep -nE '"(private|scratch|paper|jobs)/' .zft/baseline/elements.json >/tmp/eccbase 2>/dev/null; then
    while IFS= read -r line; do fail "baseline enumerates an internal tree: $line"; done </tmp/eccbase
    fail "re-seed the baseline on the cut (zft baseline .); never copy the lab's"
  else
    echo "  ok  no internal paths in the baseline ($(grep -c '"' .zft/baseline/elements.json) element lines)"
  fi
else
  warn ".zft/baseline/elements.json missing — zft check cannot evaluate reverse coverage"
fi

echo "== 7/8  package identity"
if ! git grep -qE '^name = "zft"' -- pyproject.toml; then
  fail 'pyproject.toml does not declare name = "zft"'
fi
if git grep -qiE 'traceagent' -- pyproject.toml; then
  fail "pyproject.toml still mentions the pre-rename package"
fi
if ! git grep -qE 'zft = "zft\.cli\.main:main"' -- pyproject.toml; then
  fail 'pyproject.toml console script is not zft = "zft.cli.main:main"'
fi
echo "  ok  name zft, sole console script zft"

echo "== 8/8  markdown link integrity (relative links resolve inside the public set)"
# A link that resolves in the lab but dangles in the cut is a published bug:
# the allowlist prunes internal docs, and a README or skill page still
# pointing at them ships broken. Resolve each link, then require the target
# to be a path the allowlist admits — the same standard as tracked files.
md_broken=0
while IFS= read -r -d '' f; do
  dir="${f%/*}"; [ "$dir" = "$f" ] && dir="."
  while IFS= read -r target; do
    case "$target" in http://*|https://*|mailto:*|\#*) continue ;; esac
    target="${target%%#*}"; target="${target%%\?*}"
    [ -z "$target" ] && continue
    root="$PWD"; rel="$(cd "$dir" && realpath -m --relative-to="$root" "$target" 2>/dev/null)"
    if [ -z "$rel" ] || ! ok "$rel"; then
      fail "broken or non-public link: $f -> $target"
      md_broken=$((md_broken + 1))
    fi
  done < <(grep -ohE '\]\(([^)]+)\)' "$f" | sed -E 's/^\]\(//; s/\)$//')
done < <(git ls-files -z '*.md')
[ "$md_broken" -eq 0 ] && echo "  ok  every relative markdown link resolves inside the public set"

# Untracked files a blanket `git add -A` would scoop up. The runbook adds by
# allowlist, so this should stay empty; flaging it catches a future blanket add.
while IFS= read -r p; do
  [ -z "$p" ] && continue
  p="${p#?? }"; p="${p#\"}"; p="${p%\"}"
  ok "$p" || warn "untracked and outside the public set (blanket add would ship it): $p"
done < <(git status --porcelain --untracked-files=all | grep '^??')

# The self-check is the last word on internal consistency. It needs a zft
# executable; the runbook documents the wheel-unzip fallback for hosts
# without one.
ZFT_BIN="${ZFT_BIN:-}"
ZFT="$ZFT_BIN"
[ -z "$ZFT" ] && command -v zft >/dev/null 2>&1 && ZFT=zft
if [ -z "$ZFT" ] && [ -x .venv/bin/python ]; then
  if .venv/bin/python -c 'import zft' >/dev/null 2>&1; then
    ZFT=".venv/bin/python -m zft.cli.main"
  fi
fi
if [ -n "$ZFT" ]; then
  echo "== self-check ($ZFT)"
  if $ZFT lint . >/tmp/ecclint 2>&1 && $ZFT check . >/tmp/ecccheck 2>&1; then
    echo "  ok  lint + check green"
  else
    fail "self-check failed (see /tmp/ecclint, /tmp/ecccheck)"
    tail -5 /tmp/ecccheck 2>/dev/null | sed 's/^/       /'
  fi
else
  warn "no zft executable found — lint/check skipped (runbook § wheel-unzip fallback)"
fi

echo
if [ "$fails" -gt 0 ]; then
  echo "RESULT: FAIL — $fails hard failure(s), $warns warning(s). Do not push."
  exit 1
fi
echo "RESULT: PASS — $warns warning(s), 0 hard failures. Safe to push."
