import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.workspaces import (
    InvalidWorkspaceKindError,
    InvalidWorkspaceRoleError,
    WorkspaceEditPermissionError,
    WorkspaceKindMismatchError,
    WorkspaceNotFoundError,
    add_workspace_member,
    create_workspace,
    ensure_teacher_can_edit_workspace_content,
    find_shared_workspace_for_teacher_and_student,
    find_workspaces_for_user_by_role,
    get_or_create_student_workspace,
    get_workspace,
    get_workspace_member,
    list_workspaces_for_user,
    user_is_workspace_member,
)


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "workspaces.sqlite3"
    db.init_db()


def test_init_db_creates_workspace_tables_with_kind(tmp_path: Path) -> None:
    setup_db(tmp_path)

    with sqlite3.connect(db.DB_PATH) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        column_names = {
            row[1] for row in connection.execute("PRAGMA table_info(workspaces)").fetchall()
        }

    assert "workspaces" in table_names
    assert "workspace_members" in table_names
    assert "kind" in column_names


def test_create_workspace_persists_row_and_kind(tmp_path: Path) -> None:
    setup_db(tmp_path)

    result = create_workspace(" Family Space ", kind="student")
    row = get_workspace(int(result["workspace_id"]))

    assert result["name"] == "Family Space"
    assert result["kind"] == "student"
    assert row is not None
    assert row["name"] == "Family Space"
    assert row["kind"] == "student"


def test_create_workspace_rejects_invalid_kind(tmp_path: Path) -> None:
    setup_db(tmp_path)

    with pytest.raises(InvalidWorkspaceKindError):
        create_workspace("Broken", kind="catalog")


def test_add_workspace_member_persists_and_upserts_role(tmp_path: Path) -> None:
    setup_db(tmp_path)
    workspace = create_workspace("Shared")

    first_result = add_workspace_member(workspace["workspace_id"], 501, "teacher")
    second_result = add_workspace_member(workspace["workspace_id"], 501, "student")

    with db.get_connection() as connection:
        membership = connection.execute(
            """
            SELECT workspace_id, telegram_user_id, role
            FROM workspace_members
            WHERE workspace_id = ? AND telegram_user_id = ?
            """,
            (workspace["workspace_id"], 501),
        ).fetchone()

    assert first_result["role"] == "teacher"
    assert second_result["role"] == "student"
    assert membership is not None
    assert membership["role"] == "student"


def test_add_workspace_member_rejects_invalid_role_and_missing_workspace(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    workspace = create_workspace("Shared")

    with pytest.raises(InvalidWorkspaceRoleError):
        add_workspace_member(workspace["workspace_id"], 601, "parent")

    with pytest.raises(WorkspaceNotFoundError):
        add_workspace_member(999, 601, "teacher")


def test_list_workspaces_for_user_returns_joined_workspaces_with_kind(tmp_path: Path) -> None:
    setup_db(tmp_path)
    family_workspace = create_workspace("Family", kind="teacher")
    school_workspace = create_workspace("School", kind="student")
    add_workspace_member(family_workspace["workspace_id"], 701, "teacher")
    add_workspace_member(school_workspace["workspace_id"], 701, "student")

    workspaces = list_workspaces_for_user(701)

    assert [workspace["name"] for workspace in workspaces] == ["Family", "School"]
    assert [workspace["kind"] for workspace in workspaces] == ["teacher", "student"]
    assert [workspace["role"] for workspace in workspaces] == ["teacher", "student"]


def test_find_workspaces_for_user_by_role_filters_memberships(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher_workspace = create_workspace("Teacher Space")
    student_workspace = create_workspace("Student Space", kind="student")
    add_workspace_member(teacher_workspace["workspace_id"], 801, "teacher")
    add_workspace_member(student_workspace["workspace_id"], 801, "student")

    teacher_workspaces = find_workspaces_for_user_by_role(801, "teacher")
    student_workspaces = find_workspaces_for_user_by_role(801, "student")

    assert [workspace["name"] for workspace in teacher_workspaces] == ["Teacher Space"]
    assert [workspace["name"] for workspace in student_workspaces] == ["Student Space"]


def test_workspace_membership_helpers_return_expected_rows(tmp_path: Path) -> None:
    setup_db(tmp_path)
    workspace = create_workspace("Shared")
    add_workspace_member(workspace["workspace_id"], 901, "teacher")
    add_workspace_member(workspace["workspace_id"], 902, "student")

    teacher_membership = get_workspace_member(workspace["workspace_id"], 901)

    assert teacher_membership is not None
    assert teacher_membership["role"] == "teacher"
    assert user_is_workspace_member(workspace["workspace_id"], 901, "teacher") is True
    assert user_is_workspace_member(workspace["workspace_id"], 902) is True
    assert user_is_workspace_member(workspace["workspace_id"], 903) is False


def test_find_shared_workspace_for_teacher_and_student_filters_by_kind(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher_workspace = create_workspace("Teacher", kind="teacher")
    student_workspace = create_workspace("Student", kind="student")
    add_workspace_member(teacher_workspace["workspace_id"], 1001, "teacher")
    add_workspace_member(teacher_workspace["workspace_id"], 1002, "student")
    add_workspace_member(student_workspace["workspace_id"], 1001, "teacher")
    add_workspace_member(student_workspace["workspace_id"], 1002, "student")

    workspace = find_shared_workspace_for_teacher_and_student(1001, 1002, kind="student")

    assert workspace is not None
    assert workspace["id"] == student_workspace["workspace_id"]
    assert workspace["kind"] == "student"


def test_get_or_create_student_workspace_is_stable(tmp_path: Path) -> None:
    setup_db(tmp_path)

    first_workspace = get_or_create_student_workspace(1101, 1102)
    second_workspace = get_or_create_student_workspace(1101, 1102)

    assert first_workspace["id"] == second_workspace["id"]
    assert first_workspace["kind"] == "student"
    assert get_workspace_member(int(first_workspace["id"]), 1101)["role"] == "teacher"
    assert get_workspace_member(int(first_workspace["id"]), 1102)["role"] == "student"


def test_find_shared_workspace_for_teacher_and_student_returns_none_when_ambiguous(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    first_workspace = create_workspace("Student A", kind="student")
    second_workspace = create_workspace("Student B", kind="student")
    add_workspace_member(first_workspace["workspace_id"], 1151, "teacher")
    add_workspace_member(first_workspace["workspace_id"], 1152, "student")
    add_workspace_member(second_workspace["workspace_id"], 1151, "teacher")
    add_workspace_member(second_workspace["workspace_id"], 1152, "student")

    workspace = find_shared_workspace_for_teacher_and_student(1151, 1152, kind="student")

    assert workspace is None


def test_teacher_only_content_edit_checks_workspace_kind_and_role(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher_workspace = create_workspace("Teacher", kind="teacher")
    student_workspace = create_workspace("Student", kind="student")
    add_workspace_member(teacher_workspace["workspace_id"], 1201, "teacher")
    add_workspace_member(student_workspace["workspace_id"], 1201, "teacher")
    add_workspace_member(teacher_workspace["workspace_id"], 1202, "student")

    workspace = ensure_teacher_can_edit_workspace_content(
        teacher_workspace["workspace_id"],
        1201,
    )
    assert workspace["kind"] == "teacher"

    with pytest.raises(WorkspaceKindMismatchError):
        ensure_teacher_can_edit_workspace_content(student_workspace["workspace_id"], 1201)

    with pytest.raises(WorkspaceEditPermissionError):
        ensure_teacher_can_edit_workspace_content(teacher_workspace["workspace_id"], 1202)
