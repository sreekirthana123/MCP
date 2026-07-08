import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from context_builder import assemble_context

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL_NAME = "gemini-2.5-flash"
DRAFTING_RULES = """
DRAFTING RULES (HARD CONSTRAINTS - obey all of these):

1. ONE-ASK RULE
   Every reply contains exactly ONE clear question OR ONE clear request. Never stack multiple asks ("could you do X, Y, and also Z?"). If the incoming email has many open questions, pick the single most important one and acknowledge the rest briefly.

2. LENGTH CONTROL
   Match the energy of the incoming thread. Default to short: max 5 sentences total. Use a numbered list only if the reply genuinely needs to enumerate distinct items (e.g. 3 concrete deliverables). Otherwise, write prose.

3. NO AI FILLER
   Never open with or include any of these phrases (or close variants):
   - "I hope this finds you well"
   - "I hope you're doing well"
   - "Thank you for reaching out"
   - "Thank you for your email"
   - "Great question"
   - "Certainly!"
   - "I'd be happy to"
   Just start with the substance.

4. STRUCTURE
    Order the reply exactly like this:
    (a) greeting line: "Hi [Name],"
    (b) one-line warm acknowledgment that references the specific message
    (c) the response / substance
    (d) ONE clear next step or question
    No sign-off explanation. Just the email body, ready to send.
"""

# ---------------------------------------------------------------------------
# Environment / API key handling
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent

# Target the specific subdirectory where the .env file lives
load_dotenv(dotenv_path=_HERE / "Gmail-MCP-Server" / ".env")
load_dotenv(dotenv_path=_HERE / ".env")
load_dotenv()

def _get_api_key() -> str | None:
    """Return the GEMINI_API_KEY from the environment, or None if missing."""
    return os.getenv("GEMINI_API_KEY")

def _missing_api_key_message() -> str:
    """Return the helpful error message shown when the API key is missing."""
    return (
        "GEMINI_API_KEY is not set.\n"
        "Add it to a .env file in this directory, e.g.:\n"
        "  GEMINI_API_KEY=your_real_key_here\n"
        "or export it in your shell before running this script.\n"
        "Get a key at: https://google.com"
    )

# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------
def _extract_recipient_name(thread: dict[str, Any]) -> str:
    """Best-effort: return the display name of the most recent sender."""
    messages = thread.get("messages") or []
    if not messages:
        return "the sender"
    
    last_from = messages[-1].get("from", "") or ""
    # "Elena Park <elena.park@acme.com>" -> "Elena Park"
    name_part = last_from.split("<", 1)[0].strip().strip("'\"")
    if not name_part and "@" in last_from:
        name_part = last_from.split("@", 1)[0]
        
    return name_part or "the sender"

# ---------------------------------------------------------------------------
# Prompt assembly + post-processing
# ---------------------------------------------------------------------------
def _build_combined_prompts(thread: dict[str, Any]) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) with the drafting rules appended."""
    ctx = assemble_context(thread)
    system_prompt = ctx["system"].rstrip() + "\n\n" + DRAFTING_RULES
    user_prompt = ctx["user"]
    return system_prompt, user_prompt

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9]*\n|\n```$", re.MULTILINE)
_SUBJECT_LINE_RE = re.compile(r"^subject\s*:\s*.*$", re.IGNORECASE)

def _post_process(raw: str) -> str:
    """Clean up a model response into a send-ready draft.

    - Strips wrapping Markdown code fences if the model added them.
    - Removes a leading "Subject:" line if it slipped in.
    - Trims surrounding whitespace.
    """
    text = raw.strip()

    # Strip ``` blocks the model sometimes wraps replies in.
    if text.startswith("```") and text.endswith("```"):
        text = _FENCE_RE.sub("", text).strip()

    # Drop a leading "Subject: ..." line if present.
    text = _SUBJECT_LINE_RE.sub("", text, count=1).lstrip()

    return text.strip()

# ---------------------------------------------------------------------------
# Gemini client
# ---------------------------------------------------------------------------
def _build_model():
    """Construct a configured Gemini client.

    Raises
    ------
    RuntimeError
        If `google-genai` is not installed, or the API key is missing.
    """
    try:
        from google import genai
    except ImportError as e:
        raise RuntimeError(
            "The 'google-genai' package is not installed. "
            "Install it with: pip install google-genai"
        ) from e

    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError(_missing_api_key_message())

    return genai.Client(api_key=api_key)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def draft_reply(thread: dict[str, Any]) -> str:
    """Generate a draft reply for `thread` and return only the body text.

    Parameters
    ----------
    thread : dict
        Thread dict with `subject` and `messages` (as expected by
        `context_builder.assemble_context`).

    Returns
    -------
    str
        The draft email body, ready to send (no subject, no preamble).
    """
    from google import genai
    from google.genai import types

    system_prompt, user_prompt = _build_combined_prompts(thread)

    # Gemini's chat-style API: pass system as the first "user" turn with
    # an explicit "system:" prefix is awkward; instead, prepend the system
    # block to the user prompt with a clear delimiter. This works well in
    # practice and keeps the call single-turn (lower latency, no state).
    combined_user = (
        f"[SYSTEM INSTRUCTIONS]\n{system_prompt}\n[/SYSTEM INSTRUCTIONS]\n\n"
        f"{user_prompt}"
    )

    client = _build_model()
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=combined_user,
        config=types.GenerateContentConfig(
            temperature=0.7,
            top_p=0.9,
            max_output_tokens=1024,
        ),
    )
    return _post_process(response.text)

def draft_reply_with_metadata(thread: dict[str, Any]) -> dict[str, Any]:
    """Like `draft_reply` but also returns useful metadata.

    Returns
    -------
    dict with keys:
        'draft'           : str - the email body
        'model'           : str - model name used
        'thread_subject'  : str - the original thread subject
        'reply_to'        : str - display name of the person being replied to
        'char_count'      : int - length of the draft in characters
    """
    draft = draft_reply(thread)
    return {
        "draft": draft,
        "model": MODEL_NAME,
        "thread_subject": thread.get("subject", ""),
        "reply_to": _extract_recipient_name(thread),
        "char_count": len(draft),
    }

# ---------------------------------------------------------------------------
# Demo / CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Same sample thread used by context_builder.py's demo, so the two
    # modules are easy to compare end-to-end.
    sample_thread = {
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
    }

    if not _get_api_key():
        print(_missing_api_key_message(), file=sys.stderr)
        sys.exit(1)

    try:
        result = draft_reply_with_metadata(sample_thread)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    print("=" * 70)
    print("GEMINI DRAFT")
    print("=" * 70)
    print(f"Model:           {result['model']}")
    print(f"Thread subject:  {result['thread_subject']}")
    print(f"Replying to:     {result['reply_to']}")
    print(f"Char count:      {result['char_count']}")
    print("-" * 70)
    print(result["draft"])
    print("=" * 70)
