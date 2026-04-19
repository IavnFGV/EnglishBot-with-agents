from .db import get_connection, init_db, utc_now


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
    return [
        {
            "name": str(topic["topic"]),
            "title": str(topic["title"]),
            "item_count": len(topic["items"]),
        }
        for topic in BASIC_TOPICS
    ]


def get_basic_topic_group(topic_name: str) -> dict[str, object] | None:
    normalized_topic_name = topic_name.strip().casefold()
    for topic in BASIC_TOPICS:
        if str(topic["topic"]).casefold() == normalized_topic_name:
            return topic
    return None


def resolve_basic_topic_learning_item_ids(topic_name: str) -> list[int]:
    topic = get_basic_topic_group(topic_name)
    if topic is None:
        return []

    lemmas = [str(item["lemma"]) for item in topic["items"]]
    placeholders = ", ".join("?" for _ in lemmas)
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT lexemes.lemma, learning_items.id
            FROM learning_items
            JOIN lexemes
              ON lexemes.id = learning_items.lexeme_id
            WHERE lexemes.lemma IN ({placeholders})
            """,
            tuple(lemmas),
        ).fetchall()

    learning_item_ids_by_lemma = {
        str(row["lemma"]): int(row["id"])
        for row in rows
    }
    if any(lemma not in learning_item_ids_by_lemma for lemma in lemmas):
        return []

    return [learning_item_ids_by_lemma[lemma] for lemma in lemmas]


def seed_basic_topics() -> dict[str, int]:
    init_db()
    timestamp = utc_now()
    created_lexemes = 0
    created_learning_items = 0
    created_translations = 0

    with get_connection() as connection:
        for topic in BASIC_TOPICS:
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
                    WHERE lexeme_id = ? AND text = ?
                    """,
                    (lexeme_id, lemma),
                ).fetchone()
                if learning_item_row is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO learning_items (
                            lexeme_id,
                            text,
                            image_ref,
                            audio_ref,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, NULL, NULL, ?, ?)
                        """,
                        (lexeme_id, lemma, timestamp, timestamp),
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

    return {
        "topics": len(BASIC_TOPICS),
        "created_lexemes": created_lexemes,
        "created_learning_items": created_learning_items,
        "created_translations": created_translations,
    }
