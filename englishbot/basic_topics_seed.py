from .db import (
    get_connection,
    get_default_content_workspace_id,
    init_db,
    utc_now,
)
from .topics import get_topic_by_name, get_topic_learning_item_ids, list_topics


BASIC_TOPICS: tuple[dict[str, object], ...] = (
    {
        "topic": "weekdays",
        "title": "Дни недели",
        "items": (
            {"lemma": "monday", "ru": "понедельник", "uk": "понеділок", "bg": "понеделник"},
            {"lemma": "tuesday", "ru": "вторник", "uk": "вівторок", "bg": "вторник"},
            {"lemma": "wednesday", "ru": "среда", "uk": "середа", "bg": "сряда"},
            {"lemma": "thursday", "ru": "четверг", "uk": "четвер", "bg": "четвъртък"},
            {"lemma": "friday", "ru": "пятница", "uk": "п'ятниця", "bg": "петък"},
            {"lemma": "saturday", "ru": "суббота", "uk": "субота", "bg": "събота"},
            {"lemma": "sunday", "ru": "воскресенье", "uk": "неділя", "bg": "неделя"},
        ),
    },
    {
        "topic": "months",
        "title": "Месяцы",
        "items": (
            {"lemma": "january", "ru": "январь", "uk": "січень", "bg": "януари"},
            {"lemma": "february", "ru": "февраль", "uk": "лютий", "bg": "февруари"},
            {"lemma": "march", "ru": "март", "uk": "березень", "bg": "март"},
            {"lemma": "april", "ru": "апрель", "uk": "квітень", "bg": "април"},
            {"lemma": "may", "ru": "май", "uk": "травень", "bg": "май"},
            {"lemma": "june", "ru": "июнь", "uk": "червень", "bg": "юни"},
        ),
    },
    {
        "topic": "colors",
        "title": "Цвета",
        "items": (
            {"lemma": "red", "ru": "красный", "uk": "червоний", "bg": "червен"},
            {"lemma": "blue", "ru": "синий", "uk": "синій", "bg": "син"},
            {"lemma": "green", "ru": "зеленый", "uk": "зелений", "bg": "зелен"},
            {"lemma": "yellow", "ru": "желтый", "uk": "жовтий", "bg": "жълт"},
            {"lemma": "black", "ru": "черный", "uk": "чорний", "bg": "черен"},
            {"lemma": "white", "ru": "белый", "uk": "білий", "bg": "бял"},
        ),
    },
)


def list_basic_topic_groups() -> list[dict[str, object]]:
    init_db()
    workspace_id = get_default_content_workspace_id()
    return [
        {
            "name": str(topic["name"]),
            "title": str(topic["title"]),
            "item_count": int(topic["item_count"]),
        }
        for topic in list_topics(workspace_id=workspace_id)
    ]


def get_basic_topic_group(topic_name: str) -> dict[str, object] | None:
    init_db()
    topic = get_topic_by_name(
        topic_name.strip(),
        workspace_id=get_default_content_workspace_id(),
    )
    if topic is None:
        return None
    return {
        "id": int(topic["id"]),
        "name": str(topic["name"]),
        "title": str(topic["title"]),
    }


def resolve_basic_topic_learning_item_ids(topic_name: str) -> list[int]:
    init_db()
    topic = get_basic_topic_group(topic_name)
    if topic is None:
        return []
    return get_topic_learning_item_ids(int(topic["id"]))


def seed_basic_topics() -> dict[str, int]:
    init_db()
    timestamp = utc_now()
    workspace_id = get_default_content_workspace_id()
    created_topics = 0
    created_lexemes = 0
    created_learning_items = 0
    created_translations = 0
    created_topic_links = 0

    with get_connection() as connection:
        for topic in BASIC_TOPICS:
            topic_row = connection.execute(
                """
                SELECT id
                FROM topics
                WHERE workspace_id = ? AND name = ?
                """,
                (workspace_id, str(topic["topic"])),
            ).fetchone()
            if topic_row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO topics (
                        workspace_id,
                        workbook_key,
                        source_topic_id,
                        name,
                        title,
                        is_archived,
                        created_at,
                        updated_at
                    )
                    VALUES (?, NULL, NULL, ?, ?, 0, ?, ?)
                    """,
                    (
                        workspace_id,
                        str(topic["topic"]),
                        str(topic["title"]),
                        timestamp,
                        timestamp,
                    ),
                )
                topic_id = int(cursor.lastrowid)
                created_topics += 1
            else:
                topic_id = int(topic_row["id"])

            for item in topic["items"]:
                lemma = item["lemma"]
                lexeme_row = connection.execute(
                    """
                    SELECT id
                    FROM lexemes
                    WHERE lemma = ?
                    """,
                    (lemma,),
                ).fetchone()
                if lexeme_row is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO lexemes (lemma, created_at, updated_at)
                        VALUES (?, ?, ?)
                        """,
                        (lemma, timestamp, timestamp),
                    )
                    lexeme_id = int(cursor.lastrowid)
                    created_lexemes += 1
                else:
                    lexeme_id = int(lexeme_row["id"])

                learning_item_row = connection.execute(
                    """
                    SELECT id
                    FROM learning_items
                    WHERE workspace_id = ? AND lexeme_id = ? AND text = ?
                    """,
                    (workspace_id, lexeme_id, lemma),
                ).fetchone()
                if learning_item_row is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO learning_items (
                            workspace_id,
                            workbook_key,
                            source_learning_item_id,
                            lexeme_id,
                            text,
                            image_ref,
                            audio_ref,
                            is_archived,
                            created_at,
                            updated_at
                        )
                        VALUES (?, NULL, NULL, ?, ?, NULL, NULL, 0, ?, ?)
                        """,
                        (workspace_id, lexeme_id, lemma, timestamp, timestamp),
                    )
                    learning_item_id = int(cursor.lastrowid)
                    created_learning_items += 1
                else:
                    learning_item_id = int(learning_item_row["id"])

                for language_code in ("ru", "uk", "bg"):
                    translation_text = item[language_code]
                    translation_row = connection.execute(
                        """
                        SELECT id
                        FROM learning_item_translations
                        WHERE learning_item_id = ?
                          AND language_code = ?
                          AND translation_text = ?
                        """,
                        (learning_item_id, language_code, translation_text),
                    ).fetchone()
                    if translation_row is not None:
                        continue

                    connection.execute(
                        """
                        INSERT INTO learning_item_translations (
                            learning_item_id,
                            language_code,
                            translation_text,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            learning_item_id,
                            language_code,
                            translation_text,
                            timestamp,
                            timestamp,
                        ),
                    )
                    created_translations += 1

                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO topic_learning_items (topic_id, learning_item_id)
                    VALUES (?, ?)
                    """,
                    (topic_id, learning_item_id),
                )
                if cursor.rowcount > 0:
                    created_topic_links += 1

    return {
        "topics": len(BASIC_TOPICS),
        "created_topics": created_topics,
        "created_lexemes": created_lexemes,
        "created_learning_items": created_learning_items,
        "created_translations": created_translations,
        "created_topic_links": created_topic_links,
    }
