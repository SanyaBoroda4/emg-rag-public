#!/usr/bin/env bash
# Sync the private repo to the sanitized public mirror (emg-rag-public).
#
# Rewrites the FULL history on every run with git-filter-repo:
#   * the server IP is replaced everywhere (including in this script's own
#     public copy — the replacement line below self-redacts in the mirror)
#   * early commits with the placeholder author email are re-attributed to
#     the real GitHub noreply address so they count as contributions
# filter-repo is deterministic, so unchanged history rewrites to identical
# commit hashes and the force-push only ever appends new commits.
#
# Run after every push to the private repo:  bash scripts/sync_public.sh
# Requires: git-filter-repo (pip install git-filter-repo), push access.

set -euo pipefail

PRIVATE_URL="https://github.com/SanyaBoroda4/emg-rag.git"
PUBLIC_URL="https://github.com/SanyaBoroda4/emg-rag-public.git"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

git clone --quiet "$PRIVATE_URL" "$tmp/repo"

cat > "$tmp/replacements.txt" <<'EOF'
SERVER_IP_REDACTED==>SERVER_IP_REDACTED
EOF

cat > "$tmp/mailmap.txt" <<'EOF'
Alex Sorokin <83870702+SanyaBoroda4@users.noreply.github.com> <your-github-email@example.com>
EOF

cd "$tmp/repo"
git filter-repo --quiet --replace-text "$tmp/replacements.txt" \
    --mailmap "$tmp/mailmap.txt"
git push --quiet --force "$PUBLIC_URL" main

echo "public mirror synced: $PUBLIC_URL"
