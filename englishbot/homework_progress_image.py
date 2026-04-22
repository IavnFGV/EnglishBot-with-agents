from __future__ import annotations

import tempfile
from pathlib import Path

from .assignment_progress_renderer import (
    AssignmentProgressSegment,
    AssignmentProgressSnapshot,
    render_assignment_progress_image,
)
from .homework import get_assignment_progress_snapshot
from .i18n import translate_for_user


def build_assignment_progress_image_snapshot(
    telegram_user_id: int,
    assignment_id: int,
    session_id: int,
) -> AssignmentProgressSnapshot:
    snapshot = get_assignment_progress_snapshot(assignment_id, session_id)
    items = list(snapshot["items"])
    current_item = _resolve_current_item(snapshot)

    return AssignmentProgressSnapshot(
        center_label=str(snapshot["assignment_title"] or ""),
        legend_labels=(
            translate_for_user(telegram_user_id, "homework.item_status.start"),
            translate_for_user(telegram_user_id, "homework.item_status.warm_up"),
            translate_for_user(telegram_user_id, "homework.item_status.almost"),
            translate_for_user(telegram_user_id, "homework.item_status.done"),
        ),
        hard_legend_label=translate_for_user(telegram_user_id, "homework.item_status.hard_clear"),
        completed_word_count=int(snapshot["completed_items"]),
        total_word_count=int(snapshot["total_items"]),
        remaining_word_count=max(0, int(snapshot["total_items"]) - int(snapshot["completed_items"])),
        estimated_round_count=max(1, len(items)),
        segments=tuple(
            AssignmentProgressSegment(
                word_id=str(item["learning_item_id"]),
                label=str(int(item["item_order"]) + 1),
                progress_value=_segment_progress_value(item),
                hard_clear=bool(item["hard_completed"]),
            )
            for item in items
        ),
        combo_charge_streak=int(snapshot["homework_correct_streak"]),
        combo_hard_active=bool(snapshot["homework_hard_mode"]),
        combo_target_word_id=None if current_item is None else str(current_item["learning_item_id"]),
    )


def render_homework_progress_image(
    telegram_user_id: int,
    assignment_id: int,
    session_id: int,
) -> Path:
    output_path = Path(tempfile.gettempdir()) / "englishbot-progress" / f"assignment-{session_id}.png"
    snapshot = build_assignment_progress_image_snapshot(
        telegram_user_id,
        assignment_id,
        session_id,
    )
    return render_assignment_progress_image(snapshot, output_path=output_path)


def _resolve_current_item(snapshot: dict[str, object]) -> dict[str, object] | None:
    items = list(snapshot["items"])
    if not items:
        return None
    current_position = int(snapshot["current_item_position"])
    if 1 <= current_position <= len(items):
        return items[current_position - 1]
    for item in items:
        if not bool(item["is_completed"]):
            return item
    return items[-1]


def _segment_progress_value(item: dict[str, object]) -> float:
    if bool(item["is_completed"]):
        return 1.0
    total_correct = int(item["easy_correct_count"]) + int(item["medium_correct_count"])
    return max(0.0, min(1.0, total_correct / 4.0))
