# CLAUDE.md — nrl-predictor2

Multi-agent v2 rebuild of the NRL predictor using LangGraph StateGraph.

## Commands

```bash
# Install (editable, with dev dependencies)
pip install -e ".[dev]" --break-system-packages

# Run all tests
python3 -m pytest

# Run agent tests only
python3 -m pytest tests/agent/ -v
```

Tests use moto for DynamoDB mocks. Node tests mock LLMs with `unittest.mock.MagicMock`.

## Architecture

Five-node LangGraph pipeline per match:

```
match_id → [Router] → [Primary] → [Challenger] → [Judge] → [Extended] → DynamoDB
```

| Node | Model | Role |
|---|---|---|
| Router | Haiku | Classifies EASY/CONTESTED/COMPLEX, selects primary model |
| Primary | Haiku or Sonnet | ReAct tool loop, 12-tool access, 8-step CoT, produces PrimaryPrediction |
| Challenger | Sonnet (always) | Argues opposite case, rates strength WEAK/MODERATE/STRONG |
| Judge | Sonnet | Weighs both sides using challenge_strength rules, produces FinalPrediction |
| Extended | Haiku | First-try scorer candidates, margin bracket, upset probability |

### State (agent/state.py)

`MatchPredictionState` TypedDict carries all data between nodes. Key fields:
- `match_context` — raw context dict from `load_match_context()`
- `difficulty` / `primary_model` / `challenger_model` — set by Router
- `primary_prediction: PrimaryPrediction` — set by Primary
- `challenge: Challenge` — set by Challenger
- `final_prediction: FinalPrediction` — set by Judge
- `extended: ExtendedPrediction` — set by Extended
- `agent_trace: list[TraceEntry]` — tool call audit log

### Node testability

Each node is created via a factory (`make_router_node(llm=None)`, etc.).
Pass an `llm=MagicMock()` to inject a fake LLM in tests. The graph factory
`build_graph(router_llm=..., ...)` accepts per-node LLM overrides.

### Tools (agent/tools/)

LangChain `@tool` wrappers around the same DynamoDB-backed implementations as v1.
Implementation functions have underscore prefix (`_get_team_sheet`) and accept
`table=None` for moto injection in lower-level tests.

`agent/tools/__init__.py` exports `ALL_TOOLS` — the list bound to the Primary node.

## DynamoDB additions

New fields added to each prediction item in the `predictions` table:
- `agent_difficulty` — EASY / CONTESTED / COMPLEX
- `difficulty_rationale` — Router's reasoning
- `primary_accepted` — bool (did Judge side with Primary)
- `challenge_strength` — WEAK / MODERATE / STRONG
- `primary_reasoning` — raw Primary reasoning before Judge
- `judge_rationale` — Judge's ruling explanation
- `first_try_candidates` — list of top 3 first-try scorer candidates
- `margin_bracket` — "1-5" | "6-12" | "13-20" | "21+"
- `key_player_to_watch` — name + reason
- `upset_probability` — float 0.0–1.0

New `agent_traces` table: PK=matchId, SK=generatedAt, full tool call log.

## CDK deploy

```bash
# One-time setup
pip3 install aws-cdk-lib constructs --break-system-packages

# Secrets must exist in Secrets Manager before first deploy
aws secretsmanager create-secret --name nrl-predictor/anthropic-api-key --secret-string "sk-ant-..."
aws secretsmanager create-secret --name nrl-predictor/tavily-api-key --secret-string "tvly-..."

# Bootstrap CDK (once per account/region)
AWS_DEFAULT_REGION=ap-southeast-2 cdk bootstrap

# Deploy from infra/
cd infra
AWS_DEFAULT_REGION=ap-southeast-2 cdk deploy --require-approval never
```

The v2 stack imports v1 DynamoDB tables by name (does NOT recreate them).
It adds only `agent_traces` as a new table.

### Manual invocation

```bash
# Full round (orchestrator scrapes draw → fans out to agent per match)
aws lambda invoke --function-name nrl-predictor-v2-orchestrator \
  --payload '{"season": 2026, "round": "current"}' \
  --cli-binary-format raw-in-base64-out --region ap-southeast-2 \
  response.json && cat response.json

# Single match (agent only)
aws lambda invoke --function-name nrl-predictor-v2-agent \
  --payload '{"matchId": "20260115", "round": 15}' \
  --cli-binary-format raw-in-base64-out --region ap-southeast-2 \
  response.json && cat response.json

# Tail logs
aws logs tail /aws/lambda/nrl-predictor-v2-agent --follow --region ap-southeast-2
```

## Shadow mode

v2 runs alongside v1 for 2-3 rounds:
1. v2 orchestrator fires 4 minutes after v1 orchestrator (staggered EventBridge rules)
2. v2 predictions land in the same `predictions` table (identifiable by `prompt_version = "v2.0"`)
3. v1 API continues to serve frontend — only the most recent prediction per match is served,
   so v2 predictions don't affect the live site until you switch the API Lambda
4. Compare accuracy via the existing scoring + metrics pipeline

## Team & match identity (canonical representation)

The single source of truth is `common/` (shipped to every Lambda via the whole-repo asset):

- **Team identity** — a team is *always* the lowercase slug (`sea-eagles`) internally. The NRL
  `nickName`, full names, odds-API names and LLM free text are inbound forms that **must** be
  `common.teams.to_slug()`'d at the boundary before they touch a table, tool arg, or comparison.
  Display strings come from `common.teams.display()`. Data lives in `common/team_registry.json`.
  *Invariant: no raw team name is written to a table or passed to a tool — slug at the boundary.*
- **Match identity** — `matchId` is the round-qualified slug `round-<N>-<home>-v-<away>` from
  `common.match_id` (`match_id_from_url` / `match_id`). **Every join is round-aware** (by matchId or
  roundNumber); never join on a bare team-pair (that produced bogus cross-round results).

Plans: `docs/team-identity-plan.md`, `docs/matchid-identity-plan.md`. One-off DB migration:
`scripts/migrate_identity.py {teams,matchids}` (dry-run by default; `--apply` to write).

## Important constraints

Inherits all v1 constraints (see v1/CLAUDE.md). Additional:
- **Betting odds are never passed to any agent node.** The odds join happens at API response time.
- **Rate limit**: Haiku + Sonnet calls stagger via orchestrator (8s between match invocations).
  The v2 agent uses ~3x more tokens than v1 (5 LLM calls vs 1 loop). Budget threshold default $50/month.
- The graph is compiled once at Lambda cold start (`get_app()` caches the compiled graph).
- All node tests use mocked LLMs — never hit the real Anthropic API in tests.
