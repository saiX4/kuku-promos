"""Streamlit front end for Find the Promos.

Run locally:   streamlit run app.py
Deploy:        see README_STREAMLIT.md
"""
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import fallback, generate, score, shortlist, suppress  # noqa: E402
from main import load_env, serialize  # noqa: E402
from parser import parse_script, timecode  # noqa: E402
from report import render_report  # noqa: E402
from semantic import GeminiEvaluator  # noqa: E402

st.set_page_config(page_title="Find the Promos", page_icon="🎬", layout="wide")


# ----------------------------------------------------------------- helpers
def secret(name):
    """Read a Streamlit secret without crashing when no secrets file exists."""
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def password_gate():
    """Optional: set APP_PASSWORD in secrets to lock a public deployment."""
    expected = secret("APP_PASSWORD")
    if not expected or st.session_state.get("authed"):
        return
    st.title("🎬 Find the Promos")
    entered = st.text_input("Password", type="password")
    if entered and entered == expected:
        st.session_state["authed"] = True
        st.rerun()
    elif entered:
        st.error("Wrong password.")
    st.stop()


def run_pipeline(paths, evaluator, p, log, progress):
    """Same steps as main.run(), but reports progress and keeps rejected clips."""
    selected, evaluated, seen = [], [], set()
    total_steps = len(paths)
    for file_no, path in enumerate(paths):
        entries, warnings = parse_script(path)
        episode = entries[0].episode_id
        if episode in seen:
            raise ValueError(f"Duplicate episode ID: {episode} ({path.name})")
        seen.add(episode)
        for w in warnings:
            log(f"⚠️ {path.name}:{w['line']}: {w['reason']}")
        candidates = [score(c) for c in generate(entries, p["min_duration"], p["max_duration"])]
        chosen = shortlist(candidates, p["shortlist_fraction"], p["max_candidates"])
        log(f"**{episode}** — {len(candidates)} valid windows, evaluating {len(chosen)}")
        for i, cand in enumerate(chosen, 1):
            try:
                cand.evaluation = evaluator.evaluate(cand)
            except (ValueError, KeyError, TypeError) as exc:
                log(f"⚠️ skipped {cand.candidate_id} after retries: {exc}")
                continue
            except RuntimeError as exc:
                raise RuntimeError(f"{cand.candidate_id}: {exc}") from None
            ev = cand.evaluation
            evaluated.append({
                "Episode": episode, "Start": timecode(cand.start_sec), "End": timecode(cand.end_sec),
                "Gemini score": ev["viral_score"], "Standalone": ev["standalone"],
                "Reason": ev["justification"],
            })
            progress.progress((file_no + i / max(1, len(chosen))) / total_steps,
                              text=f"{episode}: clip {i}/{len(chosen)}")
        chosen = [c for c in chosen if c.evaluation]
        picks = suppress(chosen, p["iou_threshold"], p["promos_per_episode"])
        if not picks:
            picks = fallback(chosen)
        selected.extend((c, path.name) for c in picks)
        log(f"**{episode}** — {len(picks)} promos selected")
    selected.sort(key=lambda it: (-it[0].evaluation["viral_score"], -it[0].scores["raw"],
                                  it[0].episode_id, it[0].start_sec))
    promos = [serialize(c, src, rank) for rank, (c, src) in enumerate(selected, 1)]
    return promos, evaluated


def build_html(promos):
    with tempfile.TemporaryDirectory() as tmp:
        render_report(Path(tmp), promos)
        return (Path(tmp) / "report.html").read_text(encoding="utf-8")


# --------------------------------------------------------------------- UI
password_gate()
load_env()  # picks up code/.env when running locally

with st.sidebar:
    st.header("Settings")
    key_default = secret("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    api_key = st.text_input("Gemini API key", type="password", value="",
                            placeholder="Using saved key" if key_default else "Paste your key",
                            help="Get one free at aistudio.google.com/apikey. Never stored on disk.")
    api_key = api_key.strip() or key_default
    model = st.text_input("Model", value=os.environ.get("GEMINI_MODEL") or GeminiEvaluator.default_model)

    st.subheader("Clip search")
    max_candidates = st.slider("Clips sent to Gemini per episode", 1, 20, 8,
                               help="More = better chance of good promos, more API calls.")
    shortlist_fraction = st.slider("Shortlist fraction", 0.05, 1.0, 0.15, 0.05)
    promos_per_episode = st.slider("Max promos per episode", 1, 6, 3)
    min_d, max_d = st.slider("Clip length (seconds)", 20, 60, (20, 60))
    iou = st.slider("Overlap allowed (IoU)", 0.0, 1.0, 0.4, 0.05,
                    help="0 forbids any overlap between promos in the same episode.")
    interval = st.slider("Seconds between API calls", 0, 30, 6,
                         help="Raise this if you see HTTP 429 rate-limit errors.")

