# Quality-harness onboarding — nrl-predictor2

How the user-level SDLC harness (`~/.claude/HARNESS.md`) binds to this repo, what
works today, and what's needed to go further.

## TL;DR

- The harness autodetects **Next.js** and **SAM** only. This is a plain Python
  package — no `package.json`, no `template.yaml` — so with no binding the gates
  resolve `runtime: unknown` and **no-op on every key**.
- A one-key binding (`.claude/harness.json`) wires the fast gate to the existing
  pytest suite. **Done — fast gate is green** (`31 passed`).
- The Stop hook is already wired globally, and the source-changed guard already
  covers `.py`, so the gate now fires automatically when a `.py` file changes.
- The **heavy gate (`gate-verify`) does not map cleanly** to this project — there
  is no long-running HTTP server to boot and poll. Options below.

## What was required for the fast gate (`gate-ci`)

The fast gate runs whichever of `lint` / `typecheck` / `test` resolve, skipping
any key that resolves to nothing. The binding added:

```json
// .claude/harness.json
{
  "runtime": "lambda",
  "lint": "python3 -m ruff check .",
  "test": "python3 -m pytest -q",
  "env": { "AWS_REGION": "ap-southeast-2" }
}
```

Verified:

```
node ~/.claude/bin/gate-ci.mjs --force   →  exit 0,  lint clean + 31 passed
```

| Key | Status | Notes |
|---|---|---|
| `lint` | ✅ wired | `python3 -m ruff check .` (Ruff 0.15). Cleaned 13 dead imports on enablement; `infra/cdk.out` excluded via `[tool.ruff]` in `pyproject.toml`. `ruff>=0.15` added to dev deps. |
| `test` | ✅ wired | `python3 -m pytest -q`, 31 tests, moto-mocked DynamoDB, MagicMock LLMs. Fast (~0.5s). |
| `typecheck` | ⚪ omitted | No type checker installed; the code is pydantic-heavy and would surface many errors on day one. Omitting = clean skip. |
| `build` | ⚪ omitted | No meaningful build for a zipped-Lambda Python app. `cdk synth` is the closest analogue but is slow and needs CDK installed. |

Nothing else is required for the fast gate to be useful today.

## Optional upgrade path for the fast gate

Lint is now wired (above). The remaining opt-in is typecheck — opt-in because,
once a command resolves, a failure **blocks turn completion** (exit 2 via the
Stop hook), so only enable it once the repo is clean.

**Typecheck with mypy** (start lenient):
   ```bash
   pip install mypy --break-system-packages
   ```
   Add a lenient `[tool.mypy]` section to `pyproject.toml` (e.g.
   `ignore_missing_imports = true`, check only `agent/`), then add
   `"typecheck": "python3 -m mypy agent"`. Tighten over time.

Add `mypy` to `pyproject.toml` `[project.optional-dependencies].dev` so it
installs with `pip install -e ".[dev]"` (`ruff` is already there).

## The heavy gate (`gate-verify`) — mismatch + options

`gate-verify` is built around a service model: **mock AWS up → boot an HTTP app →
poll a `ready` URL for 200 → run `acceptance` → teardown**. This project has no
such server. The "app" is a LangGraph pipeline invoked per-match inside a Lambda,
and the real run makes live Anthropic calls (which we never want in a gate).

Three ways to handle it, cheapest first:

### Option A — Don't use gate-verify; lean on the integration test (recommended)
`tests/agent/test_graph_integration.py` already boots the **whole five-node graph**
end-to-end with MagicMock LLMs against moto DynamoDB. That is exactly the
"does it actually wire together" proof gate-verify exists to provide — it just
runs inside `pytest` (i.e. the fast gate) instead of over HTTP. Leave
`boot`/`ready`/`acceptance` unset so `gate-verify` no-ops. **Zero extra work.**

### Option B — Thin local HTTP wrapper for a true boot-and-verify
Add a tiny dev server (`stdlib http.server`) that:
- `GET /health` → `{"status":"ok"}` (the `ready`/`readyMatch` target),
- `POST /invoke` → runs `get_app()` with an injected MagicMock LLM against
  **dynamodb-local**, writing a prediction row.

Then bind:
```json
{
  "boot": "python3 -m tools.devserver",
  "ready": "http://localhost:8080/health",
  "readyMatch": "\"status\":\"ok\"",
  "mockAws": "dynamodb-local",
  "setup": "python3 -m tools.seed_local",
  "acceptance": "python3 -m tools.verify_persistence"
}
```
`verify_persistence` POSTs a match and asserts a `predictions` row with
`prompt_version=v2.0` lands with all v2 fields. ~1 day of work; gives a genuine
"boots and persists" gate. Still no live LLM calls.

### Option C — Smoke against real AWS (out of scope for the harness)
A separate script that invokes the deployed `nrl-predictor-v2-agent` Lambda for
one match and asserts the row + trace land. Real money, real LLM — belongs in a
manual/CI smoke check, **not** the Stop-hook path.

## Notable findings while onboarding

These aren't harness work, but surfaced during it and are worth flagging:

- **No v2 output exists yet.** Scanning `predictions` (170 items): `prompt_version`
  is `v1.1` (29), `v1.2` (56), or absent (85). **Zero `v2.0` rows.** The
  `agent_traces` table is **empty**. So the multi-agent v2 pipeline has not yet
  written a successful live result — worth confirming before/around shadow mode.
  (See `project_v2_bugs.md` memory — prior Challenger crash + stale deploy.)
- **Experiment scaffolding already exists** in DynamoDB: `prompt_variants` (8
  active variants with `hypothesis` + `dimensions`, e.g. `light-home-advantage`,
  `high-confidence-strict`), plus empty `variant_metrics` and
  `simulation_predictions` tables. This is the "run lots of scenarios" substrate —
  central to the visualization plans (see `visualization-plans.md`).
