#!/usr/bin/env bash
# Local daily driver for the NRL v2 predictor.
#
#   Refreshes supporting data, scores the last completed round (auto-derived), then
#   fires the v2 orchestrator to generate predictions for the current round. Designed
#   to be safe to run daily from cron: every step is idempotent.
#
#     ./scripts/daily_update.sh                 # full daily cycle, rounds auto-derived
#     SCORE_ROUND=16 ./scripts/daily_update.sh  # force-score a specific round instead
#
# The orchestrator scrapes the draw + team sheets itself and holds a per-round lock,
# so re-runs within the lock window no-op. The data guard added in agent/lambda_handler.py
# means matches whose line-ups aren't named yet are skipped, not predicted blind — so it
# is fine to run this every day; predictions land once the NRL publishes teams (~Tue).
set -euo pipefail

export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-ap-southeast-2}"
SEASON="${SEASON:-2026}"

fire() {  # fire <function-name> <json-payload>   (async; returns immediately)
  aws lambda invoke --function-name "$1" \
    --invocation-type Event \
    --cli-binary-format raw-in-base64-out \
    --payload "$2" /dev/null >/dev/null
  echo "  fired $1 $2"
}

HERE="$(dirname "$0")"

echo "[1/3] refreshing ladder (fixes the missing ladder#${SEASON}/current item)"
fire nrl-predictor-ladder-scraper "{\"season\": ${SEASON}}"

# Determine the round being predicted and the most recent finished round. The current
# round's matches are likely unplayed, so we scrape results for it AND the one before,
# then let round_state derive which is actually complete (majority FullTime in results).
CURRENT="$(AWS_REGION=$AWS_DEFAULT_REGION python3 "$HERE/round_state.py" current || true)"
echo "[2/3] scoring the last completed round (current predicted round: ${CURRENT:-unknown})"
if [[ -n "${SCORE_ROUND:-}" ]]; then
  TARGET="$SCORE_ROUND"
  echo "  SCORE_ROUND override -> round ${TARGET}"
elif [[ -n "$CURRENT" ]]; then
  # Refresh results for the current and previous round so completion is up to date.
  for R in "$CURRENT" $((CURRENT - 1)); do
    [[ "$R" -ge 1 ]] || continue
    aws lambda invoke --function-name nrl-predictor-results-scraper \
      --cli-binary-format raw-in-base64-out \
      --payload "{\"season\": ${SEASON}, \"round\": ${R}}" /dev/null >/dev/null
    echo "  scraped results for round ${R}"
  done
  TARGET="$(AWS_REGION=$AWS_DEFAULT_REGION python3 "$HERE/round_state.py" scorable "$CURRENT" $((CURRENT - 1)) || true)"
else
  echo "  no predictions found — skipping scoring"
fi

if [[ -n "${TARGET:-}" ]]; then
  echo "  scoring round ${TARGET}"
  python3 "$HERE/score_round.py" --round "$TARGET" --season "${SEASON}"
else
  echo "  no completed round to score yet"
fi

echo "[3/3] generating predictions for the current round"
# Async: the orchestrator runs ~73s, which overruns the CLI's 60s read timeout and
# triggers duplicate fan-out if invoked synchronously (see TODO.md). Event-type avoids it.
fire nrl-predictor-v2-orchestrator "{\"season\": ${SEASON}, \"round\": \"current\"}"

echo "done. tail with: aws logs tail /aws/lambda/nrl-predictor-v2-orchestrator --follow --region ${AWS_DEFAULT_REGION}"
