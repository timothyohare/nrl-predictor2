# nrl-predictor2

> [!IMPORTANT]
> **This repository has moved.** As of 2026-06-29, v2 lives in the monorepo
> **[timothyohare/nrl-predictor](https://github.com/timothyohare/nrl-predictor)**
> under `v2/`, sharing one copy of `common/`, `scrapers/`, and `scoring/` with v1.
> Both fleets now deploy from there. This repo is **archived** (read-only) and kept
> only for history. Do not commit here — open changes against the monorepo.

Multi-agent v2 rebuild of the NRL predictor. Uses a five-node LangGraph pipeline (Router → Primary → Challenger → Judge → Extended) to produce match predictions, running in shadow mode alongside v1.

## Architecture

```
match_id → [Router] → [Primary] → [Challenger] → [Judge] → [Extended] → DynamoDB
```

| Node | Model | Role |
|---|---|---|
| Router | Haiku | Classifies EASY/CONTESTED/COMPLEX, selects primary model |
| Primary | Haiku or Sonnet | ReAct tool loop, 12-tool access, produces PrimaryPrediction |
| Challenger | Sonnet | Argues opposite case, rates strength WEAK/MODERATE/STRONG |
| Judge | Sonnet | Weighs both sides, produces FinalPrediction |
| Extended | Haiku | First-try scorer candidates, margin bracket, upset probability |

## Prerequisites

- AWS credentials configured (`aws configure` or `AWS_PROFILE`)
- Anthropic and Tavily API keys stored in Secrets Manager:

```bash
aws secretsmanager create-secret --name nrl-predictor/anthropic-api-key --secret-string "sk-ant-..."
aws secretsmanager create-secret --name nrl-predictor/tavily-api-key --secret-string "tvly-..."
```

- CDK bootstrapped (once per account/region):

```bash
pip install aws-cdk-lib constructs --break-system-packages
AWS_DEFAULT_REGION=ap-southeast-2 cdk bootstrap
```

## Deploy

```bash
cd infra
AWS_DEFAULT_REGION=ap-southeast-2 cdk deploy --require-approval never
```

Creates:
- `nrl-predictor-v2-agent` Lambda (8 min timeout, 512 MB)
- `nrl-predictor-v2-orchestrator` Lambda
- `nrl-predictor-v2-api` Lambda + API Gateway (`/predictions/{round}`, `/health`)
- `agent_traces` DynamoDB table
- EventBridge rules firing Tue/Thu/Fri UTC

## Run manually

**Trigger a full round** (scrapes draw, fans out to agent per match):

```bash
aws lambda invoke \
  --function-name nrl-predictor-v2-orchestrator \
  --payload '{"season": 2026, "round": "current"}' \
  --cli-binary-format raw-in-base64-out \
  --region ap-southeast-2 \
  response.json && cat response.json
```

**Trigger a single match**:

```bash
aws lambda invoke \
  --function-name nrl-predictor-v2-agent \
  --payload '{"matchId": "20260115", "round": 15}' \
  --cli-binary-format raw-in-base64-out \
  --region ap-southeast-2 \
  response.json && cat response.json
```

**Tail logs**:

```bash
aws logs tail /aws/lambda/nrl-predictor-v2-agent --follow --region ap-southeast-2
aws logs tail /aws/lambda/nrl-predictor-v2-orchestrator --follow --region ap-southeast-2
```

## Local development

```bash
pip install -e ".[dev]" --break-system-packages
python3 -m pytest
```

## Shadow mode

v2 runs alongside v1 during validation:

1. EventBridge fires v2 orchestrator ~4 minutes after v1
2. v2 predictions land in the same `predictions` table, identifiable by `prompt_version = "v2.0"`
3. v1 API continues serving the frontend until you swap the API Lambda
4. Compare accuracy via the scoring + metrics pipeline
