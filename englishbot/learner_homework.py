from .homework import (
    AssignmentNotFoundError,
    get_assignment_progress_snapshot,
    list_active_assignments,
)
from .training import find_latest_incomplete_assignment_training_session


HOMEWORK_ACTION_START = "start"
HOMEWORK_ACTION_CONTINUE = "continue"
HOMEWORK_PROGRESS_NOT_STARTED = "not_started"
HOMEWORK_PROGRESS_IN_PROGRESS = "in_progress"


def list_learner_homework(student_user_id: int) -> list[dict[str, object]]:
    assignments = list_active_assignments(student_user_id)
    return [
        _build_assignment_snapshot(student_user_id, assignment)
        for assignment in assignments
    ]


def get_learner_homework_overview(
    student_user_id: int,
    assignment_id: int,
) -> dict[str, object]:
    for assignment in list_active_assignments(student_user_id):
        if int(assignment["id"]) == assignment_id:
            return _build_assignment_snapshot(student_user_id, assignment)
    raise AssignmentNotFoundError


def _build_assignment_snapshot(
    student_user_id: int,
    assignment: dict[str, object],
) -> dict[str, object]:
    assignment_id = int(assignment["id"])
    item_count = int(assignment["item_count"])
    incomplete_session = find_latest_incomplete_assignment_training_session(
        student_user_id,
        assignment_id,
    )
    if incomplete_session is None:
        return {
            "assignment_id": assignment_id,
            "title": assignment["title"],
            "item_count": item_count,
            "completed_items": 0,
            "total_items": item_count,
            "current_item_position": 0,
            "current_stage": None,
            "action_key": HOMEWORK_ACTION_START,
            "progress_state": HOMEWORK_PROGRESS_NOT_STARTED,
        }

    progress_snapshot = get_assignment_progress_snapshot(
        assignment_id,
        int(incomplete_session["id"]),
    )
    return {
        "assignment_id": assignment_id,
        "title": assignment["title"],
        "item_count": item_count,
        "completed_items": int(progress_snapshot["completed_items"]),
        "total_items": int(progress_snapshot["total_items"]),
        "current_item_position": int(progress_snapshot["current_item_position"]),
        "current_stage": progress_snapshot["current_stage"],
        "action_key": HOMEWORK_ACTION_CONTINUE,
        "progress_state": HOMEWORK_PROGRESS_IN_PROGRESS,
    }
