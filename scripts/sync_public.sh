#!/usr/bin/env bash
# Sync the private repo to the sanitized public mirror (emg-rag-public).
#
# WO19: allowlist + transform + guard, snapshot commits. Nothing that is not
# named in deploy/public_allowlist.txt leaves the private repo; every allowed
# text file is rewritten by scripts/public_transform.py (employee pseudonyms,
# customer names / contact data / EMG dollar figures redacted, server IP
# redacted) and the result must pass scripts/public_scan.py, or nothing is
# pushed and this script exits 1. Each run adds one snapshot commit to the
# public repo's main branch (no history replay: the private history holds
# customer data and must never be mirrored again).
#
# Requires: private/pii_terms.json + private/shingles.txt (gitignored; built
# on the server by the WO19 term builder) and push access to the public repo.
#
#   bash scripts/sync_public.sh                 # build, guard, push
#   bash scripts/sync_public.sh --dry-run DIR   # build + guard into DIR, no push
#   PUBLIC_EMPLOYEE_NAMES=real bash scripts/sync_public.sh   # keep real employee names (default: pseudonym)

set -euo pipefail

PUBLIC_URL="${PUBLIC_URL:-https://github.com/SanyaBoroda4/emg-rag-public.git}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python}"

dry=""
if [ "${1:-}" = "--dry-run" ]; then dry="${2:?--dry-run needs a target directory}"; fi

for f in private/pii_terms.json private/shingles.txt; do
  [ -f "$ROOT/$f" ] || { echo "missing $f (build it with the WO19 term builder); nothing pushed" >&2; exit 1; }
done
if [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]; then
  echo "private working tree has uncommitted changes; commit and push first" >&2; exit 1
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
sha=$(git -C "$ROOT" rev-parse --short HEAD)

git clone --quiet "$ROOT" "$tmp/src"          # tracked files at HEAD, nothing else
"$PY" "$ROOT/scripts/public_transform.py" --src "$tmp/src" --out "$tmp/pub"

# guard: any customer, contact, note-text or secret hit means nothing leaves
if ! "$PY" "$ROOT/scripts/public_scan.py" tree "$tmp/pub"; then
  echo "GUARD FAILED: the transformed tree still contains guarded content; nothing pushed" >&2
  exit 1
fi

if [ -n "$dry" ]; then
  mkdir -p "$dry"; rm -rf "${dry:?}"/*; cp -r "$tmp/pub/." "$dry/"
  echo "dry run: sanitized tree at $dry (private $sha); nothing pushed"
  exit 0
fi

git clone --quiet "$PUBLIC_URL" "$tmp/pubrepo"
cd "$tmp/pubrepo"
git rm -rq --quiet . 2>/dev/null || true
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -r "$tmp/pub/." .
git add -A
if git diff --cached --quiet; then
  echo "public mirror already up to date with private $sha"
  exit 0
fi
git commit --quiet -m "sync: private $sha" -m "Allowlisted, transformed snapshot (scripts/public_transform.py); see PUBLIC_MANIFEST.md."
git push --quiet "$PUBLIC_URL" HEAD:main
echo "public mirror synced: $PUBLIC_URL (private $sha)"
