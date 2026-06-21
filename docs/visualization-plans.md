# Visualising inputs, outputs & in-progress runs — three plans

Goal: make the v2 multi-agent predictor's **inputs, outputs, and current progress**
visible — especially the "run lots of scenarios over weeks to see what works"
experiment loop. Three approaches at increasing cost/ambition; pick one (or stage
A → C).

## What data actually exists (verified against `ap-southeast-2`)

| Source | Shape | State today |
|---|---|---|
| `predictions` | per-match final prediction; `prompt_version` v1.1/v1.2/none, v2 adds `agent_difficulty`, `challenge_strength`, `primary_accepted`, `judge_rationale`, `first_try_candidates`, `margin_bracket`, `upset_probability` | **170 rows, all v1.** No `v2.0` yet. |
| `agent_traces` | PK `matchId`, SK `generatedAt`; `trace_entries[]` (node/tool/input/output), `difficulty`, `primary_model` | **empty** |
| `prompt_variants` | `variantId`, `hypothesis`, `dimensions[]`, `prompt_template`, `active` | **8 active variants** |
| `variant_metrics` | per-variant accuracy rollups | **empty** |
| `simulation_predictions` | predictions tagged by variant (A/B backtest output) | **empty** |
| `results` / `metrics` / `odds` | actual scores, accuracy rollups, betting lines (odds joined only at API time) | populated (v1) |

Implication: a viz layer must be **graceful when v2/experiment tables are empty**
(they are the point of the project, but not filled yet) and should double as the
thing that tells you *the moment they start filling*.

The repo also already has a static-site target: `/home/timohare/dev/quicksite/public`
(a Hugo build). Plans B/C can publish there, or stand alone.

---

## Plan A — `nrl-inspect` CLI + static HTML snapshot ✅ BUILT

> **Status: implemented** in `tools/inspector.py` (stdlib + boto3, lint-clean).
>
> ```bash
> python3 -m tools.inspector                     # coverage + latest round board (terminal)
> python3 -m tools.inspector --round 14          # a specific round
> python3 -m tools.inspector --match round-15-eels-v-raiders   # pipeline trace
> python3 -m tools.inspector --all --html inspect.html         # every round → HTML snapshot
> ```
>
> Verified against live `ap-southeast-2`: round boards join to actual results
> with ✓/✗ and margin error, coverage shows v1-vs-v2 + trace counts, and the
> empty v2/trace tables render as "pending" rather than erroring. The HTML is
> self-contained (no external assets) — open it or drop it into quicksite.

### Original design (lowest cost, fastest)

A single Python script (`tools/inspector.py`, stdlib + boto3 only — both already
deps) that reads the tables and renders **two outputs from one pass**: a rich
terminal summary and a self-contained `inspect.html` you can open or drop into
quicksite.

**Views**
1. **Round board** — table of matches for a round: predicted winner, margin,
   confidence, difficulty, challenge strength, `primary_accepted`, upset prob.
   Colour by confidence; flag where the Judge overruled the Primary.
2. **Pipeline trace** — for one `matchId`, the Router→Primary→Challenger→Judge→
   Extended flow rendered as an indented timeline from `agent_traces.trace_entries`
   (which tool was called, with what input, what it returned). This is the
   "what did the agent actually look at" view.
3. **Coverage / progress** — counts by `prompt_version` and round, and a
   "v2 vs v1 produced so far" line. Surfaces the *empty-table* reality at a glance.

**Pros:** hours not days; no infra, no deploy, no new IAM; runs from your laptop
with existing creds; works offline against a `scan` dump; easy to wire as a
harness `observability` check later. **Cons:** static (re-run to refresh); no
live "currently running" view; terminal/HTML only.

**Effort:** ~0.5–1 day. **Best if:** you want eyes on the data *this week* and to
confirm v2/traces start landing.

---

## Plan B — Local Streamlit dashboard ✅ BUILT