st.title("🎬 Find the Promos")
st.caption("Upload timestamped screenplay TXT files (one episode per file). "
           "Gemini ranks the best 20–60 second promo clips.")

uploads = st.file_uploader("Episode TXT files", type=["txt"], accept_multiple_files=True)
limit = st.number_input("Only process the first N files (0 = all)", min_value=0, value=0, step=1)

go = st.button("Find promos", type="primary", disabled=not uploads)

if go:
    if not api_key:
        st.error("Add a Gemini API key in the sidebar.")
        st.stop()
    os.environ["GEMINI_API_KEY"] = api_key
    st.session_state.pop("result", None)
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for f in sorted(uploads, key=lambda u: u.name):
            target = Path(tmp) / Path(f.name).name
            target.write_bytes(f.getvalue())
            paths.append(target)
        if limit:
            paths = paths[:int(limit)]
        params = dict(min_duration=float(min_d), max_duration=float(max_d),
                      shortlist_fraction=shortlist_fraction, max_candidates=max_candidates,
                      promos_per_episode=promos_per_episode, iou_threshold=iou)
        progress = st.progress(0.0, text="Starting…")
        with st.status("Working…", expanded=True) as status:
            try:
                evaluator = GeminiEvaluator(model, request_interval=float(interval))
                promos, evaluated = run_pipeline(paths, evaluator, params, st.write, progress)
            except (ValueError, RuntimeError, OSError) as exc:
                status.update(label="Failed", state="error")
                st.error(str(exc))
                st.stop()
            status.update(label=f"Done: {len(promos)} promos, {evaluator.calls} API calls", state="complete")
        progress.empty()
        st.session_state["result"] = {
            "promos": promos, "evaluated": evaluated, "html": build_html(promos),
            "usage": evaluator.usage, "calls": evaluator.calls,
        }

res = st.session_state.get("result")
if res:
    promos, evaluated = res["promos"], res["evaluated"]
    tab_promos, tab_all, tab_html = st.tabs(
        [f"Ranked promos ({len(promos)})", f"All evaluated clips ({len(evaluated)})", "HTML report"])

    with tab_promos:
        if not promos:
            st.warning("Gemini rejected every clip it saw. Open the “All evaluated clips” tab to see why, "
                       "then try more clips per episode or a longer shortlist.")
        for p in promos:
            seg = p["segments"][0]
            with st.container(border=True):
                a, b, c = st.columns([1, 4, 1.5])
                a.metric("Rank", f"#{p['rank']}")
                b.subheader(f"{p['episode_id']}  ·  {seg['start_timestamp']} → {seg['end_timestamp']}")
                b.caption(f"{p['duration_sec']:.1f}s  ·  {seg['source_file']}")
                c.metric("Gemini score", f"{p['viral_score']:.0f}")
                st.markdown(f"**Hook:** {p['hook']['quote']}")
                st.markdown(f"**Cliffhanger:** {p['cliffhanger']['quote']}")
                st.write(p["justification"])
                with st.expander("Dialogue and action"):
                    for e in p["transcript"]:
                        who = e["speaker"] if e["kind"] == "dialogue" else "ACTION"
                        st.markdown(f"`{e['start_timestamp']}` **{who}:** {e['content']}")

    with tab_all:
        st.caption("Every clip sent to Gemini, including rejected ones.")
        st.dataframe(pd.DataFrame(evaluated), use_container_width=True, hide_index=True)

    with tab_html:
        st.download_button("Download report.html", res["html"], file_name="report.html", mime="text/html")
        components.html(res["html"], height=900, scrolling=True)

    st.caption(f"{res['calls']} API calls · tokens: {res['usage']}")