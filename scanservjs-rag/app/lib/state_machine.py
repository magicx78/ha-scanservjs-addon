"""
Search state transition helpers.
"""

PHASES = (
    "idle",
    "started",
    "retrieving",
    "reranking",
    "generating_answer",
    "done",
    # legacy phases kept for backward compatibility
    "finding_hits",
    "building_answer",
    "expanding_result",
    "completed",
    "empty",
    "error",
    "cancelled",
)

TERMINAL = {"done", "completed", "empty", "error", "cancelled"}

ALLOWED = {
    "idle": {"started"},
    # New phase flow
    "done": {"started"},
    "started": {
        "retrieving",
        "done",
        "finding_hits",  # legacy
        "error",
        "cancelled",
        "empty",
    },
    "retrieving": {
        "reranking",
        "generating_answer",
        "error",
        "cancelled",
        "empty",
    },
    "reranking": {"generating_answer", "done", "error", "cancelled", "empty"},
    "generating_answer": {"done", "error", "cancelled"},
    # Legacy flow
    "completed": {"started"},
    "finding_hits": {"building_answer", "empty", "error", "cancelled", "expanding_result"},
    "building_answer": {"expanding_result", "completed", "error", "cancelled"},
    "expanding_result": {"completed", "error", "cancelled"},
    "empty": {"started"},
    "error": {"started"},
    "cancelled": {"started"},
}


def is_valid_transition(current: str, target: str) -> bool:
    if current not in ALLOWED:
        return True
    return target in ALLOWED[current]


def normalize_transition(current: str, target: str) -> str:
    if target not in PHASES:
        return current
    if is_valid_transition(current, target):
        return target
    return current
