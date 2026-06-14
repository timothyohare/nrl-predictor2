#!/usr/bin/env python3
"""nrl-inspect — read the v2 predictor's state from DynamoDB and render it.

One read pass, two outputs: a coloured terminal summary and an optional
self-contained HTML snapshot (no external assets — open it or drop it into a
static site). stdlib + boto3 only.

Views
-----
- coverage : counts by prompt_version and round, v1-vs-v2, trace coverage.
- board    : per-round table — latest prediction per match, joined to the actual
             result when one exists (✓/✗ on the winner, margin error).
- trace    : the Router→Primary→Challenger→Judge→Extended tool timeline for one
             match, from the agent_traces table.

Usage
-----
    python3 -m tools.inspector                      # coverage + latest round board
    python3 -m tools.inspector --round 14
    python3 -m tools.inspector --match round-15-eels-v-raiders
    python3 -m tools.inspector --html inspect.html  # also write a snapshot
    python3 -m tools.inspector --all --html inspect.html   # every round in the HTML

Empty v2/trace tables are expected today and render as "pending", not errors.
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

import boto3

REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
V2_PROMPT_VERSION = "v2.0"
_ROUND_PREFIX = re.compile(r"^round-\d+-", re.IGNORECASE)


# ── Data access ──────────────────────────────────────────────────────────────

def scan_table(name: str) -> list[dict]:
    """Full paginated scan of a table. Returns [] if the table is missing/empty."""
    table = boto3.resource("dynamodb", region_name=REGION).Table(name)
    items: list[dict] = []
    kwargs: dict = {}
    try:
        while True:
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
    except Exception as e:  # noqa: BLE001 — surface as a warning, keep going
        print(f"  warning: could not scan {name}: {e}", file=sys.stderr)
    return items


def norm_match(match_id: str) -> str:
    """Normalise a matchId to the bare `team-v-team` slug used across tables."""
    return _ROUND_PREFIX.sub("", match_id or "").lower()


def num(v, default=None):
    """Coerce a DynamoDB Decimal/str number to int/float, tolerating None."""
    if v is None or v == "":
        return default
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return default


def latest_per_match(preds: list[dict]) -> dict[str, dict]:
    """Keep only the most recent prediction (by generatedAt) per matchId."""
    best: dict[str, dict] = {}
    for p in preds:
        mid = p.get("matchId")
        if not mid:
            continue
        ts = p.get("generatedAt", "")
        if mid not in best or ts > best[mid].get("generatedAt", ""):
            best[mid] = p
    return best


def results_by_slug(results: list[dict]) -> dict[str, dict]:
    """Index actual results by normalised match slug, keeping the latest."""
    best: dict[str, dict] = {}
    for r in results:
        slug = norm_match(r.get("matchId", ""))
        ts = r.get("scoredAt", "")
        if slug and (slug not in best or ts > best[slug].get("scoredAt", "")):
            best[slug] = r
    return best


# ── Derived models ───────────────────────────────────────────────────────────

def round_of(p: dict):
    return num(p.get("roundNumber"))


def all_rounds(preds: list[dict]) -> list[int]:
    rs = {round_of(p) for p in preds if round_of(p) is not None}
    return sorted(rs)


def board_rows(preds: list[dict], results: list[dict], round_no: int) -> list[dict]:
    """Rows for one round: latest prediction per match joined to its result."""
    latest = latest_per_match([p for p in preds if round_of(p) == round_no])
    res_idx = results_by_slug(results)
    rows = []
    for mid, p in sorted(latest.items()):
        slug = norm_match(mid)
        res = res_idx.get(slug)
        winner = p.get("predicted_winner", "?")
        margin = num(p.get("predicted_margin"))
        actual_winner = res.get("winner") if res else None
        actual_margin = num(res.get("margin")) if res else None
        correct = None
        margin_err = None
        if actual_winner:
            correct = winner.lower() == str(actual_winner).lower()
            if margin is not None and actual_margin is not None:
                margin_err = abs(margin - actual_margin)
        rows.append({
            "match": slug,
            "winner": winner,
            "margin": margin,
            "confidence": p.get("confidence", "?"),
            "difficulty": p.get("agent_difficulty"),
            "challenge_strength": p.get("challenge_strength"),
            "primary_accepted": p.get("primary_accepted"),
            "upset": num(p.get("upset_probability")),
            "prompt_version": p.get("prompt_version", "—"),
            "actual_winner": actual_winner,
            "actual_score": f"{num(res.get('homeScore'))}-{num(res.get('awayScore'))}" if res else None,
            "correct": correct,
            "margin_err": margin_err,
        })
    return rows


def coverage(preds: list[dict], traces: list[dict]) -> dict:
    pv = Counter(p.get("prompt_version", "—") for p in preds)
    rnd = Counter(str(round_of(p)) for p in preds)
    v2 = sum(1 for p in preds if p.get("prompt_version") == V2_PROMPT_VERSION)
    trace_matches = {t.get("matchId") for t in traces}
    return {
        "total": len(preds),
        "v2": v2,
        "v1": len(preds) - v2,
        "by_version": dict(sorted(pv.items())),
        "by_round": dict(sorted(rnd.items(), key=lambda kv: (kv[0] == "None", kv[0]))),
        "traces": len(traces),
        "trace_matches": len([m for m in trace_matches if m]),
    }


def trace_for(traces: list[dict], match_id: str) -> dict | None:
    """Latest trace for a match, matched on raw or normalised id."""
    target = norm_match(match_id)
    cands = [t for t in traces if norm_match(t.get("matchId", "")) == target]
    if not cands:
        return None
    return max(cands, key=lambda t: t.get("generatedAt", ""))


# ── Terminal rendering ───────────────────────────────────────────────────────

class C:
    """ANSI helpers, no-ops when stdout is not a TTY."""
    on = sys.stdout.isatty()

    @classmethod
    def _w(cls, s, code):
        return f"\033[{code}m{s}\033[0m" if cls.on else str(s)

    @classmethod
    def bold(cls, s): return cls._w(s, "1")
    @classmethod
    def dim(cls, s): return cls._w(s, "2")
    @classmethod
    def green(cls, s): return cls._w(s, "32")
    @classmethod
    def red(cls, s): return cls._w(s, "31")
    @classmethod
    def cyan(cls, s): return cls._w(s, "36")
    @classmethod
    def yellow(cls, s): return cls._w(s, "33")


def print_coverage(cov: dict) -> None:
    print(C.bold("\n■ Coverage"))
    v2 = cov["v2"]
    v2s = C.green(f"{v2} v2.0") if v2 else C.yellow("0 v2.0 (none yet)")
    print(f"  predictions: {cov['total']} total — {v2s}, {cov['v1']} v1")
    print(f"  by version : {cov['by_version']}")
    print(f"  by round   : {cov['by_round']}")
    tr = cov["traces"]
    trs = C.green(f"{tr} traces ({cov['trace_matches']} matches)") if tr else C.yellow("0 traces (agent_traces empty)")
    print(f"  agent_traces: {trs}")


def print_board(rows: list[dict], round_no: int) -> None:
    print(C.bold(f"\n■ Round {round_no} board") + C.dim(f"  ({len(rows)} matches)"))
    if not rows:
        print(C.dim("  no predictions for this round"))
        return
    print(C.dim(f"  {'match':<28} {'pick':<14} {'mgn':>4} {'conf':<7} {'diff':<10} {'result':<18} {'':<3}"))
    for r in rows:
        mark = ""
        if r["correct"] is True:
            mark = C.green("✓")
        elif r["correct"] is False:
            mark = C.red("✗")
        result = ""
        if r["actual_winner"]:
            me = f" Δ{r['margin_err']}" if r["margin_err"] is not None else ""
            result = f"{r['actual_winner']} {r['actual_score'] or ''}{me}"
        diff = r["difficulty"] or C.dim("—")
        mgn = r["margin"] if r["margin"] is not None else "?"
        print(f"  {r['match']:<28} {r['winner']:<14} {str(mgn):>4} {r['confidence']:<7} "
              f"{str(diff):<10} {result:<18} {mark}")


def print_trace(match_id: str, t: dict | None) -> None:
    print(C.bold(f"\n■ Trace — {norm_match(match_id)}"))
    if not t:
        print(C.yellow("  no trace found (agent_traces has no row for this match yet)"))
        return
    print(C.dim(f"  difficulty={t.get('difficulty')}  primary_model={t.get('primary_model')}  "
                f"generatedAt={t.get('generatedAt')}"))
    entries = t.get("trace_entries") or []
    if not entries:
        print(C.dim("  trace row exists but has no tool entries"))
        return
    last_node = None
    for e in entries:
        node = e.get("node", "?")
        if node != last_node:
            print(C.cyan(f"  ▸ {node}"))
            last_node = node
        out = str(e.get("output", ""))
        out = out[:90] + "…" if len(out) > 90 else out
        print(f"      {e.get('tool', '?'):<22} {C.dim(out)}")


# ── HTML rendering (self-contained) ──────────────────────────────────────────

_CSS = """
:root{--bg:#0f1419;--card:#1a212b;--ink:#e6edf3;--mut:#8b98a5;--line:#2d3742;
--ok:#1565C0;--bad:#E65100;--accent:#3fb950}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:24px 0 8px;color:var(--accent)}
.sub{color:var(--mut);font-size:12px;margin-bottom:16px}
.cards{display:flex;gap:12px;flex-wrap:wrap}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px;min-width:140px}
.card .n{font-size:22px;font-weight:700}.card .l{color:var(--mut);font-size:12px}
.warn{color:#d29922}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
border-radius:8px;overflow:hidden;margin-bottom:8px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);font-size:13px}
th{color:var(--mut);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
tr:last-child td{border-bottom:none}
.ok{color:var(--ok);font-weight:700}.bad{color:var(--bad);font-weight:700}
.mut{color:var(--mut)}.pill{font-size:11px;padding:1px 7px;border-radius:10px;border:1px solid var(--line)}
details{background:var(--card);border:1px solid var(--line);border-radius:8px;margin-bottom:8px}
summary{padding:10px 14px;cursor:pointer;font-weight:600}
.trace{padding:0 14px 12px}.node{color:#58a6ff;margin:8px 0 2px;font-weight:600}
.te{padding-left:18px;font-size:12px}.te .t{color:var(--ink)}.te .o{color:var(--mut)}
"""


def _conf_pill(c: str) -> str:
    return f'<span class="pill">{html.escape(str(c))}</span>'


def _board_table(rows: list[dict]) -> str:
    if not rows:
        return '<p class="mut">no predictions for this round</p>'
    head = ("<tr><th>match</th><th>pick</th><th>mgn</th><th>conf</th><th>difficulty</th>"
            "<th>challenge</th><th>upset</th><th>result</th><th>ver</th></tr>")
    body = []
    for r in rows:
        if r["correct"] is True:
            res = f'<span class="ok">✓ {html.escape(str(r["actual_winner"]))} {r["actual_score"] or ""}</span>'
        elif r["correct"] is False:
            res = f'<span class="bad">✗ {html.escape(str(r["actual_winner"]))} {r["actual_score"] or ""}</span>'
        else:
            res = '<span class="mut">—</span>'
        if r["margin_err"] is not None:
            res += f' <span class="mut">Δ{r["margin_err"]}</span>'
        upset = f'{r["upset"]:.0%}' if isinstance(r["upset"], float) else '<span class="mut">—</span>'
        body.append(
            "<tr>"
            f'<td>{html.escape(r["match"])}</td>'
            f'<td>{html.escape(str(r["winner"]))}</td>'
            f'<td>{r["margin"] if r["margin"] is not None else "?"}</td>'
            f'<td>{_conf_pill(r["confidence"])}</td>'
            f'<td>{html.escape(str(r["difficulty"] or "—"))}</td>'
            f'<td>{html.escape(str(r["challenge_strength"] or "—"))}</td>'
            f'<td>{upset}</td>'
            f'<td>{res}</td>'
            f'<td class="mut">{html.escape(str(r["prompt_version"]))}</td>'
            "</tr>"
        )
    return f"<table>{head}{''.join(body)}</table>"


def _trace_html(t: dict) -> str:
    entries = t.get("trace_entries") or []
    if not entries:
        return '<div class="trace mut">trace row exists but has no tool entries</div>'
    out, last = ['<div class="trace">'], None
    for e in entries:
        node = e.get("node", "?")
        if node != last:
            out.append(f'<div class="node">▸ {html.escape(str(node))}</div>')
            last = node
        o = str(e.get("output", ""))
        o = html.escape(o[:140] + "…" if len(o) > 140 else o)
        out.append(f'<div class="te"><span class="t">{html.escape(str(e.get("tool", "?")))}</span> '
                   f'<span class="o">{o}</span></div>')
    out.append("</div>")
    return "".join(out)


def render_html(cov: dict, preds: list[dict], results: list[dict], traces: list[dict],
                rounds: list[int]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    v2_card = (f'<div class="n">{cov["v2"]}</div>' if cov["v2"]
               else '<div class="n warn">0</div>')
    tr_card = (f'<div class="n">{cov["traces"]}</div>' if cov["traces"]
               else '<div class="n warn">0</div>')
    parts = [
        f"<!doctype html><meta charset=utf-8><title>nrl-inspect</title><style>{_CSS}</style>",
        '<div class="wrap">',
        "<h1>nrl-predictor2 · inspect</h1>",
        f'<div class="sub">{now} · region {html.escape(REGION)}</div>',
        "<h2>Coverage</h2>",
        '<div class="cards">',
        f'<div class="card"><div class="n">{cov["total"]}</div><div class="l">predictions</div></div>',
        f'<div class="card">{v2_card}<div class="l">v2.0 rows</div></div>',
        f'<div class="card"><div class="n">{cov["v1"]}</div><div class="l">v1 rows</div></div>',
        f'<div class="card">{tr_card}<div class="l">agent traces</div></div>',
        f'<div class="card"><div class="n">{len(rounds)}</div><div class="l">rounds</div></div>',
        "</div>",
    ]
    parts.append("<h2>Round boards</h2>")
    for rn in sorted(rounds, reverse=True):
        rows = board_rows(preds, results, rn)
        scored = sum(1 for r in rows if r["correct"] is not None)
        hits = sum(1 for r in rows if r["correct"])
        acc = f" · {hits}/{scored} correct" if scored else ""
        parts.append(
            f'<details {"open" if rn == max(rounds) else ""}>'
            f'<summary>Round {rn} <span class="mut">({len(rows)} matches{acc})</span></summary>'
            f'<div style="padding:0 14px 12px">{_board_table(rows)}</div></details>'
        )
    parts.append("<h2>Agent traces</h2>")
    if not traces:
        parts.append('<p class="warn">No agent traces yet — the agent_traces table is empty. '
                     "This section fills once the v2 pipeline runs.</p>")
    else:
        for t in sorted(traces, key=lambda x: x.get("generatedAt", ""), reverse=True):
            mid = norm_match(t.get("matchId", ""))
            parts.append(
                f'<details><summary>{html.escape(mid)} '
                f'<span class="mut">{html.escape(str(t.get("difficulty") or ""))} · '
                f'{html.escape(str(t.get("primary_model") or ""))}</span></summary>'
                f"{_trace_html(t)}</details>"
            )
    parts.append("</div>")
    return "".join(parts)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nrl-inspect", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--round", type=int, help="round number for the terminal board (default: latest)")
    ap.add_argument("--match", help="matchId to show a pipeline trace for")
    ap.add_argument("--html", metavar="FILE", help="also write a self-contained HTML snapshot")
    ap.add_argument("--all", action="store_true", help="(terminal) print a board for every round")
    ap.add_argument("--region", help="AWS region (default: $AWS_REGION or ap-southeast-2)")
    args = ap.parse_args(argv)

    global REGION
    if args.region:
        REGION = args.region

    print(C.dim(f"reading DynamoDB in {REGION} …"), file=sys.stderr)
    preds = scan_table("predictions")
    results = scan_table("results")
    traces = scan_table("agent_traces")

    cov = coverage(preds, traces)
    rounds = all_rounds(preds)

    print_coverage(cov)

    if rounds:
        targets = rounds if args.all else [args.round or max(rounds)]
        for rn in targets:
            print_board(board_rows(preds, results, rn), rn)
    else:
        print(C.yellow("\nno rounds found in predictions"))

    if args.match:
        print_trace(args.match, trace_for(traces, args.match))

    if args.html:
        out = render_html(cov, preds, results, traces, rounds)
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(out)
        print(C.bold(f"\n→ wrote {args.html}") + C.dim(f" ({len(out):,} bytes)"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
