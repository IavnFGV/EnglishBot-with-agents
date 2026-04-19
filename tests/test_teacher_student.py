import sys
from pathlib import Path

import pytest
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.teacher_student import (
    InviteAlreadyUsedError,
    InviteNotFoundError,
    StudentAlreadyLinkedError,
    TeacherRoleRequiredError,
    create_invite,
    get_invite,
    get_teacher_link,
    join_with_invite,
)
from englishbot.user_profiles import get_user_role, set_user_role
from englishbot.workspaces import get_workspace_member


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "teacher_student.sqlite3"
    db.init_db()


def test_create_invite_persists_code_for_teacher(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(101, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")

    code = create_invite(teacher.id)

    invite = get_invite(code)
    assert invite is not None
    assert invite["code"] == code
    assert invite["teacher_user_id"] == teacher.id
    assert invite["used_at"] is None


def test_create_invite_rejects_non_teacher(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(102, "Student")
    db.save_user(user)

    with pytest.raises(TeacherRoleRequiredError):
        create_invite(user.id)


def test_join_with_invite_creates_link_marks_invite_used_and_preserves_default_student_role(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    teacher = make_user(103, "Teacher")
    student = make_user(104, "Student")
    db.save_user(teacher)
    db.save_user(student)
    set_user_role(teacher.id, "teacher")

    code = create_invite(teacher.id)
    teacher_user_id = join_with_invite(student.id, code.lower())

    invite = get_invite(code)
    link = get_teacher_link(student.id)
    student_role = get_user_role(student.id)
    workspace_id = db.get_default_content_workspace_id()
    assert teacher_user_id == teacher.id
    assert invite is not None
    assert invite["used_by_user_id"] == student.id
    assert invite["used_at"] is not None
    assert link is not None
    assert link["teacher_user_id"] == teacher.id
    assert student_role == "student"
    assert get_workspace_member(workspace_id, teacher.id)["role"] == "teacher"
    assert get_workspace_member(workspace_id, student.id)["role"] == "student"


def test_join_with_invite_rejects_missing_or_used_codes(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(105, "Teacher")
    student = make_user(106, "Student")
    other_student = make_user(107, "Other")
    db.save_user(teacher)
    db.save_user(student)
    db.save_user(other_student)
    set_user_role(teacher.id, "teacher")

    code = create_invite(teacher.id)

    with pytest.raises(InviteNotFoundError):
        join_with_invite(student.id, "missing")

    join_with_invite(student.id, code)

    with pytest.raises(InviteAlreadyUsedError):
        join_with_invite(other_student.id, code)


def test_join_with_invite_rejects_student_already_linked(tmp_path: Path) -> None:
    setup_db(tmp_path)
    first_teacher = make_user(108, "TeacherA")
    second_teacher = make_user(109, "TeacherB")
    student = make_user(110, "Student")
    db.save_user(first_teacher)
    db.save_user(second_teacher)
    db.save_user(student)
    set_user_role(first_teacher.id, "teacher")
    set_user_role(second_teacher.id, "teacher")

    first_code = create_invite(first_teacher.id)
    second_code = create_invite(second_teacher.id)
    join_with_invite(student.id, first_code)

    with pytest.raises(StudentAlreadyLinkedError):
        join_with_invite(student.id, second_code)


def test_join_with_invite_allows_teacher_to_join_own_invite_without_losing_role(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    teacher = make_user(111, "TeacherSelf")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")

    code = create_invite(teacher.id)
    teacher_user_id = join_with_invite(teacher.id, code)

    invite = get_invite(code)
    link = get_teacher_link(teacher.id)
    teacher_role = get_user_role(teacher.id)
    workspace_id = db.get_default_content_workspace_id()
    assert teacher_user_id == teacher.id
    assert invite is not None
    assert invite["used_by_user_id"] == teacher.id
    assert invite["used_at"] is not None
    assert link is not None
    assert link["teacher_user_id"] == teacher.id
    assert link["student_user_id"] == teacher.id
    assert teacher_role == "teacher"
    assert get_workspace_member(workspace_id, teacher.id)["role"] == "teacher"
