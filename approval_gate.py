"""
Human-in-the-Loop Approval Gate for AI Email Ghostwriter
A Streamlit app that shows draft email replies and lets users approve, edit, or reject them.
"""

from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

# Import from local modules
# Note: We render thread inline to control display format without modifying context_builder.py
from draft_machine import draft_reply, draft_reply_with_metadata


# ---------------------------------------------------------------------------
# Local Thread Display (returns HTML string)
# ---------------------------------------------------------------------------
def render_thread(thread: dict[str, Any]) -> str:
    """Return thread as HTML string with proper line breaks."""
    if "subject" not in thread or "messages" not in thread:
        return ""
    lines = []
    lines.append(f"<p><strong>Subject:</strong> {thread['subject']}</p>")
    for msg in thread["messages"]:
        sender = msg.get("from", "unknown sender")
        date = msg.get("date", "unknown date")
        body = msg.get("body", "").strip().replace("\n", "<br>")
        lines.append(f"<p><strong>From:</strong> {sender}</p>")
        lines.append(f"<p><strong>Date:</strong> {date}</p>")
        lines.append(f"<p>{body}</p>")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
APPROVED_DRAFTS_PATH = _HERE / "approved_drafts.json"

# Load environment variables
load_dotenv()

# ---------------------------------------------------------------------------
# Sample Threads
# ---------------------------------------------------------------------------
SAMPLE_THREADS: dict[str, dict[str, Any]] = {
    "Q3 Roadmap Review": {
        "subject": "Q3 Roadmap Review - need your input by Friday",
        "messages": [
            {
                "from": "Elena Park <elena.park@acme.com>",
                "date": "2026-06-12 10:42",
                "body": (
                    "Hi Rahul,\n\n"
                    "Hope your week's going well. I'm putting together the Q3 review "
                    "deck and would love a short paragraph from you on the Onboarding "
                    "rewrite. Specifically: status, biggest risk, and what you need "
                    "from leadership to land it.\n\n"
                    "Could you send something by EOD Friday? Even 4-5 lines is fine.\n\n"
                    "Thanks!\nElena"
                ),
            }
        ],
    },
    "Project Proposal Feedback": {
        "subject": "Re: Project Proposal — Agentic Workflow System",
        "messages": [
            {
                "from": "Meera <meera@company.com>",
                "date": "2026-06-11 14:30",
                "body": (
                    "Hi Kirthana,\n\n"
                    "I've put together a preliminary proposal for the Agentic Workflow System "
                    "we discussed. The core loop design and tool integration points are mapped out.\n\n"
                    "Could you take a look and share your thoughts on the technical feasibility? "
                    "Especially interested in your take on the memory management approach.\n\n"
                    "Thanks!\nMeera"
                ),
            },
            {
                "from": "Kirthana <kirthana@company.com>",
                "date": "2026-06-11 16:00",
                "body": "Hi Meera,\n\nThis looks like a strong foundation. I've reviewed the architecture and have some suggestions...\n\nBest,\nKirthana",
            }
        ],
    },
    "Dataset Collaboration": {
        "subject": "Model Selection for Classification Pipeline",
        "messages": [
            {
                "from": "Aditya <aditya@company.com>",
                "date": "2026-06-10 09:15",
                "body": (
                    "Hi Kirthana,\n\n"
                    "I've finished preprocessing the customer churn dataset. Here's what I did:\n"
                    "- Handled missing values with median imputation\n"
                    "- Applied SMOTE for class imbalance\n"
                    "- Scaled features using StandardScaler\n\n"
                    "For the classification model, I'm deciding between Random Forest and XGBoost. "
                    "What's your recommendation given the interpretability requirements?\n\n"
                    "Thanks!\nAditya"
                ),
            }
        ],
    },
}

# ---------------------------------------------------------------------------
# Session State Initialization
# ---------------------------------------------------------------------------
def init_session_state() -> None:
    """Initialize Streamlit session state variables."""
    if "current_draft" not in st.session_state:
        st.session_state.current_draft = ""
    if "draft_status" not in st.session_state:
        st.session_state.draft_status = "none"  # none, approved, editing, rejected
    if "selected_thread" not in st.session_state:
        st.session_state.selected_thread = "Q3 Roadmap Review"
    if "custom_thread_json" not in st.session_state:
        st.session_state.custom_thread_json = ""
    if "generation_count" not in st.session_state:
        st.session_state.generation_count = 0
    if "edited_draft" not in st.session_state:
        st.session_state.edited_draft = ""
    if "draft_metadata" not in st.session_state:
        st.session_state.draft_metadata = {}
    if "show_reset_msg" not in st.session_state:
        st.session_state.show_reset_msg = False


