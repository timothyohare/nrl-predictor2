# Match identity: one canonical matchId, enforced and round-aware

**Status:** proposal · **Applies to:** `nrl-predictor` (v1, live) and `nrl-predictor2` (v2)
**Author:** 2026-06-21 · **Sibling:** [team-identity-plan.md](team-identity-plan.md)

## Problem

`matchId` is meant to be the round-qualified slug from the match-centre URL
(`round-17-sea-eagles-v-storm`) — both repos' `draw.py` say so. But the shared `results`
table holds the same fixture under several keys at once:

```
round-16-knights-v-dragons    (round-prefixed, from the v2 scraper + scoring write-back)
dragons-v-knights             (round-less, legacy/raw)
knights-v-raiders  AND  raiders-v-knights   (home/away order not normalised)
```

Three independent inconsistencies:

1. **Round prefix is optional** — some rows are `round-N-home-v-away`, some are `home-v-away`.
2. **Home/away order isn't canonical** — `knights-v-raiders` vs `raiders-v-knights` are different
   keys for what a round-blind joiner treats as the same fixture.
3. **Multiple writers, one table** — current scrapers, scoring write-backs, and legacy
   backfill/raw rows coexist in the shared `results` table.

### Who this actually breaks

- The v1 **API is safe**: it joins results by `matchId` *and filters on `roundNumber`*, and only
  the scoring lambda's write-back row carries `roundNumber` — so raw/legacy rows are excluded
  (`api/predictions.py:57-69`).
- **Round-blind consumers break**: the v2 inspector/dashboard join by normalised team-pair without
  a round, so they matched round-17 predictions to an *earlier* meeting and displayed bogus
  "results" for matches that hadn't been played. `scripts/round_state.py` already works around
  this by reading completion only from round-prefixed FullTime slugs.
- **Scoring is fragile**: `score_prediction(match_id, …)` queries `results` by the prediction's
  matchId; it only works because that matchId is the round-prefixed slug *and* a matching result
  row exists under the same key. A future writer that emits a different form silently breaks it.

## Goal

One canonical `matchId`, produced by a **single helper** used by every writer, and a hard rule
that **every join is round-aware** (by `matchId` or `roundNumber`, never team-pair alone).

```
canonical matchId  =  round-<N>-<home-slug>-v-<away-slug>
```

where `<home>`/`<away>` come from the official `matchCentreUrl` order (the draw is the source of
truth for which side is home), and the team slugs are the canonical team slugs from the
[team-identity plan](team-identity-plan.md). The two plans compose: `round-16-sea-eagles-v-storm`,
never `round-16-manly-sea-eagles-v-melbourne-storm`.

---

## Design

### One helper, one definition
Promote the existing `match_id_from_url()` (v2) / `slug_from_match_centre_url()` (v1) to the
**single source of truth** and route every writer through it. Add a sibling for callers that have
structured fields instead of a URL:

```python
def match_id_from_url(url: str) -> str            # canonical key from matchCentreUrl
def match_id(round_no: int, home_slug: str, away_slug: str) -> str
    # -> f"round-{round_no}-{home_slug}-v-{away_slug}"   (home/away NOT reordered)
```

These live next to the team registry so both identity rules sit together.

### The invariant (documented + tested)
> Every `results`/`predictions`/`teams`/`odds` row is keyed by the canonical `matchId`, and every
> join across tables uses `matchId` or `(matchId, roundNumber)` — never a round-blind team-pair.

### Joiners become round-aware
- v2 **inspector/dashboard** (`tools/inspector.py`, `tools/dashboard.py`): join predictions→results
  on `matchId` (round-prefixed) directly; drop the team-pair normalisation that caused the bogus
  round-17 join. Fall back to `roundNumber` filtering like the v1 API does.
- `scripts/round_state.py`: already round-aware — keep, but switch from a regex on the slug to the
  shared helper once it lands.

---

## Scope of change (both repos)

### Producers — all key on the canonical matchId
- `scrapers/nrl/results.py`, `backfill.py` — already use the helper; confirm and lock with a test.
- `scrapers/nrl/draw.py`, `team_sheet.py` — same helper for the teams-table key.
- `scoring/lambda_handler.py` — writes back under the matchId it's invoked with; ensure callers
  (`scripts/score_round.py`, orchestrators) always pass the canonical slug.
- `scrapers/odds/*` — key odds rows on the canonical matchId (today they match on team strings).

