#!/usr/bin/env bash
# Print Jira issues assigned to the current user and updated recently, as a
# JSON array of {key, summary, status, updated, type, priority}.
#
# Usage: fetch-jira-activity.sh [since-days] [jira-site]
#   since-days  whole number of days to look back (default 1)
#   jira-site   bare hostname such as your-company.atlassian.net; defaults to
#               the DIGITS_JIRA_SITE environment variable
#   DIGITS_JIRA_PRIORITY_LABEL (optional) also includes open issues carrying
#               this label and marks them with "priority": true
#
# Requirements: bash, jq, curl and the macOS `security` tool.
#
# One-time setup, done by you in your own terminal (never paste it into a chat):
#   1. Create an API token in your Atlassian account settings
#      (Security -> API tokens).
#   2. Store it in the login Keychain:
#        security add-generic-password -s digits-standup-jira -a jira \
#          -w '{"email": "<you@example.com>", "api_token": "<api-token>"}'
# The Keychain item name and the placeholders above are not secrets. The secret
# reaches curl only on stdin, never on a command line or in output.
#
# This is a bounded search for headless runs; it does not replace a full
# ticket reconciliation through an interactive tracker integration, and it must
# not be used as a fallback when interactive tracker authentication fails.
set -euo pipefail

SERVICE="digits-standup-jira"

fail() {
  echo "fetch-jira-activity: $*" >&2
  exit 1
}

days="${1:-1}"
if [[ ! "$days" =~ ^[0-9]+$ ]]; then
  fail "since-days must be a whole number of days (got '$days')."
fi

site="${2:-${DIGITS_JIRA_SITE:-}}"
if [[ -z "$site" ]]; then
  fail "no Jira site configured; pass it as the second argument or set DIGITS_JIRA_SITE (for example your-company.atlassian.net)."
fi
if [[ ! "$site" =~ ^[A-Za-z0-9.-]+$ ]]; then
  fail "the Jira site must be a bare hostname without scheme or path (got '$site')."
fi

label="${DIGITS_JIRA_PRIORITY_LABEL:-}"
if [[ -n "$label" && ! "$label" =~ ^[A-Za-z0-9_.-]+$ ]]; then
  fail "DIGITS_JIRA_PRIORITY_LABEL may contain only letters, digits, '_', '.' and '-'."
fi

credentials="$(security find-generic-password -s "$SERVICE" -w 2>/dev/null || true)"
if [[ -z "$credentials" ]]; then
  {
    echo "fetch-jira-activity: no Jira credentials found in the Keychain item '$SERVICE'."
    echo "Set it up once in your own terminal (placeholders shown):"
    echo "  security add-generic-password -s $SERVICE -a jira -w '{\"email\": \"<you@example.com>\", \"api_token\": \"<api-token>\"}'"
  } >&2
  exit 1
fi

if ! curl_config="$(printf '%s' "$credentials" | jq -er '
    if (.email | type) == "string" and (.email | length) > 0
       and (.api_token | type) == "string" and (.api_token | length) > 0
    then "user = " + ((.email + ":" + .api_token) | tojson)
    else error("incomplete")
    end' 2>/dev/null)"; then
  fail "the Keychain item '$SERVICE' must hold JSON with non-empty \"email\" and \"api_token\" strings."
fi
unset credentials

if [[ -n "$label" ]]; then
  jql="assignee = currentUser() AND (updated >= -${days}d OR (labels = \"${label}\" AND statusCategory != Done)) ORDER BY updated DESC"
else
  jql="assignee = currentUser() AND updated >= -${days}d ORDER BY updated DESC"
fi

response="$(printf '%s\n' "$curl_config" | curl -sf --config - -G \
  "https://${site}/rest/api/3/search/jql" \
  --data-urlencode "jql=${jql}" \
  --data-urlencode "fields=summary,status,updated,issuetype,labels" \
  --data-urlencode "maxResults=30")"
unset curl_config

jq --arg label "$label" '[
  (.issues // [])[] | {
    key: .key,
    summary: .fields.summary,
    status: .fields.status.name,
    updated: .fields.updated,
    type: .fields.issuetype.name,
    priority: ($label != "" and any((.fields.labels // [])[]; . == $label))
  }
]' <<<"$response"
