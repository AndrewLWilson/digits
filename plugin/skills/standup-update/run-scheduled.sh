#!/usr/bin/env bash
# Headless runner that asks Copilot CLI to draft today's standup update with
# the digits plugin's standup-update skill and save it as a dated Markdown file.
#
# Nothing installs or schedules this script; plugin installation never runs it.
# If you want it on a timer, create your own launchd or cron job.
#
# WARNING: it launches `copilot -p` unsupervised with --allow-all-tools and
# --allow-all-urls. Review those broad approvals before scheduling it.
#
# It only writes a local draft and a log. It never submits or posts the update.
#
# Environment:
#   DIGITS_STANDUP_DIR  output directory (default ~/.local/state/digits/standup)
#   DIGITS_STANDUP_TZ   time zone for the draft date (default: system local time)
set -euo pipefail
set -o noclobber

# Schedulers start with a minimal environment.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

OUT="${DIGITS_STANDUP_DIR:-$HOME/.local/state/digits/standup}"
mkdir -p "$OUT"

if [[ -n "${DIGITS_STANDUP_TZ:-}" ]]; then
  TODAY="$(TZ="$DIGITS_STANDUP_TZ" date +%Y-%m-%d)"
else
  TODAY="$(date +%Y-%m-%d)"
fi
DRAFT="$OUT/$TODAY.md"
LOG="$OUT/$TODAY.log"

if [[ -e "$DRAFT" || -L "$DRAFT" ]]; then
  echo "run-scheduled: refusing to overwrite existing draft $DRAFT" >&2
  exit 1
fi

cd "$HOME"
exec >>"$LOG" 2>&1

echo "=== Digits standup draft run for $TODAY started $(date) ==="

PROMPT="Use the digits plugin's standup-update skill (/digits:standup-update) to draft today's standup update in my configured format. \
Save the finished Markdown draft to exactly this absolute path: $DRAFT \
Do not overwrite any existing file; if that path already exists, stop and say so. \
For each progress item give its previous state and its new state; keep items that are still in review without inventing a transition. \
Do not post, send or submit the update anywhere. \
When done, reply with the path you saved."

copilot -p "$PROMPT" --allow-all-tools --allow-all-urls --log-dir "$OUT/copilot-logs"

if [[ -L "$DRAFT" || ! -f "$DRAFT" || ! -s "$DRAFT" ]]; then
  echo "run-scheduled: error: no nonempty regular draft saved at $DRAFT"
  exit 1
fi

echo "=== Digits standup draft run finished $(date) ==="
echo "Draft saved to: $DRAFT"

if command -v pbcopy >/dev/null 2>&1; then
  pbcopy <"$DRAFT" || true
fi
if command -v osascript >/dev/null 2>&1; then
  osascript -e "display notification \"Draft saved to $TODAY.md\" with title \"Digits standup\"" || true
fi
