"""
Search state transition helpers.
"""

PHASES = (
    "started",
    "finding_hits",
    "building_answer",
    "expanding_result",
    "completed",
    "empty",
    "error",
    "cancelled",
)

TERMINAL = {"completed", "empty", "error", "cancelled"}

ALLOWED = {
    "completed": {"started"},
    "started": {"finding_hits", "error", "cancelled", "empty"},
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
