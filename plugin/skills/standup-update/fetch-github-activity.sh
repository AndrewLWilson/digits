#!/usr/bin/env bash
# Print the current user's recently updated pull requests as one JSON array.
#
# Usage: fetch-github-activity.sh [since-date]
#   since-date  YYYY-MM-DD (or any value `gh search --updated` accepts);
#               defaults to yesterday.
#
# Read-only. Requires `gh` (already logged in) and `jq`. Each search row is
# enriched with live details from `gh pr view`; if any detail lookup fails the
# script stops instead of emitting partial search metadata.
set -euo pipefail

if [[ $# -ge 1 && -n "$1" ]]; then
  since="$1"
else
  since="$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d yesterday +%Y-%m-%d)"
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "fetch-github-activity: the GitHub CLI (gh) is not on PATH." >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "fetch-github-activity: gh is not authenticated; run 'gh auth login' yourself, then retry." >&2
  exit 1
fi

rows="$(gh search prs --author @me --updated ">=${since}" -L 50 \
  --json number,repository,state,title,updatedAt,url)"

count="$(jq 'length' <<<"$rows")"
merged="[]"
for ((i = 0; i < count; i++)); do
  row="$(jq -c ".[$i]" <<<"$rows")"
  number="$(jq -r '.number' <<<"$row")"
  repo="$(jq -r '.repository.nameWithOwner' <<<"$row")"
  if ! detail="$(gh pr view "$number" --repo "$repo" \
    --json number,title,state,reviewDecision,isDraft,url,body)"; then
    echo "fetch-github-activity: could not read ${repo}#${number}; activity collection stopped." >&2
    exit 1
  fi
  merged="$(jq -c --argjson row "$row" --argjson detail "$detail" '. + [($row * $detail)]' <<<"$merged")"
done

jq '.' <<<"$merged"
