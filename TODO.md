# TODO — get the v2 pipeline producing live output

Tracking the fix for the bug that has kept v2 at **zero output**. Started 2026-06-14.

## The bug (root cause)

The v2 agent runs the full LangGraph pipeline (~190s of real LLM calls) and then
**crashes on the DynamoDB write**:

```
TypeError: Float types are not supported. Use Decimal types instead.
  agent/lambda_handler.py  write_prediction → table.put_item(Item=item)
```

`first_try_candidates[*].probability` (`FirstTryScorerCandidate.probability`) is a
Python `float`; the boto3 DynamoDB **resource** client only accepts `Decimal`.
`upset_probability` already had a `str(...)` workaround; the candidate probabilities
did not. Result: every scheduled run (Tue/Thu/Fri) burned ~5 LLM calls then threw the
result away → 0 `v2.0` rows in `predictions`, 0 rows in `agent_traces`.

Evidence: CloudWatch `/aws/lambda/nrl-predictor-v2-agent`, stream `2026/06/12/...`.

Never caught because `tests/agent/test_graph_integration.py` stops at `graph.invoke()`
and never calls `write_prediction` — the write path was untested.

## Status / steps

- [x] Diagnose: read CloudWatch agent logs → float serialisation crash on write.
- [x] Fix `write_prediction`: added `_ddb_safe()` recursive float→Decimal converter in
      `agent/lambda_handler.py`, applied to the item before `put_item`. **(working tree, uncommitted)**
- [x] Apply `_ddb_safe()` to `write_trace` too — `trace_entries[*].input` tool-arg dicts
      can also hold floats.
- [x] Add a moto-backed test (`tests/agent/test_write_prediction.py`, 3 tests) that calls
      `write_prediction` + `write_trace` with float-bearing data, asserts persistence +
      Decimal round-trip. Confirmed moto raises the exact `TypeError` without the fix.
- [x] Gate green: `node ~/.claude/bin/gate-ci.mjs --force` → ruff clean + 34 passed.
- [ ] Commit the fix (`fix: convert floats to Decimal before DynamoDB write` + test).
- [ ] **Redeploy** the agent Lambda:
      `cd infra && AWS_DEFAULT_REGION=ap-southeast-2 cdk deploy --require-approval never`
      (deployed code is from 2026-06-10 and still has the bug).
- [ ] Smoke test ONE match (cheap, ~5 LLM calls) — pick a round with team-sheet data
      already in `teams` (e.g. a round-15 match). Needs the team sheet present, else run
      the orchestrator which scrapes+seeds first:
      ```
      aws lambda invoke --function-name nrl-predictor-v2-agent \
        --payload '{"matchId":"round-15-warriors-v-sharks","round":15}' \
        --cli-binary-format raw-in-base64-out --region ap-southeast-2 response.json && cat response.json
      ```
- [ ] Verify a `v2.0` row landed in `predictions` and a row in `agent_traces`
      (`python3 -m tools.inspector --match round-15-warriors-v-sharks`, or the dashboard
      Run monitor / Match explorer — the multi-agent + trace views should light up).
- [ ] Only then run a full round via the orchestrator (spends ~8 matches × 5 calls,
      8s stagger, budget threshold $50/mo):
      ```
      aws lambda invoke --function-name nrl-predictor-v2-orchestrator \
        --payload '{"season":2026,"round":"current"}' \
        --cli-binary-format raw-in-base64-out --region ap-southeast-2 response.json && cat response.json
      ```

## Notes

- Deployed v2 Lambdas (agent + orchestrator) last modified 2026-06-10, layer
  `nrl-predictor-v2-deps:4`. They are AFTER the 2026-06-06 Challenger/primary fixes,
  so this float crash is the remaining blocker.
- `response.json` is now gitignored (it's the `aws lambda invoke` output).
- Orchestrator is the real entrypoint: scrapes draw → writes team sheets → async
  fan-out to the agent per match (8s stagger). Single-match agent invokes require the
  team sheet to already exist in `teams`.
- Background on the empty tables: memory `project_v2_no_live_output` + `project_v2_bugs`.
