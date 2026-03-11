"""
Shared ADK tools that read/write OAS content via session state.

Passing the OAS spec through session state (not message text) avoids
ADK's template substitution which breaks on path params like {id}.
"""
import json
from google.adk.tools.tool_context import ToolContext

# ── Session state keys ────────────────────────────────────────────
SPEC_KEY         = "current_spec"
POSTMAN_KEY      = "postman_json"
HAS_POSTMAN_KEY  = "has_postman"
SUGGESTIONS_KEY  = "review_suggestions"
SATISFIED_KEY    = "review_satisfied"
SUMMARY_KEY      = "review_summary"
CHANGES_KEY      = "last_changes"
ITERATIONS_KEY   = "iterations_data"


# ── Shared tools ──────────────────────────────────────────────────

def get_oas_spec(tool_context: ToolContext) -> str:
    """Retrieve the current OAS specification from session state."""
    spec = tool_context.state.get(SPEC_KEY, {})
    return json.dumps(spec, indent=2)


def get_postman_collection(tool_context: ToolContext) -> str:
    """Retrieve the Postman collection from session state, if provided."""
    postman = tool_context.state.get(POSTMAN_KEY)
    if not postman:
        return "No Postman collection was provided."
    return postman


def get_breaking_changes_policy(tool_context: ToolContext) -> str:
    """Return the breaking-changes policy based on whether a Postman collection is available."""
    if tool_context.state.get(HAS_POSTMAN_KEY, False):
        return (
            "A Postman collection IS available. Breaking changes ARE allowed — "
            "align the spec with the Postman collection if responses or schemas differ."
        )
    return (
        "NO Postman collection is available. Breaking changes are NOT allowed. "
        "Only additive improvements: add examples, descriptions, new error responses, etc."
    )


# ── Reviewer-only tool ────────────────────────────────────────────

def submit_review(
    satisfied: bool,
    summary: str,
    suggestions: list[str],
    tool_context: ToolContext,
) -> str:
    """
    Submit the review result. Call this once after completing your review.

    Args:
        satisfied: True if the spec needs no further improvements.
        summary: Brief description of what was found / overall state of the spec.
        suggestions: List of specific, actionable improvement instructions.
    """
    tool_context.state[SATISFIED_KEY] = satisfied
    tool_context.state[SUMMARY_KEY]   = summary
    tool_context.state[SUGGESTIONS_KEY] = suggestions if not satisfied else []

    if satisfied or not suggestions:
        return f"Review complete — spec is satisfactory. {summary}"
    return f"Review submitted: {len(suggestions)} suggestions recorded."


# ── Enhancer-only tools ───────────────────────────────────────────

def get_review_suggestions(tool_context: ToolContext) -> str:
    """Retrieve the reviewer's suggestions that must be applied to the spec."""
    suggestions = tool_context.state.get(SUGGESTIONS_KEY, [])
    if not suggestions:
        return "No suggestions found — nothing to apply."
    return json.dumps(suggestions, indent=2)


def save_enhanced_spec(
    enhanced_spec: dict,
    changes_made: list[str],
    tool_context: ToolContext,
) -> str:
    """
    Save the fully enhanced OAS specification back to session state.

    Args:
        enhanced_spec: The complete enhanced OAS 3.x object (not a partial update).
        changes_made: Human-readable list of every change applied in this iteration.
    """
    tool_context.state[SPEC_KEY]    = enhanced_spec
    tool_context.state[CHANGES_KEY] = changes_made

    # Append iteration record
    iterations: list = tool_context.state.get(ITERATIONS_KEY, [])
    iterations.append({
        "review_summary": tool_context.state.get(SUMMARY_KEY, ""),
        "suggestions":    tool_context.state.get(SUGGESTIONS_KEY, []),
        "changes_made":   changes_made,
    })
    tool_context.state[ITERATIONS_KEY] = iterations

    return f"Enhanced spec saved — {len(changes_made)} changes applied."
