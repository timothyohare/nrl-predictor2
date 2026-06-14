#!/usr/bin/env python3
"""nrl-predictor2 dashboard — interactive view of inputs, outputs & progress.

Plan B from docs/visualization-plans.md. A Streamlit app over the same DynamoDB
tables the CLI reads, reusing tools/inspector.py as the data layer.

Run:
    streamlit run tools/dashboard.py
    # or, with a region:  AWS_REGION=ap-southeast-2 streamlit run tools/dashboard.py

Pages
-----
- Run monitor        : freshness + "how much of the live round is done" (auto-refresh).
- Round boards       : predictions joined to results, per round, with ✓/✗ + margin error.
- Variant scoreboard : prompt_variants ⋈ simulation_predictions/variant_metrics — "what worked best".
- Match explorer     : one match — Primary/Challenger/Judge detail + agent-trace timeline.
- Calibration        : confidence reliability, margin-error, predicted-vs-actual scatter.

Empty v2/experiment tables are expected today and render as "pending", not errors.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

# Make `tools.inspector` importable when launched via `streamlit run tools/dashboard.py`
# (which puts tools/ — not the repo root — on sys.path[0]).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools.inspector as ins  # noqa: E402

DATA_TTL = 30  # seconds; bounds how stale the auto-refreshing monitor can get
V2 = ins.V2_PROMPT_VERSION


# ── Data layer (cached) ──────────────────────────────────────────────────────

@st.cache_data(ttl=DATA_TTL, show_spinner="Reading DynamoDB…")
def load(region: str) -> dict:
    """One cached read pass of every table the dashboard needs."""
    ins.REGION = region
    return {
        "predictions": ins.scan_table("predictions"),
        "results": ins.scan_table("results"),
        "traces": ins.scan_table("agent_traces"),
        "variants": ins.scan_table("prompt_variants"),
        "variant_metrics": ins.scan_table("variant_metrics"),
        "simulations": ins.scan_table("simulation_predictions"),
    }


def predictions_frame(preds: list[dict], results: list[dict]) -> pd.DataFrame:
    """Latest prediction per match, joined to its actual result, as a DataFrame."""
    res_idx = ins.results_by_slug(results)
    rows = []
    for mid, p in ins.latest_per_match(preds).items():
        res = res_idx.get(ins.norm_match(mid))
        winner = p.get("predicted_winner")
        pmargin = ins.num(p.get("predicted_margin"))
        amargin = ins.num(res.get("margin")) if res else None
        correct = None
        if res and winner:
            correct = str(winner).lower() == str(res.get("winner", "")).lower()
        rows.append({
            "match": ins.norm_match(mid),
            "round": ins.round_of(p),
            "pick": winner,
            "pred_margin": pmargin,
            "confidence": p.get("confidence"),
            "difficulty": p.get("agent_difficulty"),
            "version": p.get("prompt_version", "—"),
            "upset": ins.num(p.get("upset_probability")),
            "actual_winner": res.get("winner") if res else None,
            "actual_margin": amargin,
            "correct": correct,
            "abs_err": (abs(pmargin - amargin)
                        if pmargin is not None and amargin is not None else None),
            "generatedAt": p.get("generatedAt"),
        })
    return pd.DataFrame(rows)


def latest_by_key(items: list[dict], key: str, sort_key: str) -> dict[str, dict]:
    """Collapse rows to the latest per `key` (by `sort_key`)."""
    best: dict[str, dict] = {}
    for it in items:
        k = it.get(key)
        if k is None:
            continue
        if k not in best or it.get(sort_key, "") > best[k].get(sort_key, ""):
            best[k] = it
    return best


# ── Pages ────────────────────────────────────────────────────────────────────

def page_monitor(data: dict) -> None:
    st.subheader("Run monitor")
    preds, traces = data["predictions"], data["traces"]
    df = predictions_frame(preds, data["results"])

    last_pred = max((p.get("generatedAt", "") for p in preds), default="")
    last_trace = max((t.get("generatedAt", "") for t in traces), default="")
    rounds = ins.all_rounds(preds)
    latest_round = max(rounds) if rounds else None
    in_round = df[df["round"] == latest_round] if latest_round is not None else df.iloc[0:0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Predictions", len(preds))
    c2.metric(f"Latest round (R{latest_round})", len(in_round) if latest_round else 0,
              help="matches with a prediction in the most recent round")
    c3.metric("Agent traces", len(traces),
              delta="empty" if not traces else None, delta_color="off")
    c4.metric("Last prediction", _ago(last_pred))

    if last_trace:
        st.caption(f"Last agent trace: {_ago(last_trace)} ({last_trace})")
    else:
        st.info("agent_traces is empty — the v2 pipeline has not written a trace yet.")

    st.markdown("**Most recent predictions**")
    recent = (df.sort_values("generatedAt", ascending=False)
              [["generatedAt", "round", "match", "pick", "pred_margin", "confidence", "version"]]
              .head(15))
    st.dataframe(recent, hide_index=True, width="stretch")


def page_boards(data: dict) -> None:
    st.subheader("Round boards")
    preds, results = data["predictions"], data["results"]
    rounds = ins.all_rounds(preds)
    if not rounds:
        st.warning("No rounds found in predictions.")
        return
    rn = st.selectbox("Round", sorted(rounds, reverse=True), index=0)
    rows = ins.board_rows(preds, results, rn)
    scored = [r for r in rows if r["correct"] is not None]
    if scored:
        hits = sum(1 for r in scored if r["correct"])
        mae = sum(r["margin_err"] for r in scored if r["margin_err"] is not None) / max(
            1, sum(1 for r in scored if r["margin_err"] is not None))
        a, b = st.columns(2)
        a.metric("Winner accuracy", f"{hits}/{len(scored)}", f"{hits / len(scored):.0%}")
        b.metric("Mean margin error", f"{mae:.1f} pts")

    df = pd.DataFrame([{
        "match": r["match"], "pick": r["winner"], "margin": r["margin"],
        "conf": r["confidence"], "difficulty": r["difficulty"] or "—",
        "challenge": r["challenge_strength"] or "—",
        "upset": f"{r['upset']:.0%}" if isinstance(r["upset"], float) else "—",
        "result": (("✓ " if r["correct"] else "✗ ") + f"{r['actual_winner']} {r['actual_score'] or ''}"
                   if r["actual_winner"] else "—"),
        "Δmargin": r["margin_err"] if r["margin_err"] is not None else None,
        "ver": r["prompt_version"],
    } for r in rows])
    st.dataframe(df, hide_index=True, width="stretch")


def page_variants(data: dict) -> None:
    st.subheader("Variant scoreboard")
    st.caption("Each row is a prompt experiment. Accuracy fills in once "
               "`simulation_predictions` / `variant_metrics` are populated.")
    variants = latest_by_key(data["variants"], "variantId", "version")
    if not variants:
        st.warning("prompt_variants is empty.")
        return

    sims_by_variant: dict[str, list[dict]] = {}
    for s in data["simulations"]:
        sims_by_variant.setdefault(s.get("variantId"), []).append(s)
    metrics = latest_by_key(data["variant_metrics"], "variantId", "period")
    res_idx = ins.results_by_slug(data["results"])

    rows = []
    for vid, v in sorted(variants.items()):
        sims = sims_by_variant.get(vid, [])
        scored = correct = 0
        for s in sims:
            res = res_idx.get(ins.norm_match(s.get("matchId", "")))
            if res and s.get("predicted_winner"):
                scored += 1
                correct += str(s["predicted_winner"]).lower() == str(res.get("winner", "")).lower()
        m = metrics.get(vid, {})
        rows.append({
            "variantId": vid,
            "dimensions": ", ".join(v.get("dimensions", []) or []),
            "active": bool(v.get("active")),
            "n_sims": len(sims),
            "accuracy": (f"{correct}/{scored} ({correct / scored:.0%})" if scored
                         else (m.get("accuracy", "—") if m else "pending")),
            "stored_metric_period": m.get("period", "—") if m else "—",
            "hypothesis": v.get("hypothesis", ""),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"hypothesis": st.column_config.TextColumn(width="large")})

    with st.expander("Inspect a variant's prompt template"):
        vid = st.selectbox("Variant", sorted(variants))
        st.code(variants[vid].get("prompt_template", "(none)"), language="markdown")


def page_match(data: dict) -> None:
    st.subheader("Match explorer")
    preds = data["predictions"]
    rounds = ins.all_rounds(preds)
    if not rounds:
        st.warning("No predictions yet.")
        return
    rn = st.selectbox("Round", sorted(rounds, reverse=True))
    latest = ins.latest_per_match([p for p in preds if ins.round_of(p) == rn])
    if not latest:
        st.info("No matches in this round.")
        return
    mid = st.selectbox("Match", sorted(latest, key=ins.norm_match),
                       format_func=ins.norm_match)
    p = latest[mid]

    top = st.columns(3)
    top[0].metric("Pick", str(p.get("predicted_winner", "?")))
    top[1].metric("Margin", ins.num(p.get("predicted_margin"), "?"))
    top[2].metric("Confidence", str(p.get("confidence", "?")))
    if p.get("key_factors"):
        st.markdown("**Key factors:** " + " · ".join(p["key_factors"]))
    if p.get("reasoning"):
        st.markdown("**Final reasoning**")
        st.write(p["reasoning"])

    has_v2 = any(p.get(k) for k in ("challenge_strength", "primary_reasoning", "judge_rationale"))
    if has_v2:
        st.markdown("### Multi-agent breakdown")
        cols = st.columns(3)
        with cols[0]:
            st.markdown("**Primary**")
            st.write(p.get("primary_reasoning", "—"))
        with cols[1]:
            st.markdown(f"**Challenger** · {p.get('challenge_strength', '—')}")
            st.write(p.get("challenge_reasoning", "—"))
        with cols[2]:
            accepted = p.get("primary_accepted")
            st.markdown(f"**Judge** · {'kept Primary' if accepted else 'overruled Primary'}")
            st.write(p.get("judge_rationale", "—"))
    else:
        st.caption("Multi-agent (Primary/Challenger/Judge) detail appears here once a "
                   "v2.0 prediction exists for this match.")

    st.markdown("### Agent trace")
    t = ins.trace_for(data["traces"], mid)
    if not t:
        st.info("No agent_traces row for this match yet.")
    else:
        st.caption(f"difficulty={t.get('difficulty')} · primary_model={t.get('primary_model')}")
        for e in t.get("trace_entries", []) or []:
            st.markdown(f"**{e.get('node', '?')}** · `{e.get('tool', '?')}` — "
                        f"{str(e.get('output', ''))[:200]}")


def page_calibration(data: dict) -> None:
    st.subheader("Calibration & accuracy")
    df = predictions_frame(data["predictions"], data["results"])
    scored = df[df["correct"].notna()].copy()
    if scored.empty:
        st.warning("No scored predictions yet (need matching rows in `results`).")
        return

    rounds = sorted(r for r in df["round"].dropna().unique())
    sel = st.multiselect("Rounds", rounds, default=rounds)
    if sel:
        scored = scored[scored["round"].isin(sel)]
    if scored.empty:
        st.info("No scored predictions for that filter.")
        return

    a, b = st.columns(2)
    a.metric("Overall accuracy", f"{scored['correct'].mean():.0%}",
             f"{int(scored['correct'].sum())}/{len(scored)}")
    mae = scored["abs_err"].dropna()
    b.metric("Mean margin error", f"{mae.mean():.1f} pts" if not mae.empty else "—")

    st.markdown("**Confidence reliability** — win-rate by stated confidence")
    order = ["LOW", "MEDIUM", "HIGH"]
    rel = (scored.assign(confidence=scored["confidence"].fillna("?"))
           .groupby("confidence")["correct"].agg(["mean", "count"]))
    rel = rel.reindex([c for c in order if c in rel.index] +
                      [c for c in rel.index if c not in order])
    st.bar_chart(rel["mean"], width="stretch", y_label="win rate")
    st.caption("counts: " + ", ".join(f"{i}={int(r['count'])}" for i, r in rel.iterrows()))

    st.markdown("**Predicted vs actual margin** (absolute points)")
    sc = scored.dropna(subset=["pred_margin", "actual_margin"])
    if not sc.empty:
        st.scatter_chart(sc, x="pred_margin", y="actual_margin", color="correct",
                         width="stretch")
    else:
        st.caption("no rows with both predicted and actual margins")


# ── helpers ──────────────────────────────────────────────────────────────────

def _ago(iso: str) -> str:
    if not iso:
        return "—"
    try:
        then = datetime.fromisoformat(iso)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        secs = (datetime.now(timezone.utc) - then).total_seconds()
    except ValueError:
        return iso
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= n:
            return f"{int(secs // n)}{unit} ago"
    return "just now"


# ── App shell ────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(page_title="nrl-predictor2", layout="wide")
    st.title("nrl-predictor2 · dashboard")

    region = st.sidebar.text_input("AWS region", ins.REGION)
    if st.sidebar.button("↻ Refresh data now"):
        st.cache_data.clear()
        st.rerun()
    interval = st.sidebar.slider("Auto-refresh (s, 0 = off)", 0, 120, 0, step=10)
    st.sidebar.caption(f"data cached for {DATA_TTL}s")

    data = load(region)
    v2 = sum(1 for p in data["predictions"] if p.get("prompt_version") == V2)
    if v2 == 0:
        st.warning("No **v2.0** predictions in DynamoDB yet — multi-agent views show "
                   "v1 data and 'pending' placeholders until the v2 pipeline runs.")

    pages = {
        "Run monitor": page_monitor,
        "Round boards": page_boards,
        "Variant scoreboard": page_variants,
        "Match explorer": page_match,
        "Calibration": page_calibration,
    }
    choice = st.sidebar.radio("View", list(pages))

    if choice == "Run monitor" and interval:
        # Reload inside the fragment so each tick fetches fresh data (bounded by DATA_TTL),
        # rather than re-rendering the snapshot captured on first run.
        @st.fragment(run_every=f"{interval}s")
        def _live_monitor() -> None:
            page_monitor(load(region))
        _live_monitor()
    else:
        pages[choice](data)


if __name__ == "__main__":
    main()
