import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot.i18n import TRANSLATIONS, translate


def test_translate_returns_requested_language_text() -> None:
    assert translate("settings.title", "ru") == "Настройки"


def test_translate_falls_back_to_default_language_for_unknown_language() -> None:
    assert translate("settings.title", "unknown") == "Settings"


def test_translate_falls_back_to_default_catalog_when_translation_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(TRANSLATIONS["ru"], "settings.title", raising=False)

    assert translate("settings.title", "ru") == "Settings"


def test_translate_raises_for_missing_key() -> None:
    with pytest.raises(KeyError):
        translate("missing.translation.key", "en")
