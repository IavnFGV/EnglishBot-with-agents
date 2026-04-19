import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.workspaces import (
    InvalidWorkspaceRoleError,
    WorkspaceNotFoundError,
    add_workspace_member,
    create_workspace,
    find_workspaces_for_user_by_role,
    list_workspaces_for_user,
)


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "workspaces.sqlite3"
    db.init_db()


def test_init_db_creates_workspace_tables(tmp_path: Path) -> None:
    setup_db(tmp_path)

    with sqlite3.connect(db.DB_PATH) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "workspaces" in table_names
    assert "workspace_members" in table_names


def test_create_workspace_persists_row(tmp_path: Path) -> None:
    setup_db(tmp_path)

    result = create_workspace(" Family Space ")

    with db.get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, name, created_at
            FROM workspaces
            WHERE id = ?
            """,
            (result["workspace_id"],),
        ).fetchone()

    assert result["name"] == "Family Space"
    assert row is not None
    assert row["name"] == "Family Space"
    assert row["created_at"] == result["created_at"]


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
        user = connection.execute(
            """
            SELECT telegram_user_id
            FROM users
            WHERE telegram_user_id = ?
            """,
            (501,),
        ).fetchone()

    assert first_result["role"] == "teacher"
    assert second_result["role"] == "student"
    assert membership is not None
    assert membership["role"] == "student"
    assert user is not None


def test_add_workspace_member_rejects_invalid_role_and_missing_workspace(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    workspace = create_workspace("Shared")

    with pytest.raises(InvalidWorkspaceRoleError):
        add_workspace_member(workspace["workspace_id"], 601, "parent")

    with pytest.raises(WorkspaceNotFoundError):
        add_workspace_member(999, 601, "teacher")


def test_list_workspaces_for_user_returns_joined_workspaces(tmp_path: Path) -> None:
    setup_db(tmp_path)
    family_workspace = create_workspace("Family")
    school_workspace = create_workspace("School")
    solo_workspace = create_workspace()
    add_workspace_member(family_workspace["workspace_id"], 701, "teacher")
    add_workspace_member(school_workspace["workspace_id"], 701, "student")
    add_workspace_member(solo_workspace["workspace_id"], 702, "teacher")

    workspaces = list_workspaces_for_user(701)

    assert [workspace["name"] for workspace in workspaces] == ["Family", "School"]
    assert [workspace["role"] for workspace in workspaces] == ["teacher", "student"]


def test_find_workspaces_for_user_by_role_filters_memberships(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher_workspace = create_workspace("Teacher Space")
    student_workspace = create_workspace("Student Space")
    add_workspace_member(teacher_workspace["workspace_id"], 801, "teacher")
    add_workspace_member(student_workspace["workspace_id"], 801, "student")

    teacher_workspaces = find_workspaces_for_user_by_role(801, "teacher")
    student_workspaces = find_workspaces_for_user_by_role(801, "student")

    assert [workspace["name"] for workspace in teacher_workspaces] == ["Teacher Space"]
    assert [workspace["name"] for workspace in student_workspaces] == ["Student Space"]
