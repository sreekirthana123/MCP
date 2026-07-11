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
from datetime import datetime
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

PRIORITY_CONFIG = {
    "urgent":      {"emoji": "🔴", "label": "Urgent"},
    "needs-reply": {"emoji": "⚪", "label": "Needs Reply"},
    "fyi":         {"emoji": "🟢", "label": "FYI"},
    "ignore":      {"emoji": "⚫", "label": "Ignore"},
}

# -----------------------------------------------------------------------------
# Local imports
# -----------------------------------------------------------------------------
import sys
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "Gmail-MCP-Server"))
from triage import triage_inbox
from draft_machine import draft_reply, draft_reply_with_metadata
from engine import send_reply


# -----------------------------------------------------------------------------
# Lazy imports for calendar engine
# -----------------------------------------------------------------------------
@st.cache_resource
def get_calendar_engine():
    """Lazy import calendar_engine functions to avoid loading them eagerly.

    Returns
    -------
    tuple of (parse_meeting_request, find_free_slot, create_event)
    """
    import importlib
    mod = importlib.import_module("calendar_engine")
    return (mod.parse_meeting_request, mod.find_free_slot, mod.create_event)


# -----------------------------------------------------------------------------
# Session state initialization
# -----------------------------------------------------------------------------
def _init_session_state() -> None:
    defaults: dict[str, Any] = {
        "threads": [],
        "triaged": {},       # subject -> full triage result dict
        "drafts": {},        # thread_id -> {draft, metadata, thread}
        "approved": {},
        "rejected": [],
        "sent": [],
        "booked": {},
        "current_phase": "Inbox & Triage",
        "source": "Sample threads",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

_init_session_state()


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def load_sample_threads() -> list[dict[str, Any]]:
    if not SAMPLE_THREADS_PATH.exists():
        return []
    try:
        with SAMPLE_THREADS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def fetch_gmail_threads() -> list[dict[str, Any]]:
    """Fetch threads from Gmail via engine.py and normalize to our format."""
    from engine import fetch_threads, DEFAULT_MAX_RESULTS
    # Now it will use the default defined in engine.py
    raw = fetch_threads(max_results=DEFAULT_MAX_RESULTS)
    if not isinstance(raw, list):
        return []
    normalized = []
    for i, t in enumerate(raw):
        normalized.append({
            "id": t.get("thread_id", f"gmail_{i}"),
            "subject": t.get("subject", "(no subject)"),
            "messages": [
                {
                    "from": t.get("sender", ""),
                    "date": t.get("date", ""),
                    "body": t.get("body", "") or t.get("snippet", ""),
                }
            ],
        })
    return normalized


def get_triage_result(thread: dict[str, Any]) -> dict[str, Any]:
    """Return full triage result for a thread."""
    return st.session_state.triaged.get(thread.get("subject", ""), {})


def get_actionable_threads() -> list[dict[str, Any]]:
    """Return threads classified as urgent or needs-reply."""
    actionable = []
    for thread in st.session_state.threads:
        result = get_triage_result(thread)
        priority = result.get("priority", "")
        if priority in ("urgent", "needs-reply"):
            actionable.append(thread)
    return actionable


def render_thread_expander(thread: dict[str, Any], triage_result: dict) -> None:
    """Render a thread inside an st.expander with full message history."""
    subject = thread.get("subject", "(no subject)")
    messages = thread.get("messages", []) or []
    priority = triage_result.get("priority", "unknown")
    reason = triage_result.get("reason", "")

    cfg = PRIORITY_CONFIG.get(priority, {"emoji": "❓", "label": priority})
    label = f"{cfg['emoji']} {subject}"

    with st.expander(label, expanded=False):
        if reason:
            st.caption(f"**Reason:** {reason}")
        st.divider()
        for i, msg in enumerate(messages, start=1):
            st.markdown(
                f"**{msg.get('from', 'Unknown')}** · {msg.get('date', '')}"
            )
            st.write(msg.get("body", ""))
            if i < len(messages):
                st.divider()


# -----------------------------------------------------------------------------
# Export helpers
# -----------------------------------------------------------------------------
def generate_proof_markdown() -> str:
    """Generate a markdown proof document with all approved drafts."""
    lines = []
    lines.append("# Draft Desk — Proof of Work")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append(f"**Total approved:** {len(st.session_state.approved)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for thread_id, approved_data in st.session_state.approved.items():
        thread = approved_data.get("thread", {})
        subject = thread.get("subject", "(no subject)")
        messages = thread.get("messages", []) or []
        draft_text = approved_data.get("draft", "")

        lines.append(f"## {subject}")
        lines.append("")
        lines.append("### Original Thread")
        for msg in messages:
            sender = msg.get("from", "Unknown")
            date = msg.get("date", "")
            body = msg.get("body", "").strip()
            lines.append(f"> **From:** {sender} · {date}")
            lines.append(">")
            for line in body.split("\n"):
                lines.append(f"> {line}")
            lines.append("")
        lines.append("### Draft Reply")
        lines.append("")
        lines.append("```")
        lines.append(draft_text)
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("")
    lines.append(
        "_Share with **#MyAIChiefOfStaff** to earn your Ghostwriter badge!_"
    )
    return "\n".join(lines)


def generate_proof_html() -> str:
    """Generate a styled HTML proof document with all approved drafts."""
    approved = st.session_state.approved
    items_html = ""

    for thread_id, approved_data in approved.items():
        thread = approved_data.get("thread", {})
        subject = thread.get("subject", "(no subject)")
        messages = thread.get("messages", []) or []
        draft_text = approved_data.get("draft", "")

        # Build original messages HTML
        msgs_html = ""
        for msg in messages:
            sender = msg.get("from", "Unknown")
            date = msg.get("date", "")
            body = msg.get("body", "").strip().replace("\n", "<br>")
            msgs_html += f"""
            <div class="message">
                <div class="msg-header">{sender} · {date}</div>
                <div class="msg-body">{body}</div>
            </div>
            """

        items_html += f"""
        <div class="thread-card">
            <h2>{subject}</h2>
            <div class="grid">
                <div class="original">
                    <div class="label label-orange">📨 Original Thread</div>
                    {msgs_html}
                </div>
                <div class="draft-col">
                    <div class="label label-green">🤖 Draft Reply</div>
                    <pre>{draft_text}</pre>
                </div>
            </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Draft Desk — Proof of Work</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: #0e1117;
            color: #fafafa;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            padding: 40px;
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{
            font-size: 2rem;
            margin-bottom: 8px;
        }}
        .subtitle {{
            color: #888;
            margin-bottom: 32px;
        }}
        .thread-card {{
            background: #1a1b26;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
        }}
        .thread-card h2 {{
            margin-bottom: 16px;
            font-size: 1.25rem;
            color: #e0e0e0;
        }}
        .grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }}
        .original {{
            background: #262730;
            border-radius: 8px;
            padding: 16px;
            border-left: 4px solid #ff9800;
        }}
        .draft-col {{
            background: #262730;
            border-radius: 8px;
            padding: 16px;
            border-left: 4px solid #4caf50;
        }}
        .label {{
            font-weight: 600;
            margin-bottom: 12px;
            font-size: 0.9rem;
        }}
        .label-orange {{ color: #ff9800; }}
        .label-green {{ color: #4caf50; }}
        .message {{
            margin-bottom: 12px;
            padding-bottom: 12px;
            border-bottom: 1px solid #333;
        }}
        .message:last-child {{ border-bottom: none; }}
        .msg-header {{
            color: #4a9eff;
            font-size: 0.85rem;
            margin-bottom: 4px;
        }}
        .msg-body {{
            font-size: 0.9rem;
            line-height: 1.5;
            color: #d0d0d0;
        }}
        pre {{
            white-space: pre-wrap;
            font-size: 0.9rem;
            line-height: 1.5;
            color: #d0d0d0;
            font-family: 'Consolas', 'Courier New', monospace;
        }}
        .badge {{
            margin-top: 32px;
            text-align: center;
            padding: 16px;
            background: linear-gradient(135deg, #1a1b26, #262730);
            border-radius: 8px;
            color: #ffd700;
            font-style: italic;
        }}
        @media (max-width: 768px) {{
            .grid {{ grid-template-columns: 1fr; }}
            body {{ padding: 20px; }}
        }}
    </style>
</head>
<body>
    <h1>✍️ Draft Desk — Proof of Work</h1>
    <div class="subtitle">
        Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} &nbsp;|&nbsp;
        Approved: {len(approved)}
    </div>
    {items_html}
    <div class="badge">
        Share with <strong>#MyAIChiefOfStaff</strong> to earn your Ghostwriter badge!
    </div>
</body>
</html>"""
    return html


# -----------------------------------------------------------------------------
# Sidebar
# -----------------------------------------------------------------------------
def render_sidebar() -> None:
    with st.sidebar:
        st.title("✍️ The Draft Desk")
        triaged_count = len(st.session_state.triaged)
        needs_reply_count = sum(
            1 for v in st.session_state.triaged.values()
            if isinstance(v, dict) and v.get("priority") == "needs-reply"
        )
        st.caption(
            f"Loaded: **{len(st.session_state.threads)}** thread(s)\n"
            f"Triaged: **{triaged_count}**\n"
            f"Needs reply: **{needs_reply_count}**\n"
            f"Drafts: **{len(st.session_state.drafts)}**\n"
            f"Approved: **{len(st.session_state.approved)}**\n"
            f"Rejected: **{len(st.session_state.rejected)}**"
        )
        st.divider()

        st.subheader("Source")
        st.session_state.source = st.radio(
            "source_radio",
            options=["Sample threads", "Gmail via engine.py"],
            index=0 if st.session_state.source == "Sample threads" else 1,
            label_visibility="collapsed",
            key="source_radio",
        )

        st.divider()
        st.subheader("Navigation")

        for phase in PHASES:
            is_current = st.session_state.current_phase == phase
            label = f"▶️ {phase}" if is_current else phase
            if st.button(label, key=f"nav_{phase}", use_container_width=True):
                st.session_state.current_phase = phase
                st.rerun()

        st.divider()


# -----------------------------------------------------------------------------
# Phase 1: Inbox & Triage
# -----------------------------------------------------------------------------
def render_inbox_phase() -> None:
    st.header("📥 Inbox & Triage")
    st.write(
        "Pull threads from the selected source, then triage them by priority. "
        "Once triaged, the highest-priority threads move to *Draft Generation*."
    )

    col1, col2, _ = st.columns([1, 1, 4])
    with col1:
        pull_clicked = st.button("Pull & Triage", type="primary", use_container_width=True)
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
        with st.spinner("Loading threads..."):
            if source == "Sample threads":
                loaded = load_sample_threads()
                if not loaded:
                    st.error(f"No threads found at `{SAMPLE_THREADS_PATH.name}`.")
                    return
            else:
                loaded = fetch_gmail_threads()
                if not loaded:
                    st.warning("No Gmail threads returned. Check credentials.")
                    return

        st.session_state.threads = loaded
        st.session_state.triaged = {}

        triage_input = [
            {
                "sender": (t.get("messages") or [{}])[0].get("from", ""),
                "subject": t.get("subject", ""),
                "snippet": (t.get("messages") or [{}])[0].get("body", "")[:150],
            }
            for t in loaded
        ]

        with st.spinner("Triaging threads with AI..."):
            triaged_results = triage_inbox(triage_input)

        for r in triaged_results:
            subject = r.get("subject", "")
            st.session_state.triaged[subject] = r

        needs_reply = sum(
            1 for r in triaged_results if r.get("priority") == "needs-reply"
        )
        st.success(
            f"Loaded and triaged {len(loaded)} thread(s) — "
            f"{needs_reply} need a reply."
        )
        st.rerun()

    st.divider()

    threads = st.session_state.threads
    if not threads:
        st.info("No threads loaded yet. Click **Pull & Triage** to get started.")
        return

    groups: dict[str, list] = {p: [] for p in PRIORITY_CONFIG}
    for thread in threads:
        result = get_triage_result(thread)
        priority = result.get("priority", "ignore")
        if priority not in groups:
            priority = "ignore"
        groups[priority].append((thread, result))

    for priority, cfg in PRIORITY_CONFIG.items():
        items = groups[priority]
        if not items:
            continue
        st.subheader(f"{cfg['emoji']} {cfg['label']} ({len(items)})")
        for thread, triage_result in items:
            render_thread_expander(thread, triage_result)
        st.divider()

    needs_reply_threads = groups.get("needs-reply", [])
    urgent_threads = groups.get("urgent", [])
    actionable_count = len(needs_reply_threads) + len(urgent_threads)

    if actionable_count > 0:
        st.info(f"{actionable_count} thread(s) need a reply → go to **Draft Generation**")
    
    if st.session_state.threads:
        if st.button("Go to Draft Generation →", type="primary"):
            st.session_state.current_phase = "Draft Generation"
            st.rerun()


# -----------------------------------------------------------------------------
# Phase 2: Draft Generation
# -----------------------------------------------------------------------------
def render_draft_generation_phase() -> None:
    st.header("📝 Draft Generation")

    actionable = get_actionable_threads()

    if not actionable:
        st.warning("No actionable threads found. Go to **Inbox & Triage** first and pull threads.")
        return

    already_drafted = len(st.session_state.drafts)
    st.write(
        f"**{len(actionable)} actionable thread(s)** (urgent + needs-reply) ready for drafting. "
        f"{already_drafted} draft(s) already generated."
    )

    # ── Generate All Drafts button ────────────────────────────────────────────
    if st.button("✨ Generate All Drafts", type="primary"):
        progress_bar = st.progress(0, text="Starting draft generation...")
        total = len(actionable)

        for i, thread in enumerate(actionable):
            thread_id = thread.get("id", thread.get("subject", f"thread_{i}"))
            subject = thread.get("subject", "(no subject)")

            progress_bar.progress(
                (i) / total,
                text=f"Drafting {i + 1}/{total}: {subject[:50]}..."
            )

            try:
                result = draft_reply_with_metadata(thread)
                st.session_state.drafts[thread_id] = {
                    "draft": result["draft"],
                    "model": result.get("model", ""),
                    "reply_to": result.get("reply_to", ""),
                    "char_count": result.get("char_count", 0),
                    "thread": thread,
                }
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                    st.warning(f"⏳ Quota reached on thread '{subject}'. Resets at 12:30 PM IST.")
                else:
                    st.error(f"Failed to draft '{subject}': {e}")
                st.session_state.drafts[thread_id] = {
                    "draft": "⏳ Quota reached — draft will generate when quota resets at 12:30 PM IST.",
                    "model": "",
                    "reply_to": "",
                    "char_count": 0,
                    "thread": thread,
                }

        progress_bar.progress(1.0, text="All drafts generated!")
        st.rerun()

    st.divider()

    # ── Display drafts ────────────────────────────────────────────────────────
    if not st.session_state.drafts:
        st.info("Click **Generate All Drafts** to create AI replies for all actionable threads.")
        return

    for thread_id, draft_data in st.session_state.drafts.items():
        thread = draft_data.get("thread", {})
        subject = thread.get("subject", "(no subject)")
        messages = thread.get("messages", []) or []
        latest_msg = messages[-1] if messages else {}

        with st.expander(f"📧 {subject}", expanded=True):
            col_left, col_right = st.columns([1, 1], gap="large")

            # Left: original thread latest message
            with col_left:
                st.markdown("**📨 Original Thread**")
                st.caption(
                    f"From: {latest_msg.get('from', 'Unknown')} · "
                    f"{latest_msg.get('date', '')}"
                )
                st.text_area(
                    "Thread content",
                    value=(latest_msg.get("body") or "").strip(),
                    height=250,
                    disabled=True,
                    label_visibility="collapsed",
                    key=f"thread_{thread_id}",
                )

            # Right: AI draft
            with col_right:
                st.markdown("**🤖 AI Draft Reply**")
                meta = draft_data
                st.caption(
                    f"Model: {meta.get('model', 'gemini-2.5-flash')} · "
                    f"To: {meta.get('reply_to', '')} · "
                    f"Chars: {meta.get('char_count', 0)}"
                )
                st.text_area(
                    "Draft content",
                    value=draft_data.get("draft", ""),
                    height=250,
                    disabled=True,
                    label_visibility="collapsed",
                    key=f"draft_{thread_id}",
                )

    st.divider()

    # ── Bottom CTA ────────────────────────────────────────────────────────────
    if st.session_state.drafts:
        st.success(f"✅ {len(st.session_state.drafts)} draft(s) ready → go to **Approval Gate**")
        if st.button("Go to Approval Gate →", type="primary"):
            st.session_state.current_phase = "Approval Gate"
            st.rerun()


# -----------------------------------------------------------------------------
# Approval Gate CSS (matching instructor's approval_gate.py)
# -----------------------------------------------------------------------------
def _apply_approval_gate_css() -> None:
    st.markdown(
        """
        <style>
        .thread-box {
            background-color: #262730;
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 15px;
            border-left: 4px solid #4a9eff;
        }
        
        .draft-box {
            background-color: #1a1b26;
            border-radius: 10px;
            padding: 20px;
            border-left: 4px solid #4caf50;
            margin-bottom: 15px;
        }
        
        .status-approved {
            background-color: #1b4d34;
            border-radius: 5px;
            padding: 10px;
            color: #4caf50;
            font-weight: bold;
            text-align: center;
        }
        
        .status-rejected {
            background-color: #4d1b1b;
            border-radius: 5px;
            padding: 10px;
            color: #f44336;
            font-weight: bold;
            text-align: center;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------
# Phase 3: Approval Gate
# -----------------------------------------------------------------------------
def render_thread_html(thread: dict[str, Any]) -> str:
    """Return thread as HTML string with proper line breaks."""
    lines = []
    if "subject" in thread:
        lines.append(f"<p><strong>Subject:</strong> {thread['subject']}</p>")
    for msg in thread.get("messages", []):
        sender = msg.get("from", "unknown sender")
        date = msg.get("date", "unknown date")
        body = msg.get("body", "").strip().replace("\n", "<br>")
        lines.append(f"<p><strong>From:</strong> {sender}</p>")
        lines.append(f"<p><strong>Date:</strong> {date}</p>")
        lines.append(f"<p>{body}</p>")
    return "\n".join(lines)


def render_approval_gate_phase() -> None:
    _apply_approval_gate_css()
    st.header("✅ Approval Gate")
    st.write(
        "Review each AI-generated draft below. You can **Approve**, **Edit**, "
        "or **Reject** each draft. Only explicitly approved drafts move to Export."
    )

    if not st.session_state.drafts:
        st.warning("No drafts to review. Go to **Draft Generation** first and generate drafts.")
        return

    # Running counts
    approved_count = len(st.session_state.approved)
    rejected_count = len(st.session_state.rejected)
    total = len(st.session_state.drafts)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total drafts", total)
    col2.metric("✅ Approved", approved_count)
    col3.metric("❌ Rejected", rejected_count)
    col4.metric("⏳ Pending", total - approved_count - rejected_count)

    st.divider()

    all_reviewed = True
    for thread_id, draft_data in st.session_state.drafts.items():
        thread = draft_data.get("thread", {})
        subject = thread.get("subject", "(no subject)")
        messages = thread.get("messages", []) or []
        latest_msg = messages[-1] if messages else {}

        # Determine status for this draft
        if thread_id in st.session_state.approved:
            status = "approved"
        elif thread_id in st.session_state.rejected:
            status = "rejected"
        else:
            status = "pending"
            all_reviewed = False

        with st.container():
            st.subheader(f"📧 {subject}")

            # Show status indicator
            if status == "approved":
                st.markdown(
                    '<div class="status-approved">✅ Approved - Ready to Send</div>',
                    unsafe_allow_html=True,
                )
            elif status == "rejected":
                st.markdown(
                    '<div class="status-rejected">❌ Rejected - Discarded</div>',
                    unsafe_allow_html=True,
                )

            # Two-column layout (like instructor)
            col_left, col_right = st.columns([1, 1], gap="large")

            with col_left:
                st.subheader("Thread History")
                thread_html = render_thread_html(thread)
                st.markdown(
                    f'<div class="thread-box">{thread_html}</div>',
                    unsafe_allow_html=True,
                )

            with col_right:
                st.subheader("AI Generated Draft")

                # Show metadata line
                meta = draft_data
                st.caption(
                    f"Model: {meta.get('model', 'gemini-2.5-flash')} · "
                    f"To: {meta.get('reply_to', '')} · "
                    f"Chars: {meta.get('char_count', 0)}"
                )

                if status == "approved":
                    # Allow re-editing an approved draft
                    if st.session_state.get(f"editing_{thread_id}"):
                        st.divider()
                        st.subheader("Edit Draft")

                        edit_widget_key = f"edited_draft_area_{thread_id}"

                        # Seed from the currently-approved text (not the original quota placeholder)
                        if edit_widget_key not in st.session_state:
                            current_approved_text = st.session_state.approved[thread_id].get("draft", "")
                            # Clear quota placeholder so the user starts with a blank slate
                            if current_approved_text.startswith("⏳"):
                                current_approved_text = ""
                            st.session_state[edit_widget_key] = current_approved_text

                        st.text_area(
                            "Modify the draft:",
                            height=300,
                            key=edit_widget_key,
                        )

                        save_col, cancel_col = st.columns(2)
                        with save_col:
                            if st.button("✅ Save & Approve", type="primary",
                                         key=f"save_edit_approved_{thread_id}"):
                                st.session_state.approved[thread_id] = {
                                    "draft": st.session_state[edit_widget_key],
                                    "thread": thread,
                                    "metadata": draft_data,
                                }
                                st.session_state[f"editing_{thread_id}"] = False
                                del st.session_state[edit_widget_key]
                                st.rerun()
                        with cancel_col:
                            if st.button("✖ Cancel", key=f"cancel_edit_approved_{thread_id}"):
                                st.session_state[f"editing_{thread_id}"] = False
                                st.session_state.pop(edit_widget_key, None)
                                st.rerun()
                    else:
                        approved_text = st.session_state.approved[thread_id].get("draft", "")
                        st.markdown(
                            f'<div class="draft-box"><pre style="white-space: pre-wrap; margin: 0;">{approved_text}</pre></div>',
                            unsafe_allow_html=True,
                        )
                        edit_row, _ = st.columns([1, 3])
                        with edit_row:
                            if st.button("✏️ Edit", key=f"edit_approved_{thread_id}", use_container_width=True):
                                st.session_state[f"editing_{thread_id}"] = True
                                st.rerun()
                        st.success("✅ Approved & saved")

                    # Extract recipient email from thread's last message
                    messages = thread.get("messages", []) or []
                    latest_msg = messages[-1] if messages else {}
                    raw_from = latest_msg.get("from", "")
                    if "<" in raw_from:
                        recipient = raw_from.split("<")[1].strip(">")
                    else:
                        recipient = raw_from.strip()

                    subject = thread.get("subject", "")
                    approved_draft = st.session_state.approved[thread_id].get("draft", "")

                    # Check if already sent
                    is_sent = thread_id in st.session_state.sent
                    is_booked = thread_id in st.session_state.booked

                    # Check if this is a meeting request thread
                    triage_result = get_triage_result(thread)
                    category = triage_result.get("category", "")
                    _subject_lower = thread.get("subject", "").lower()
                    _body_lower = " ".join(
                        m.get("body", "") for m in thread.get("messages", [])
                    ).lower()
                    _meeting_kws = [
                        "meeting", "call", "sync", "slot", "schedule",
                        "30 min", "30-min", "would you be free", "free for a",
                        "calendar invite", "slots open", "book a", "are you free",
                        "time slot", "catch up", "zoom", "hop on", "quick chat",
                        "15 min", "walkthrough",
                    ]
                    is_meeting = (
                        category in ("meeting_request", "meeting-request")
                        or any(kw in _subject_lower for kw in _meeting_kws)
                        or any(kw in _body_lower for kw in _meeting_kws)
                    )

                    if is_meeting:
                        # Always show two columns: Send (or sent indicator) + Book Meeting
                        btn_col_a, btn_col_b = st.columns(2)

                        with btn_col_a:
                            if is_sent:
                                st.success("📤 Sent successfully")
                            else:
                                if st.button("📤 Send", key=f"send_btn_{thread_id}",
                                            use_container_width=True):
                                    try:
                                        send_reply(
                                            thread_id=thread_id,
                                            to=recipient,
                                            subject=subject,
                                            body=approved_draft,
                                        )
                                        st.session_state.sent.append(thread_id)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Send failed: {e}")

                        with btn_col_b:
                            if is_booked:
                                booked_data = st.session_state.booked[thread_id]
                                link = booked_data.get("htmlLink", "")
                                if link:
                                    st.markdown(f"[📅 View Calendar Event]({link})")
                                else:
                                    st.success("📅 Booked")
                            else:
                                if st.button("📅 Book Meeting", key=f"book_btn_{thread_id}",
                                            use_container_width=True):
                                    try:
                                        parse_req, find_slot, create_evt = get_calendar_engine()

                                        with st.spinner("Parsing meeting request..."):
                                            parsed = parse_req(thread)

                                        if "parsing_error" in parsed:
                                            parse_err = parsed['parsing_error']
                                            if "429" in str(parse_err) or "RESOURCE_EXHAUSTED" in str(parse_err):
                                                st.error("Your API limit has been reached.")
                                            elif "503" in str(parse_err) or "UNAVAILABLE" in str(parse_err):
                                                st.error("The AI service is temporarily unavailable. Please try again in a moment.")
                                            else:
                                                st.error("Unable to parse meeting details. Please try again.")
                                        else:
                                            st.info(
                                                f"**Topic:** {parsed.get('topic', '')}\n\n"
                                                f"**Proposed times:** {parsed.get('proposed_times', [])}\n\n"
                                                f"**Attendees:** {parsed.get('attendees', [])}\n\n"
                                                f"**Duration:** {parsed.get('duration_minutes', 30)} min"
                                            )

                                            proposed = parsed.get("proposed_times", [])
                                            duration = parsed.get("duration_minutes", 30)

                                            with st.spinner("Checking availability..."):
                                                free_slot = find_slot(proposed, duration)

                                            if free_slot:
                                                with st.spinner("Creating calendar event..."):
                                                    event = create_evt(
                                                        summary=parsed.get("topic", subject),
                                                        start_time=free_slot,
                                                        duration_minutes=duration,
                                                        attendees=parsed.get("attendees", []),
                                                        description=approved_draft,
                                                    )
                                                st.session_state.booked[thread_id] = event
                                                link = event.get("htmlLink", "")
                                                if link:
                                                    st.success(f"✅ Meeting booked! [📅 View Event]({link})")
                                                else:
                                                    st.success("✅ Meeting booked!")
                                                st.rerun()
                                            else:
                                                st.warning("No free slot found among proposed times.")
                                    except Exception as e:
                                        error_msg = str(e)
                                        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                                            st.error("Your API limit has been reached.")
                                        elif "503" in error_msg or "UNAVAILABLE" in error_msg:
                                            st.error("The AI service is temporarily unavailable. Please try again in a moment.")
                                        else:
                                            st.error("Something went wrong while booking the meeting. Please try again.")
                    else:
                        # Regular thread: just a Send button
                        if is_sent:
                            st.success("📤 Sent successfully")
                        else:
                            if st.button("📤 Send", key=f"send_btn_{thread_id}",
                                         use_container_width=True):
                                try:
                                    send_reply(
                                        thread_id=thread_id,
                                        to=recipient,
                                        subject=subject,
                                        body=approved_draft,
                                    )
                                    st.session_state.sent.append(thread_id)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Send failed: {e}")

                elif status == "rejected":
                    st.markdown(
                        f'<div class="draft-box"><pre style="white-space: pre-wrap; margin: 0;">{draft_data.get("draft", "")}</pre></div>',
                        unsafe_allow_html=True,
                    )
                    # Regenerate button for rejected drafts
                    if st.button("🔄 REGENERATE", key=f"regen_rejected_{thread_id}", use_container_width=True):
                        with st.spinner("Regenerating draft..."):
                            try:
                                result = draft_reply_with_metadata(thread)
                                st.session_state.drafts[thread_id] = {
                                    "draft": result["draft"],
                                    "model": result.get("model", ""),
                                    "reply_to": result.get("reply_to", ""),
                                    "char_count": result.get("char_count", 0),
                                    "thread": thread,
                                }
                            except Exception as e:
                                st.error(f"Regeneration failed: {e}")
                            st.rerun()

                else:
                    # Pending: show draft in a draft-box
                    st.markdown(
                        f'<div class="draft-box"><pre style="white-space: pre-wrap; margin: 0;">{draft_data.get("draft", "")}</pre></div>',
                        unsafe_allow_html=True,
                    )

                    # Three action buttons (like instructor)
                    st.divider()
                    btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1])

                    with btn_col1:
                        if st.button("✅ APPROVE", key=f"approve_btn_{thread_id}", use_container_width=True):
                            st.session_state.approved[thread_id] = {
                                "draft": draft_data.get("draft", ""),
                                "thread": thread,
                                "metadata": draft_data,
                            }
                            st.rerun()

                    with btn_col2:
                        if st.button("✏️ EDIT", key=f"edit_btn_{thread_id}", use_container_width=True):
                            st.session_state[f"editing_{thread_id}"] = True
                            st.rerun()

                    # Look for this section inside render_approval_gate_phase:

                    with btn_col3:
                        # REPLACE EVERYTHING BELOW THIS LINE inside the 'with' block
                        if st.button("🔄 REGENERATE", key=f"regen_pending_{thread_id}", use_container_width=True):
                            with st.spinner("Regenerating draft..."):
                                try:
                                    result = draft_reply_with_metadata(thread)
                                    st.session_state.drafts[thread_id] = {
                                        "draft": result["draft"],
                                        "model": result.get("model", ""),
                                        "reply_to": result.get("reply_to", ""),
                                        "char_count": result.get("char_count", 0),
                                        "thread": thread,
                                    }
                                    st.rerun() # Added rerun here to update the UI immediately
                                except Exception as e:
                                    # This logic now catches the quota error and shows a clear message
                                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                                        st.error("Quota exceeded! Please wait a minute before trying again.")
                                    else:
                                        st.error(f"Regeneration failed: {e}")

                    # Edit mode (like instructor)
                    if st.session_state.get(f"editing_{thread_id}"):
                        st.divider()
                        st.subheader("Edit Draft")

                        edit_widget_key = f"edited_draft_area_{thread_id}"

                        # Seed the widget state only on first entry into edit mode
                        if edit_widget_key not in st.session_state:
                            initial = draft_data.get("draft", "")
                            # Clear quota placeholder so the user starts fresh
                            if initial.startswith("⏳"):
                                initial = ""
                            st.session_state[edit_widget_key] = initial

                        st.text_area(
                            "Modify the draft:",
                            height=300,
                            key=edit_widget_key,
                        )

                        if st.button("✅ Approve Edited Version", type="primary",
                                     key=f"approve_edit_btn_{thread_id}"):
                            st.session_state.approved[thread_id] = {
                                "draft": st.session_state[edit_widget_key],
                                "thread": thread,
                                "metadata": draft_data,
                            }
                            st.session_state[f"editing_{thread_id}"] = False
                            del st.session_state[edit_widget_key]
                            st.rerun()

            st.divider()

    # When all drafts are reviewed
    if all_reviewed and total > 0:
        st.balloons()
        st.success("🎉 All drafts have been reviewed!")
        if st.button("Go to Export Proof →", type="primary"):
            st.session_state.current_phase = "Export Proof"
            st.rerun()


# -----------------------------------------------------------------------------
# Phase 4: Export Proof
# -----------------------------------------------------------------------------
def render_export_proof_phase() -> None:
    st.header("📄 Export Proof")

    if not st.session_state.approved:
        st.warning("No approved drafts to export. Go to **Approval Gate** first and approve some drafts.")
        return

    st.write(
        f"**{len(st.session_state.approved)}** approved draft(s) ready for export. "
        "Download your proof of work as Markdown or HTML."
    )

    st.divider()

    # Preview all approved drafts side-by-side
    st.subheader("Preview of Approved Drafts")
    for thread_id, approved_data in st.session_state.approved.items():
        thread = approved_data.get("thread", {})
        subject = thread.get("subject", "(no subject)")
        messages = thread.get("messages", []) or []
        draft_text = approved_data.get("draft", "")

        with st.expander(f"📧 {subject}", expanded=True):
            col_left, col_right = st.columns([1, 1], gap="large")
            with col_left:
                st.markdown("**📨 Original Thread**")
                for msg in messages:
                    st.caption(f"{msg.get('from', 'Unknown')} · {msg.get('date', '')}")
                    st.write(msg.get("body", ""))
                    st.divider()
            with col_right:
                st.markdown("**🤖 Approved Draft Reply**")
                st.text_area(
                    "draft_preview",
                    value=draft_text,
                    height=200,
                    disabled=True,
                    label_visibility="collapsed",
                    key=f"export_draft_{thread_id}",
                )

    st.divider()

    # Generate export content
    markdown_content = generate_proof_markdown()
    html_content = generate_proof_html()

    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        st.download_button(
            label="📥 Download Proof (Markdown)",
            data=markdown_content,
            file_name=f"draft_desk_proof_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with btn_col2:
        st.download_button(
            label="📥 Download Proof (HTML)",
            data=html_content,
            file_name=f"draft_desk_proof_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
            mime="text/html",
            use_container_width=True,
        )

    st.divider()
    st.info("📢 Share with **#MyAIChiefOfStaff** to earn your Ghostwriter badge!")


# -----------------------------------------------------------------------------
# Phase dispatch
# -----------------------------------------------------------------------------
def render_phase(phase: str) -> None:
    if phase == "Inbox & Triage":
        render_inbox_phase()
    elif phase == "Draft Generation":
        render_draft_generation_phase()
    elif phase == "Approval Gate":
        render_approval_gate_phase()
    elif phase == "Export Proof":
        render_export_proof_phase()
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