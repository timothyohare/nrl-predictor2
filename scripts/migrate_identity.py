#!/usr/bin/env python3
"""Idempotent migration to canonical team slugs + matchId cleanup.

Two subcommands, both DRY-RUN by default (pass --apply to write):

  teams     Rewrite team-name fields to canonical slugs across results / predictions /
            teams / odds. matchId KEYS are never touched — only attribute values — so no
            item is recreated. Idempotent: re-running rewrites nothing.

  matchids  Report (and with --apply, delete) non-canonical `results` rows — round-less or
            reversed-order raw rows that have no roundNumber AND are already represented by a
            canonical `round-<N>-...` row with the same teams + scoredAt. A row with no
            canonical counterpart is NEVER deleted (it is reported as "kept: unique").

Run `teams` before `matchids`. See docs/team-identity-plan.md, docs/matchid-identity-plan.md.
"""
from __future__ import annotations

import argparse
import os

import boto3

from common.match_id import is_canonical
from common.teams import to_slug

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-southeast-2"

# Per-table flat team-name fields to slugify.
_NAME_FIELDS = {
    "results": ["homeTeam", "awayTeam", "winner"],
    "predictions": ["predicted_winner", "counter_winner"],
    "teams": ["team", "homeTeam", "awayTeam"],
    "odds": ["team", "home_team", "away_team"],
}


def slugify_item(item: dict, fields: list[str]) -> tuple[dict, bool]:
    """Return (new_item, changed). Slugifies the given flat fields plus the nested
    `positions[].team/team_name` (ladder) and `first_try_candidates[].team` lists."""
    new = dict(item)
    changed = False
    for f in fields:
        if f in new and isinstance(new[f], str) and new[f]:
            slug = to_slug(new[f])
            if slug != new[f]:
                new[f], changed = slug, True
    for list_field, key in (("positions", "team"), ("positions", "team_name"),
                            ("first_try_candidates", "team")):
        if isinstance(new.get(list_field), list):
            rebuilt = []
            for entry in new[list_field]:
                if isinstance(entry, dict) and isinstance(entry.get(key), str) and entry[key]:
                    slug = to_slug(entry[key])
                    if slug != entry[key]:
                        entry = {**entry, key: slug}
                        changed = True
                rebuilt.append(entry)
            new[list_field] = rebuilt
    return new, changed


def _scan_all(table) -> list[dict]:
    items: list[dict] = []
    kwargs: dict = {}
    while True:
        resp = table.scan(**kwargs)
        items += resp.get("Items", [])
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def migrate_teams(ddb, table_names: list[str], apply: bool) -> dict[str, int]:
    summary = {}
    for name in table_names:
        table = ddb.Table(name)
        fields = _NAME_FIELDS.get(name, [])
        changed = 0
        for item in _scan_all(table):
            new, did = slugify_item(item, fields)
            if did:
                changed += 1
                if apply:
                    table.put_item(Item=new)
                else:
                    print(f"  [{name}] {item.get('matchId', item.get('teamId'))}: "
                          f"{ {f: item[f] for f in fields if f in item} } -> "
                          f"{ {f: new[f] for f in fields if f in new} }")
        summary[name] = changed
        print(f"[{name}] {'rewrote' if apply else 'would rewrite'} {changed} items")
    return summary


def find_deletable_matchid_rows(results_items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split non-canonical results rows into (deletable, kept_unique).

    A non-canonical row (no `round-<N>-` prefix) is deletable only if a canonical row exists
    with the same team set (by slug) AND the same scoredAt — i.e. it is a true duplicate of a
    canonical row, so nothing is lost.
    """
    canonical_index = set()
    for it in results_items:
        mid = str(it.get("matchId", ""))
        if is_canonical(mid):
            teams = frozenset(to_slug(it.get(k, "")) for k in ("homeTeam", "awayTeam"))
            canonical_index.add((teams, it.get("scoredAt")))
    deletable, kept = [], []
    for it in results_items:
        mid = str(it.get("matchId", ""))
        if is_canonical(mid):
            continue
        teams = frozenset(to_slug(it.get(k, "")) for k in ("homeTeam", "awayTeam"))
        if (teams, it.get("scoredAt")) in canonical_index:
            deletable.append(it)
        else:
            kept.append(it)
    return deletable, kept


def migrate_matchids(ddb, apply: bool) -> dict[str, int]:
    table = ddb.Table("results")
    items = _scan_all(table)
    deletable, kept = find_deletable_matchid_rows(items)
    for it in deletable:
        print(f"  {'DELETE' if apply else 'would delete'} {it['matchId']} @ {it.get('scoredAt')}")
        if apply:
            table.delete_item(Key={"matchId": it["matchId"], "scoredAt": it["scoredAt"]})
    for it in kept:
        print(f"  KEEP (unique, no canonical counterpart) {it['matchId']} @ {it.get('scoredAt')}")
    print(f"[results] {'deleted' if apply else 'would delete'} {len(deletable)}; kept {len(kept)} unique")
    return {"deletable": len(deletable), "kept_unique": len(kept)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["teams", "matchids"])
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument("--tables", nargs="+", default=list(_NAME_FIELDS),
                        help="(teams command) tables to migrate")
    args = parser.parse_args()
    ddb = boto3.resource("dynamodb", region_name=REGION)
    if not args.apply:
        print("DRY RUN — no writes. Re-run with --apply to commit.\n")
    if args.command == "teams":
        migrate_teams(ddb, args.tables, args.apply)
    else:
        migrate_matchids(ddb, args.apply)


if __name__ == "__main__":
    main()
