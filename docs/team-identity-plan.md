# Team identity: single canonical slug + display registry

**Status:** proposal · **Applies to:** `nrl-predictor` (v1, live) and `nrl-predictor2` (v2)
**Author:** 2026-06-21

## Problem

A team is referred to by at least three different strings today:

| Form | Example | Where it comes from |
|---|---|---|
| Short nickname (mixed case) | `Sea Eagles`, `Wests Tigers` | NRL API `nickName` — stored in `results.homeTeam/awayTeam/winner`, ladder, team sheets |
| Full name | `Manly Sea Eagles`, `Manly-Warringah Sea Eagles` | Odds API; the LLM when it has no team sheet |
| Lowercase slug | `sea-eagles` | embedded in every `matchId` (`round-17-sea-eagles-v-storm`) |

Because `recent_form`/`head_to_head` scan the `results` table with an **exact-string** match,
any mismatch silently returns nothing and the agent predicts blind (this sank v2 round 17).
We have patched the symptom with a boundary resolver (`agent/tools/team_names.py::canonical`),
but the underlying representation is still inconsistent, so the bug class keeps recurring.

## Goal

One canonical internal representation — the **lowercase slug** (`sea-eagles`) — used in every
table, payload, tool argument, and comparison across both repos. A single **team registry** is
the only place that knows how to (a) map any inbound string to the slug and (b) map the slug to
display strings (full name, short name, abbreviation, logo, colours) for the website.

Slug is chosen over the alternatives (see "Options evaluated") primarily because **matchIds
already use it**, so half the system is already on slugs; finishing the job removes the
ambiguity by construction rather than papering over it.

---

## Design: one registry as the single source of truth

A static, hand-verified registry — 17 rows, one per club. Lives in shared code so both repos and
the frontend consume the *same* data.

```
# team_registry.py  (Python, shared)   +   team_registry.json (consumed by the TS frontend)
{
  "sea-eagles": {
    "team_id": 500723,             # NRL API numeric id — stable across rebrands
    "nickname": "Sea Eagles",      # NRL API nickName
    "full_name": "Manly Sea Eagles",
    "abbrev": "MAN",
    "aliases": ["manly", "manly-warringah sea eagles", "manly warringah sea eagles"],
    "odds_api_names": ["Manly Sea Eagles", "Manly-Warringah Sea Eagles"]
  },
  ...
}
```

Two functions, both pure and exhaustively tested:

```python
def to_slug(name: str) -> str        # any inbound form (nickname/full/slug/teamId/alias) -> slug
def display(slug: str) -> TeamDisplay # slug -> {nickname, full_name, abbrev, logo, ...}
```

`to_slug` subsumes today's `canonical()`. It must be **idempotent** (`to_slug(to_slug(x)) == to_slug(x)`)
and **total** (unknown input returns the input unchanged + logs a warning, never raises).

### Why a registry, not just a display file

The user asked for "a mapping file for display." We need the *inverse* map too (inbound → slug)
because the odds API and the LLM emit uncontrolled strings. One registry holds both directions;
a display-only file would still leave `to_slug` as a second, drifting source of truth.

---

## Scope of change (both repos)

### Producers — emit slugs at the write boundary
- `scrapers/nrl/results.py` — `home_team/away_team/winner` = `to_slug(nickName)`
- `scrapers/nrl/team_sheet.py` — `homeTeam/awayTeam` = `to_slug(nickName)`
- `scrapers/nrl/draw.py` — match `home_team/away_team` and teams-table `team` field
- `scrapers/nrl/ladder.py` — `positions[].team`
- `scrapers/nrl/backfill.py` — same as results
- `scrapers/odds/scraper.py` — replace the bespoke full-name fuzzy match with `to_slug`
- **Agent output**: normalise `predicted_winner`, challenge `counter_winner`,
  `first_try_candidates[].team`, `key_player_to_watch` team refs to slug in
  `agent/lambda_handler.py::write_prediction` (v2) / `agent/lambda_handler.py` (v1) before write.

### Consumers — assume slug (drop ad-hoc matching)
- `agent/tools/recent_form.py`, `head_to_head.py` — keep `to_slug` on the arg (defence in depth;
  the stored data is now slugs, but the LLM still passes free text).
- `agent/tools/coaching_matchup.py`, `spine_synergy.py`, `trap_game.py`, ladder position lookup
  in `agent/lambda_handler.py::load_match_context` — key on slug.
- `scoring/` — `predicted_winner == winner` comparison is now slug-vs-slug; pass both through
  `to_slug` on read for the transition window so pre-migration rows still score.

### Display — map slug → name at the edges only
- **API** (`api/predictions.py` v1, v2 API Lambda): add `homeTeamName`, `awayTeamName`,
  `predictedWinnerName` (from `display()`) alongside the raw slug fields. Keep slugs in the
  payload so clients can pick.
- **Frontend** (`frontend/lib/api.ts`, `components/MatchCard.tsx`): consume `team_registry.json`;
  render `display(slug)` for names + logos. This is also the natural home for crests/colours.
- **Inspector / dashboard** (`tools/inspector.py`, `tools/dashboard.py`): render via `display()`.

---

## Data migration (existing DynamoDB rows)

Tables holding name strings: `results` (homeTeam/awayTeam/winner), `predictions`
(predicted_winner, counter_winner, first_try_candidates[].team), `teams` (ladder positions[].team,
team-sheet homeTeam/awayTeam, draw `team`), `odds` (team), `retrospectives` (any team refs).

