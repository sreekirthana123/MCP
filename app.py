"""
The Draft Desk - Streamlit UI for the Chief of Staff workflow.

Phases (driven by session_state.current_phase):
   1. Inbox & Triage
   2. Draft Generation
   3. Approval Gate
   4. Export Proof
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import streamlit as st

# -----------------------------------------------------------------------------
# Page config
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="The Draft Desk",
    page_icon="✍️",
    layout="wide",
)

# -----------------------------------------------------------------------------
# Paths & constants
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
SAMPLE_THREADS_PATH = BASE_DIR / "sample_threads.json"

PHASES = [
    "Inbox & Triage",
    "Draft Generation",
    "Approval Gate",
    "Export Proof",
]

# -----------------------------------------------------------------------------
# Local imports
# -----------------------------------------------------------------------------
import sys
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "Gmail-MCP-Server"))
from triage import triage_inbox
from draft_machine import draft_reply_with_metadata

# -----------------------------------------------------------------------------
# Session state initialization
# -----------------------------------------------------------------------------
def _init_session_state() -> None:
    """Initialize all session_state keys we rely on."""
    defaults: dict[str, Any] = {
        "threads": [],           # list[dict] - loaded email threads
        "triaged": {},           # dict[str, str] - subject -> priority bucket
        "drafts": {},            # dict[str, str] - thread_id -> draft body
        "approved": {},          # dict[str, str] - thread_id -> approved draft
        "rejected": [],          # list[str] - thread_ids that were rejected
        "current_phase": "Inbox & Triage",
        "source": "Sample threads",  # "Sample threads" | "Gmail via engine.py"
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

_init_session_state()


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def load_sample_threads() -> list[dict[str, Any]]:
    """Load sample threads from disk; return [] on any failure."""
    if not SAMPLE_THREADS_PATH.exists():
        return []
    try:
        with SAMPLE_THREADS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except (json.JSONDecodeError, OSError):
        return []


def get_priority_for_thread(thread: dict[str, Any]) -> str | None:
    """Look up the triaged priority for a thread by subject."""
    subject = thread.get("subject", "")
    return st.session_state.triaged.get(subject)


def render_priority_badge(priority: str) -> None:
    """Render a coloured priority label."""
    badges = {
        "urgent":      "🔴 **Urgent**",
        "needs-reply": "🟡 **Needs Reply**",
        "fyi":         "🔵 **FYI**",
        "ignore":      "⚪ **Ignore**",
    }
    st.markdown(badges.get(priority, f"❓ **{priority}**"))


def render_thread_card(thread: dict[str, Any]) -> None:
    """Render a single thread as a compact, expandable card."""
    subject = thread.get("subject", "(no subject)")
    thread_id = thread.get("id", "?")
    messages = thread.get("messages", []) or []

    first = messages[0] if messages else {}
    sender = first.get("from", "Unknown sender")
    date = first.get("date", "")
    preview = (first.get("body") or "").strip().replace("\n", " ")
    if len(preview) > 180:
        preview = preview[:177] + "..."

    with st.container(border=True):
        col_a, col_b = st.columns([4, 1])
        with col_a:
            st.markdown(f"**{subject}**")
            st.caption(f"From: {sender}  •  {date}  •  {len(messages)} message(s)")
            st.write(preview)
        with col_b:
            st.caption(f"ID: `{thread_id}`")
            priority = get_priority_for_thread(thread)
            if priority:
                render_priority_badge(priority)
            with st.popover("Open"):
                for i, msg in enumerate(messages, start=1):
                    st.markdown(
                        f"**{i}. {msg.get('from', '?')}** "
                        f"• {msg.get('date', '')}"
                    )
                    st.write(msg.get("body", ""))
                    if i < len(messages):
                        st.divider()


# -----------------------------------------------------------------------------
# Sidebar
# -----------------------------------------------------------------------------
def render_sidebar() -> None:
    with st.sidebar:
        st.title("✍️ The Draft Desk")
        st.caption("Chief of Staff – Draft workflow")
        st.divider()

        st.subheader("Source")
        st.session_state.source = st.radio(
            "Where do threads come from?",
            options=["Sample threads", "Gmail via engine.py"],
            index=0 if st.session_state.source == "Sample threads" else 1,
            label_visibility="collapsed",
            key="source_radio",
        )

        if st.session_state.source == "Gmail via engine.py":
            st.caption("Gmail integration will run when you click *Pull & Triage*.")

        st.divider()
        st.subheader("Navigation")

        for phase in PHASES:
            is_current = st.session_state.current_phase == phase
            label = f"▶️ {phase}" if is_current else phase
            if st.button(label, key=f"nav_{phase}", use_container_width=True):
                st.session_state.current_phase = phase
                st.rerun()

        st.divider()
        st.caption(
            f"Loaded: **{len(st.session_state.threads)}** thread(s)\n"
            f"Triaged: **{len(st.session_state.triaged)}**\n"
            f"Drafts: **{len(st.session_state.drafts)}**\n"
            f"Approved: **{len(st.session_state.approved)}**\n"
            f"Rejected: **{len(st.session_state.rejected)}**"
        )


# -----------------------------------------------------------------------------
# Phase: Inbox & Triage
# -----------------------------------------------------------------------------
def render_inbox_phase() -> None:
    st.header("📥 Inbox & Triage")
    st.write(
        "Pull threads from the selected source, then triage them by priority. "
        "Once triaged, the highest-priority threads move to *Draft Generation*."
    )

    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        pull_clicked = st.button(
            "Pull & Triage",
            type="primary",
            use_container_width=True,
        )

    with col2:
        if st.button("Clear", use_container_width=True):
            st.session_state.threads = []
            st.session_state.triaged = {}
            st.session_state.drafts = {}
            st.session_state.approved = {}
            st.session_state.rejected = []
            st.rerun()

    if pull_clicked:
        source = st.session_state.source
        if source == "Sample threads":
            loaded = load_sample_threads()
            if not loaded:
                st.error(
                    f"No threads found at `{SAMPLE_THREADS_PATH.name}`. "
                    "Make sure the file exists and is valid JSON."
                )
            else:
                st.session_state.threads = loaded
                st.session_state.triaged = {}  # reset on fresh pull

                # ── Wire triage ──────────────────────────────────────────────
                triage_input = [
                    {
                        "sender": (t.get("messages") or [{}])[0].get("from", ""),
                        "subject": t.get("subject", ""),
                        "snippet": (t.get("messages") or [{}])[0].get("body", "")[:150],
                    }
                    for t in loaded
                ]
                with st.spinner("Triaging threads..."):
                    triaged_results = triage_inbox(triage_input)

                for r in triaged_results:
                    subject = r.get("subject", "")
                    priority = r.get("priority", "unknown")
                    st.session_state.triaged[subject] = priority

                st.success(
                    f"Loaded and triaged {len(loaded)} thread(s). "
                    f"Priorities assigned: {len(st.session_state.triaged)}"
                )
        else:
            st.info(
                "Gmail pull via `engine.py` isn't wired up in this build yet. "
                "Switch the source to *Sample threads* to keep going."
            )

    st.divider()

    threads = st.session_state.threads
    if not threads:
        st.info("No threads loaded yet. Click **Pull & Triage** to get started.")
        return

    # Sort controls
    sort_options = ["Most recent first", "Oldest first", "Most messages first"]
    sort_by = st.selectbox("Sort by", options=sort_options, index=0)

    sorted_threads = list(threads)
    if sort_by == "Most recent first":
        sorted_threads.sort(
            key=lambda t: (t.get("messages") or [{}])[0].get("date", ""),
            reverse=True,
        )
    elif sort_by == "Oldest first":
        sorted_threads.sort(
            key=lambda t: (t.get("messages") or [{}])[0].get("date", ""),
        )
    else:
        sorted_threads.sort(
            key=lambda t: len(t.get("messages") or []),
            reverse=True,
        )

    st.subheader(f"Threads ({len(sorted_threads)})")
    for thread in sorted_threads:
        render_thread_card(thread)


# -----------------------------------------------------------------------------
# Phase dispatch
# -----------------------------------------------------------------------------
def render_phase(phase: str) -> None:
    if phase == "Inbox & Triage":
        render_inbox_phase()
    elif phase == "Draft Generation":
        st.header("📝 Draft Generation")
        st.info("Coming up next – will draft replies for triaged threads.")
    elif phase == "Approval Gate":
        st.header("✅ Approval Gate")
        st.info("Coming up next – review and approve drafts before send.")
    elif phase == "Export Proof":
        st.header("📄 Export Proof")
        st.info("Coming up next – export approved drafts as proof of work.")
    else:
        st.warning(f"Unknown phase: {phase}")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main() -> None:
    render_sidebar()
    render_phase(st.session_state.current_phase)


if __name__ == "__main__":
    main()