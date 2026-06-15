# TODO — get the v2 pipeline producing live output

Tracking the fix for the bug that has kept v2 at **zero output**. Started 2026-06-14.

## ✅ RESOLVED 2026-06-14 — v2 now produces live output

Two bugs fixed (float→Decimal write crash; extended-node schema coercion), redeployed,
and verified: a real run via `tools.local_invoke --aws --real-llm` wrote the first
`v2.0` prediction + a 21-entry agent_trace for `round-15-warriors-v-sharks`. The
inspector/dashboard now show 1 v2.0 row + 1 trace.

### Follow-ups (not blocking "it runs")
- [x] **Agent ran blind on team sheets** (slug vs numeric matchId). Fixed: single
      source of truth `match_id_from_url()` in `scrapers/nrl/draw.py`; both writers
      (orchestrator inline + `scrapers/nrl/team_sheet.py` lambda) now key team sheets
      on the draw slug. Regression test `tests/scrapers/test_team_sheet_id.py`. Gate: 41.
      **Requires redeploy + a fresh orchestrator scrape** to take effect on live data
      (existing round-15 sheets are numeric-keyed and now >24h stale anyway).
- [~] **Slug fix verified at write/key/test level, NOT end-to-end (2026-06-15).**
      - Regression test green (3 tests). Deployed code keys by slug: the 06-14 11:13
        round-15 write produced a real slug-keyed full sheet (`round-15-warriors-v-sharks`,
        Warriors/Sharks). Raw `get_item` with the agent's exact key {teamId: slug, round}
        returns it — read/write keys agree.
      - **But no agent run has EVER consumed a real team sheet via `get_team_sheet`.**
        Audit of every trace: pre-deploy 10:50 → "Error: No team sheet found" (slug item
        not written yet); post-deploy 11:17 → agent never called `get_team_sheet`; the
        slug-keyed round-15 sheet then went >24h stale before any agent read it.
        NOTE: trace `error` field is `None` even on tool failure — failures are serialized
        into the `output` string as `"Error: ..."`. Classify by output, not the error field.
- [ ] **Real end-to-end slug verification is blocked by data, not the fix.** Orchestrator
      run 2026-06-15 (round 16) scraped fine but every match logged "Both player lists are
      empty" — NRL hasn't named round-16 line-ups yet, so NO full slug-keyed sheet was
      written (only empty `#home`/`#away` stubs from another writer). Every agent's
      `get_team_sheet` returned "Error: No team sheet found" → ran blind. **Re-run a single
      agent once round-16 line-ups publish (~Tue, 24-48h pre-kickoff) and confirm
      `get_team_sheet` returns real data in the trace.**
- [x] **OPERATIONAL: orchestrator triple-fired** on 2026-06-15 (25 agent starts, 17
      duplicate round-16 predictions, ~3× LLM spend) — synchronous `aws lambda invoke`
      overruns the CLI's 60s read timeout → botocore retries re-run the whole handler.
      **Fixed 2026-06-15**: `_acquire_round_lock()` in `orchestrator/lambda_handler.py` — a
      conditional-write lock item in the teams table keyed on (season, round) so only the
      first run within `ORCHESTRATOR_LOCK_WINDOW_SECONDS` (default 900) proceeds; duplicates
      return `{"skipped": "locked"}` without fanning out. `force: true` overrides. Tests in
      `tests/orchestrator/test_idempotency.py` (4). **Needs redeploy.** Still prefer
      `--invocation-type Event` for manual CLI invokes regardless.
- [x] **REGRESSION: `max_tokens` ValidationError on `FinalPrediction` (Judge node)** — 4
      occurrences in the 2026-06-15 round-16 run. Same class as the prior Challenger
      max_tokens crash. **Fixed 2026-06-15** in `agent/nodes/judge.py`: bumped `max_tokens`
      1536→3072 (FinalPrediction has two prose fields) AND wrapped the structured call in a
      try/except that falls back to the primary prediction (WEAK-challenge default, softens
      confidence one tier for MODERATE/STRONG) so a parse failure can't sink the pipeline.
      Tests in `tests/agent/test_judge_node.py` (6 total). Gate green: ruff + 43 passed.
      **Needs redeploy** for the fix to take effect live.
- [ ] `get_weather` also errored (no forecast for venue/date) — separate, lower priority.
- [ ] Once scheduled runs are clean, delete the `project_v2_no_live_output` memory.

---
## Original diagnosis (kept for history)

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

## Bug #2 — Extended node validation crash (found 2026-06-14, after deploy)

The float-write fix worked (got past the write). Next blocker surfaced in
`agent/nodes/extended.py`: Haiku's structured output returned `first_try_scorer`
as a **JSON string of a candidate list** instead of a `FirstTryPrediction` object:
`ValidationError: first_try_scorer Input should be a valid dictionary or instance
of FirstTryPrediction [input_type=str]`. Non-deterministic — on 06-12 it emitted
valid structure (reached the write); on 06-14 it stringified the list.

- [x] Fix in schema (`agent/state.py`): `field_validator(mode="before")` on
      `ExtendedPrediction.first_try_scorer` — json-decodes a string, wraps a bare
      list as `{"candidates": [...]}`, clamps to top 3.
- [x] Tests (`tests/agent/test_state.py`): json-string, bare-list, >3 clamp,
      still-accepts-object. Gate green: 38 passed.
- [x] Redeployed (CDK, 2026-06-14 ~06:23 + ~08:41 UTC) — both fixes now live.
- [ ] Verify a real end-to-end run lands a `v2.0` row + trace (see local emulator below).

## Local Lambda emulation — `tools/local_invoke.py` (built 2026-06-14)

Runs the real `agent.lambda_handler` locally (no deploy) against moto or real AWS,
with mock or real LLMs. Default `python3 -m tools.local_invoke` is a free ~1s smoke
of the full read→graph→write→trace path — reproduces the write crash without a
deploy. `--aws --real-llm` runs the exact handler against real data + Anthropic
locally (the fast debug loop, ~190s, costs LLM $ but no deploy).

- [x] Built + lint-clean; default mode verified (writes a `v2.0` row with a float
      `probability` via `_ddb_safe`, plus a trace). Surfaced a real test gap: the
      mocked primary node needs BOTH `bind_tools` and `with_structured_output`
      stubbed (test_graph_integration never hit the write path).
- [ ] Run `python3 -m tools.local_invoke --aws --real-llm --match round-15-warriors-v-sharks --round 15`
      as the real verification (replaces the deployed-Lambda smoke invoke). OR
      invoke the deployed Lambda directly. Then check `tools.inspector` / dashboard.
- [ ] Once a single real run is clean, run the full round via the orchestrator.

## Notes

- Deployed v2 Lambdas (agent + orchestrator) last modified 2026-06-10, layer
  `nrl-predictor-v2-deps:4`. They are AFTER the 2026-06-06 Challenger/primary fixes,
  so this float crash is the remaining blocker.
- `response.json` is now gitignored (it's the `aws lambda invoke` output).
- Orchestrator is the real entrypoint: scrapes draw → writes team sheets → async
  fan-out to the agent per match (8s stagger). Single-match agent invokes require the
  team sheet to already exist in `teams`.
- Background on the empty tables: memory `project_v2_no_live_output` + `project_v2_bugs`.