**One idempotent migration script** (`scripts/migrate_team_slugs.py`, shared logic), run per table:

1. `--dry-run` first: scan, show every distinct value and its `to_slug` target, and **flag any
   value that doesn't resolve** (forces the registry to be complete before we touch data).
2. Export/back up each table (`aws dynamodb scan` to S3/JSON) before writing.
3. Scan + rewrite name fields through `to_slug`. matchId **keys are already slugs** — we only
   rewrite attribute values, never the key, so no item re-creation/deletion is needed.
4. Idempotent by construction (`to_slug(slug) == slug`) — safe to re-run; verify with a second
   `--dry-run` showing zero changes.

`results` has `(matchId, scoredAt)` immutable history; we rewrite attributes in place via
`update_item`, preserving keys. Historical metrics already aggregated in the `metrics` table can
be left as-is (cosmetic) or recomputed by re-running `scripts/score_round.py` per round.

---

## Sequencing — expand / migrate / contract (don't break the live site)

v1 serves the live frontend, so reads must tolerate both forms until the data is migrated.

1. **Land the registry + `to_slug`/`display`** in both repos (+ `team_registry.json`). No behaviour
   change yet. Ship behind tests.
2. **Writers emit slugs** (scrapers + agent output). New rows are slugs; old rows still mixed.
3. **Readers tolerate both** — they already do, via `to_slug` on read. API starts returning the
   extra `*Name` display fields.
4. **Frontend** switches to `display(slug)` (reads new fields / registry).
5. **Migrate existing rows** (dry-run → back up → rewrite → verify).
6. **Contract**: once migration is verified, the data is uniform; the read-side `to_slug` shims
   stay only as defence against LLM/odds free text (cheap, idempotent).
7. **Decommission** the old `canonical()` in favour of `to_slug` (alias then remove).

---

## Tests to add/update

- **Registry unit tests**: every alias/full/slug/nickname/`teamId` form → correct slug;
  `to_slug` idempotent + total; `display(slug)` returns all 17; round-trip `display(to_slug(x))`.
- **Tool tests** (`test_tool_get_recent_form`, `test_tool_get_head_to_head`, coaching, spine,
  ladder): rewrite fixtures to slugs; keep the long-name-resolves regression already added.
- **Scoring tests**: slug-vs-slug correctness; a mixed-format row scores correctly during transition.
- **Migration test** (moto): seed a table with all three formats → run migration → all slugs;
  re-run → zero changes (idempotency).
- **API contract test**: response includes `*Name` display fields for a slug input.
- **Frontend**: `MatchCard` renders display name + logo from a slug; snapshot/RTL test.
- Gate: `gate-ci` (lint + typecheck + tests) green in both repos; `gate-verify` for the boot path.

## Documentation to update

- Both `CLAUDE.md`: add a **"Team identity"** section — slug is canonical internally, registry is
  the SSOT, display only at API/frontend edges. State the invariant: *no raw team name is written
  to any table or passed to any tool; everything is `to_slug`'d at the boundary.*
- `README.md` (both): note the registry + migration script.
- `scrapers/nrl/draw.py` slug docstring: cross-reference the team registry.
- This doc: link from both CLAUDE.md files; update status as phases land.

---

## Options evaluated

| Option | What | Pros | Cons | Verdict |
|---|---|---|---|---|
| **A. Slug everywhere + registry** (this plan) | lowercase slug is the internal id; registry maps in/out | matchIds already use slugs → consistency by construction; human-readable in logs/DB; one SSOT; kills the bug *class* | requires DB migration + frontend display lookup; must still normalise LLM/odds input | **Recommended** |
| B. Boundary-normalise only (status quo+) | keep storing `nickName`; run `canonical()` on every read/write | smallest change; **already deployed for form/h2h**; no migration | two written forms still coexist (`nickName` vs slug-in-matchId); every new reader must remember to normalise; ambiguity persists | Good stop-gap (done); not the destination |
| C. Numeric `teamId` as canonical | use the NRL API's stable numeric id internally | most stable (survives rebrands/renames); already in the API | opaque in logs/DB (`500723` not `sea-eagles`); bigger migration; matchIds would diverge from the id | Rejected — readability loss not worth it at this scale |
| D. Do nothing | rely on the deployed resolver | zero work | bug recurs at every new tool/field; data stays inconsistent | Rejected |

**Key insight:** *every* option still needs `to_slug` at the boundary, because the LLM and the
odds API emit uncontrolled strings — slugs define the **target** form, they don't remove the need
to normalise. So Option B's resolver is load-bearing in all of them; Option A's added value is
making the **stored** form uniform too, which is what stops new readers/writers from silently
reintroducing the bug. Given matchIds are already slugs, A is the natural completion of a
decision the codebase half-made, not a new direction.

**Recommended path:** B is already shipped and stops the bleeding. Schedule A as a deliberate
(non-emergency) change in the order above, landing the registry first (high value, low risk) and
treating the data migration as the one genuinely risky step — gated behind a dry-run that proves
the registry resolves 100% of existing values before any write.

## Out of scope (related, separate)

`matchId` keying is a *different* axis (match identity, not team identity): the results scraper
writes round-less keys (`broncos-v-roosters`) while predictions use round-prefixed slugs
(`round-17-broncos-v-roosters`), which is why the inspector showed bogus round-17 "results". The
team registry doesn't fix that; track it separately.