# ---------------------------------------------------------------------------
# API Key Handling
# ---------------------------------------------------------------------------
def get_api_key() -> str | None:
    """Get GEMINI_API_KEY from environment or session state."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        api_key = st.session_state.get("manual_api_key", "")
    return api_key


# ---------------------------------------------------------------------------
# Approved Drafts Management
# ---------------------------------------------------------------------------
def load_approved_drafts() -> list[dict[str, Any]]:
    """Load existing approved drafts from JSON file."""
    try:
        with open(APPROVED_DRAFTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_approved_draft(draft: str, thread_subject: str, metadata: dict[str, Any]) -> None:
    """Save an approved draft to the JSON file with timestamp."""
    approved_drafts = load_approved_drafts()
    new_entry = {
        "id": len(approved_drafts) + 1,
        "timestamp": datetime.now().isoformat(),
        "draft": draft,
        "thread_subject": thread_subject,
        "char_count": len(draft),
        "model": metadata.get("model", ""),
    }
    approved_drafts.append(new_entry)
    with open(APPROVED_DRAFTS_PATH, "w", encoding="utf-8") as f:
        json.dump(approved_drafts, f, indent=2)


# ---------------------------------------------------------------------------
# Custom CSS Styling
# ---------------------------------------------------------------------------
def apply_custom_styling() -> None:
    """Apply dark theme custom CSS styling."""
    st.markdown(
        """
        <style>
        .stApp {
            background-color: #0e1117;
            color: #fafafa;
        }
        
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
        
        .message-header {
            color: #4a9eff;
            font-weight: 600;
            margin-bottom: 5px;
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
        
        .status-editing {
            background-color: #4d421b;
            border-radius: 5px;
            padding: 10px;
            color: #ff9800;
            font-weight: bold;
            text-align: center;
        }
        
        /* Fix button text visibility */
        .stButton > button {
            color: #ffffff !important;
            font-weight: 600 !important;
        }
        
        .stButton > button:hover {
            color: #ffffff !important;
        }
        
        .stButton > button:active {
            color: #ffffff !important;
        }
        
        .stButton > button:disabled {
            color: #666666 !important;
        }
        
        /* Fix text area text color */
        .stTextArea textarea {
            color: #ffffff !important;
            background-color: #1a1b26 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------
def main() -> None:
    """Main Streamlit application."""
    st.set_page_config(
        page_title="Email Approval Gate",
        page_icon="📧",
        layout="wide",
    )
    init_session_state()
    apply_custom_styling()
    
    st.title("📧 Human-in-the-Loop Email Approval Gate")
    st.markdown("Review the AI-generated draft below, then APPROVE, EDIT, or REJECT it. Nothing is sent without your explicit approval.")
    
    # -----------------------------------------------------------------------
    # Sidebar: Thread Selection & API Key
    # -----------------------------------------------------------------------
    with st.sidebar:
        st.header("Configuration")
        
        # API Key handling
        api_key = get_api_key()
        if not api_key:
            st.write("API key required")
            manual_key = st.text_input(
                "GEMINI_API_KEY",
                type="password",
                key="manual_api_key_input",
            )
            if manual_key:
                st.session_state.manual_api_key = manual_key
        else:
            st.write("API key loaded")
        
        st.divider()
        
        # Thread selection dropdown
        st.subheader("Thread Selection")
        selected = st.selectbox(
            "Choose a thread:",
            options=list(SAMPLE_THREADS.keys()),
            index=list(SAMPLE_THREADS.keys()).index(st.session_state.selected_thread)
            if st.session_state.selected_thread in SAMPLE_THREADS
            else 0,
            key="selected_thread",
        )
        
        # Custom thread checkbox and JSON input
        use_custom = st.checkbox("Use custom thread", key="use_custom_thread")
        if use_custom:
            custom_json = st.text_area(
                "Thread JSON",
                height=200,
                key="custom_thread_json",
                help='Format: {"subject": "...", "messages": [{"from": "...", "date": "...", "body": "..."}]}',
            )
        
        # Generate Draft button
        generate_clicked = st.button(
            "Generate Draft",
            type="primary",
            use_container_width=True,
        )
        
        # Session stats section
        st.divider()
        st.subheader("Session stats")
        st.caption(f"Drafts generated: {st.session_state.generation_count}")
        st.caption(f"Current status: {st.session_state.draft_status}")
        
        # Reset session button
        st.divider()
        if st.button("🔄 Reset session", use_container_width=True):
            st.session_state.current_draft = ""
            st.session_state.draft_status = "none"
            st.session_state.edited_draft = ""
            st.session_state.draft_metadata = {}
            st.session_state.generation_count = 0
            st.session_state.show_reset_msg = True
            st.rerun()
        
        if st.session_state.get("show_reset_msg"):
            st.success("Session reset.")
            st.session_state.show_reset_msg = False
    
    # -----------------------------------------------------------------------
    # Get the current thread
    # -----------------------------------------------------------------------
    current_thread: dict[str, Any] | None = None
    
    if st.session_state.get("use_custom_thread"):
        if st.session_state.custom_thread_json:
            try:
                current_thread = json.loads(st.session_state.custom_thread_json)
            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON in custom thread: {e}")
    else:
        current_thread = SAMPLE_THREADS.get(st.session_state.selected_thread)
    
    # -----------------------------------------------------------------------
    # Generate draft on button click
    # -----------------------------------------------------------------------
    if generate_clicked and current_thread:
        if not get_api_key():
            st.error("Please provide a GEMINI_API_KEY to generate drafts.")
        else:
            with st.spinner("Generating draft..."):
                try:
                    result = draft_reply_with_metadata(current_thread)
                    st.session_state.current_draft = result["draft"]
                    st.session_state.draft_metadata = {
                        "model": result.get("model", ""),
                        "reply_to": result.get("reply_to", ""),
                        "char_count": result.get("char_count", 0),
                    }
                    st.session_state.draft_status = "none"
                    st.session_state.edited_draft = result["draft"]
                    st.session_state.generation_count += 1
                except Exception as e:
                    error_msg = str(e)
                    if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                        st.warning("⏳ Gemini quota reached. Resets at midnight Pacific / 12:30 PM IST. Try again tomorrow.")
                    else:
                        st.error(f"Draft generation failed: {e}")
    
    # -----------------------------------------------------------------------
    # Two-column layout
    # -----------------------------------------------------------------------
    col1, col2 = st.columns([1, 1], gap="large")
    
    with col1:
        st.subheader("Thread History")
        if current_thread:
            thread_html = render_thread(current_thread)
            st.markdown(
                f'<div class="thread-box">{thread_html}</div>',
                unsafe_allow_html=True
            )
        else:
            st.info("No thread loaded")
    
    with col2:
        st.subheader("AI Generated Draft")
        
        # Show status indicator
        if st.session_state.draft_status == "approved":
            st.markdown(
                '<div class="status-approved">✅ Approved - Ready to Send</div>',
                unsafe_allow_html=True,
            )
        elif st.session_state.draft_status == "editing":
            st.markdown(
                '<div class="status-editing">✏️ Editing Mode</div>',
                unsafe_allow_html=True,
            )
        elif st.session_state.draft_status == "rejected":
            st.markdown(
                '<div class="status-rejected">❌ Rejected - Discarded</div>',
                unsafe_allow_html=True,
            )
        
        # Show metadata line above draft
        if st.session_state.current_draft:
            meta = st.session_state.draft_metadata
            st.caption(f"Model: {meta.get('model', 'gemini-2.5-flash')} · To: {meta.get('reply_to', '')} · Chars: {meta.get('char_count', 0)}")
            st.markdown(
                f'<div class="draft-box"><pre style="white-space: pre-wrap; margin: 0;">{st.session_state.current_draft}</pre></div>',
                unsafe_allow_html=True,
            )
        else:
            st.info("Click 'Generate Draft' to create an AI reply")
    
    # -----------------------------------------------------------------------
    # Approved success message
    # -----------------------------------------------------------------------
    if st.session_state.draft_status == "approved" and st.session_state.current_draft:
        st.success("✅ Approved & saved to approved_drafts.json")
    
    # -----------------------------------------------------------------------
    # Action Buttons (below draft)
    # -----------------------------------------------------------------------
    if st.session_state.current_draft:
        st.divider()
        
        # Create columns for action buttons
        btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1])
        
        with btn_col1:
            if st.button(
                "✅ APPROVE",
                use_container_width=True,
                disabled=st.session_state.draft_status in ("approved", "editing"),
            ):
                if current_thread:
                    result = {
                        "model": "gemini-2.5-flash",
                        "thread_subject": current_thread.get("subject", ""),
                    }
                    save_approved_draft(
                        st.session_state.current_draft,
                        current_thread.get("subject", ""),
                        result,
                    )
                    st.session_state.draft_status = "approved"
                    st.rerun()
        
        with btn_col2:
            if st.button(
                "✏️ EDIT",
                use_container_width=True,
                disabled=st.session_state.draft_status == "approved",
            ):
                st.session_state.draft_status = "editing"
                st.rerun()
        
        with btn_col3:
            if st.button(
                "❌ REJECT",
                use_container_width=True,
                disabled=st.session_state.draft_status == "editing",
            ):
                st.session_state.draft_status = "rejected"
                st.rerun()
        
        # -------------------------------------------------------------------
        # Edit Mode: Show text area for editing
        # -------------------------------------------------------------------
        if st.session_state.draft_status == "editing":
            st.subheader("Edit Draft")
            edited_text = st.text_area(
                "Modify the draft:",
                value=st.session_state.current_draft,
                height=300,
                key="edited_draft_area",
            )
            st.session_state.edited_draft = edited_text
            
            # Approve edited version
            if st.button("✅ Approve Edited Version", type="primary"):
                if current_thread:
                    result = {
                        "model": "gemini-2.5-flash",
                        "thread_subject": current_thread.get("subject", ""),
                    }
                    save_approved_draft(
                        st.session_state.edited_draft,
                        current_thread.get("subject", ""),
                        result,
                    )
                    st.session_state.current_draft = st.session_state.edited_draft
                    st.session_state.draft_status = "approved"
                    st.rerun()
        
        # -------------------------------------------------------------------
        # Rejected status: Prompt to regenerate
        # -------------------------------------------------------------------
        if st.session_state.draft_status == "rejected":
            st.info("🔄 Click 'Generate Draft' to create a new version")
    
    # -----------------------------------------------------------------------
    # How this gate works (expandable section)
    # -----------------------------------------------------------------------
    with st.expander("How this gate works"):
        st.markdown("#### The safety contract")
        st.markdown("1. The AI (`draft_machine.py` + Gemini) generates a draft reply.")
        st.markdown("2. **Nothing is ever sent automatically.** You must explicitly click `APPROVE`.")
        st.markdown("3. You can `EDIT` the draft first - your edited version (not the AI's) is what gets saved.")
        st.markdown("4. You can `REJECT` a draft and ask for a new one - rejected drafts are discarded (not saved).")
        st.markdown("5. `APPROVE` writes the draft to `approved_drafts.json` with a timestamp.")
        
        st.markdown("#### Session state")
        st.markdown("- `current_draft` - the text on screen")
        st.markdown("- `draft_meta` - model / recipient / length metadata")
        st.markdown("- `status` - none | approved | editing | rejected")
        st.markdown("- `generation_count` - how many drafts this session has produced")
        st.markdown("- `edit_buffer` - working text inside the EDIT text area")
        
        st.markdown("#### Run")
        st.code("streamlit run approval_gate.py")
    
    # -----------------------------------------------------------------------
    # Approved Drafts History (expandable section)
    # -----------------------------------------------------------------------
    with st.expander("Approved Drafts History"):
        approved = load_approved_drafts()
        if approved:
            for entry in reversed(approved[-10:]):  # Show last 10
                with st.container():
                    st.caption(f"**{entry['thread_subject']}** - {entry['timestamp']}")
                    st.markdown(
                        f'<div class="draft-box" style="font-size: 0.9em;"><pre style="white-space: pre-wrap; margin: 0;">{entry["draft"]}</pre></div>',
                        unsafe_allow_html=True,
                    )
                    st.divider()
        else:
            st.info("No approved drafts yet")


if __name__ == "__main__":
    main()