### Consumers — round-aware joins only
- v2 `tools/inspector.py`, `tools/dashboard.py` — see above.
- v1 `api/predictions.py` — already round-aware; no change beyond documenting the contract.

---

## Data migration (existing `results` rows)

The legacy round-less and reversed-order rows are **raw scrape rows with no `roundNumber`** — they
carry no scored information and are duplicated by canonical rows. Two viable treatments:

- **Preferred — delete the non-canonical raw rows.** Scan `results`; any item whose `matchId` does
  not match `^round-\d+-` (or is a known reversed-order duplicate) and has no `roundNumber`/scoring
  fields is a stale raw row → delete. This declutters the table and makes round-blind joins
  impossible to get wrong. Dry-run first; export/back up; idempotent (re-run deletes nothing).
- **Conservative — leave them, fix joiners.** If any historical analysis depends on the raw rows,
  keep them and rely solely on the round-aware join rule. Lower risk, leaves the clutter.

Recommendation: **delete**, after a dry-run confirms every deleted key has a canonical counterpart
(so no result is actually lost). `recent_form`/`head_to_head` scan by `homeTeam/awayTeam`, not by
matchId, so deleting duplicate-keyed rows must not drop a *unique* historical fixture — the dry-run
must verify each deletion candidate's (teams, scoredAt) is still represented by a canonical row.

---

## Sequencing — expand / migrate / contract

1. **Land the helper(s)** as the single matchId SSOT in both repos; no behaviour change.
2. **Route all writers** through it (most already are) + a regression test per writer.
3. **Make joiners round-aware** (v2 inspector/dashboard) — this alone removes the user-visible
   bogus-results bug.
4. **Dry-run the cleanup**: list non-canonical rows, prove each has a canonical counterpart.
5. **Back up + delete** the stale raw rows.
6. **Contract**: document the invariant in CLAUDE.md; the round-aware rule is now load-bearing.

Steps 1–3 are safe and fix the live symptom; 4–5 are the only risky part and are gated by the
dry-run.

---

## Tests to add/update

- **Helper unit tests**: `match_id_from_url` for round-N URLs, finals URLs, trailing slashes, the
  2-segment fallback; `match_id(round, home, away)` shape; **does not reorder** home/away.
- **Writer regression**: results/draw/team_sheet/odds scrapers emit `round-N-…` keys (moto).
- **Joiner tests**: inspector/dashboard join an unplayed round to **no** result (the round-17
  regression — guard against round-blind matching reappearing).
- **Migration test** (moto): seed canonical + round-less + reversed rows → dry-run flags only the
  safe-to-delete ones → delete → canonical rows intact → re-run deletes nothing (idempotent).
- Gate: `gate-ci` green both repos.

## Documentation to update

- Both `CLAUDE.md`: a **"Match identity"** note stating the canonical matchId format, the single
  helper, and the round-aware-join invariant. Cross-link the team-identity plan.
- `draw.py` docstrings already describe the slug — point them at the helper as SSOT.

---

## Options evaluated

| Option | What | Pros | Cons | Verdict |
|---|---|---|---|---|
| **A. Canonical matchId + round-aware joins + cleanup** (this plan) | one helper, delete stale raw rows | removes the bug class + the clutter; joins provably correct | one (gated) destructive migration | **Recommended** |
| B. Fix joiners only, keep raw rows | make every consumer round-aware, don't migrate | zero data risk; fixes the live symptom | table stays cluttered; next round-blind joiner reintroduces the bug | Good first step (= steps 1–3) |
| C. Composite key `(matchId, roundNumber)` everywhere | add roundNumber to every join/PK | explicit, no slug parsing | larger code change; predictions/results already key on slug — redundant; doesn't dedupe raw rows | Rejected — slug already encodes the round |
| D. Do nothing | rely on the v1 API being incidentally safe | zero work | v2 inspector/dashboard stay wrong; scoring stays fragile | Rejected |

**Key insight:** the canonical matchId **already encodes the round** (`round-N-…`), so the fix is
not a new key scheme — it's *enforcing the one we already intend* at every writer and *forbidding
round-blind joins* at every reader. The destructive cleanup (A) is optional polish over the
behavioural fix (B); do B immediately, schedule A behind a dry-run.

## Relationship to the team-slug plan

Independent axes that **compose in the matchId**: team slugs decide `sea-eagles`; match identity
decides `round-16-<home>-v-<away>`. Land the team registry first (the matchId helper can then build
slugs from it), but neither blocks the other — `recent_form`/`head_to_head` are a team-identity
problem, the inspector's bogus join is a match-identity problem.