> **Status: implemented** in `tools/dashboard.py`, reusing `tools/inspector.py`
> as the data layer. Lint-clean; all five pages smoke-tested via Streamlit's
> `AppTest` against live `ap-southeast-2` (zero exceptions) and rendered in-browser.
>
> ```bash
> pip install -e ".[viz]" --break-system-packages   # streamlit + pandas
> AWS_REGION=ap-southeast-2 streamlit run tools/dashboard.py
> # If `streamlit` isn't on PATH (--break-system-packages puts the shim in
> # ~/.local/bin), run the module form instead — no PATH change needed:
> AWS_REGION=ap-southeast-2 python3 -m streamlit run tools/dashboard.py
> # Serves at http://localhost:8501
> ```
>
> Pages built: **Run monitor** (freshness + live-round progress, optional
> auto-refresh via `st.fragment`), **Round boards** (predictions ⋈ results with
> accuracy + MAE), **Variant scoreboard** (`prompt_variants` ⋈ `simulation_predictions`
> /`variant_metrics`, "pending" until those fill), **Match explorer** (prediction
> detail + Primary/Challenger/Judge breakdown when v2 fields exist + trace
> timeline), **Calibration** (confidence reliability, MAE, predicted-vs-actual
> scatter). Data cached 30s; a sidebar button clears the cache for an instant
> refresh. Verified live: R11–15 show 63% winner accuracy, 10.5 pt mean margin
> error, HIGH-confidence picks calibrating better than MEDIUM.

### Original design (best for the experiment loop)

A `streamlit run tools/dashboard.py` app — the natural fit for "compare scenarios
over weeks." Reads the same tables live, with interactive filters.

**Pages**
1. **Variant scoreboard** — the headline. One row per `prompt_variants` entry
   (`hypothesis`, `dimensions`), joined to `variant_metrics` / `simulation_predictions`
   and `results`: accuracy, margin error (MAE), confidence calibration, upset
   hit-rate. Sortable, so "what worked best" is the default question answered.
   Shows hypotheses with *no data yet* as pending.
2. **Match explorer** — pick a match → side-by-side Primary vs Challenger vs Judge
   cards (winner/margin/confidence + reasoning), with the `agent_traces` tool
   timeline below. The "why did it decide this" view.
3. **Calibration & accuracy** — reliability curve (predicted confidence vs actual
   hit-rate), margin-bracket accuracy, predicted-vs-actual scatter, all filterable
   by variant / round / difficulty.
4. **Run monitor** — recent `generatedAt` timestamps across `predictions` +
   `agent_traces`; a round in progress shows as "N of M matches predicted." Auto-
   refresh gives a near-live progress feel without real infra.

**Pros:** interactive; ideal for A/B comparison and calibration; pure Python (fits
the team's skillset); charts via Altair/Plotly; can run locally or on a small box.
**Cons:** new dep (`streamlit`); it's a running process, not a public URL unless
hosted; polling-based, not truly event-driven.

**Effort:** ~2–3 days. **Best if:** the primary need is *evaluating which scenario
wins* and iterating week to week. **This is the recommended default.**

---

## Plan C — Live dashboard on the existing API + quicksite (most ambitious)

Extend the v2 API Lambda with read-only JSON endpoints and ship a small static
dashboard to the existing site, so inputs/outputs/progress are visible to anyone
with the URL, updating as rounds run.

**Backend (`api/router.py` already path-routes — add):**
- `GET /v2/round/{round}` — predictions + v2 metadata for a round.
- `GET /v2/trace/{matchId}` — the agent trace for one match.
- `GET /v2/variants` — variant scoreboard (variants ⋈ metrics ⋈ results).
- `GET /v2/progress` — counts of matches predicted vs scheduled for the live round.

**Frontend:** a static page (vanilla JS + a chart lib, or a tiny build) published
to `/home/timohare/dev/quicksite/public/v2/`, polling the endpoints — round board,
clickable pipeline trace, variant leaderboard, and a live "round in progress"
ticker.

**Pros:** real, shareable, always-on; reuses deployed API + IAM + CORS already in
the stack; live progress as the orchestrator fans out matches; natural home for
shadow-mode v1-vs-v2 comparison. **Cons:** most work; touches deployed infra (new
routes, IAM read grants, redeploy); frontend build/host to maintain; needs the
heavy gate / a smoke test to stay honest.

**Effort:** ~4–6 days. **Best if:** you want a durable, shareable window that
outlives the experiment and doubles as the shadow-mode comparison surface.

---

## Recommendation

Stage it: **Plan A now** (immediate visibility + confirms v2/traces actually start
landing — currently both empty), then **Plan B** as the working surface for the
multi-week scenario evaluation. Promote to **Plan C** only if you want it public/
always-on. A and B share all the read/query logic, so A is not throwaway — its
table-reading functions become B's data layer.

| | Plan A — CLI/HTML | Plan B — Streamlit | Plan C — API + site |
|---|---|---|---|
| Effort | ~0.5–1d | ~2–3d | ~4–6d |
| Live progress | ✗ (re-run) | ~ (poll) | ✓ |
| Variant A/B compare | basic | **strong** | strong |
| Shareable URL | ✗ | ~ | ✓ |
| New infra/deploy | none | none | API routes + IAM |
| Experiment-loop fit | ok | **best** | best |
