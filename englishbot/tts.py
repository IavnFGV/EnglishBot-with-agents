from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from .assets import create_learning_item_tts_variant, get_learning_item_tts_variant
from .config import get_tts_base_url, get_tts_model_key, get_tts_timeout_seconds


VOICE_DISPLAY_OVERRIDES: dict[str, tuple[str, str]] = {
    "en_US_amy": ("Amy", "Female, US"),
    "en_US_lessac": ("Emma", "Female, US"),
    "en_US_ryan": ("Ryan", "Male, US"),
    "en_GB_alba": ("Alice", "Female, UK"),
    "en_GB_alan": ("Alan", "Male, UK"),
}


class TTSClientError(Exception):
    pass


class TTSUnavailableError(TTSClientError):
    pass


class TTSValidationError(TTSClientError):
    pass


class TTSUnexpectedError(TTSClientError):
    pass


@dataclass(frozen=True, slots=True)
class TTSVoice:
    voice_id: str
    label: str

    @property
    def display_name(self) -> str:
        override = VOICE_DISPLAY_OVERRIDES.get(self.voice_id)
        if override is not None:
            return override[0]
        normalized = self.label.strip()
        return normalized or self.voice_id

    @property
    def subtitle(self) -> str:
        override = VOICE_DISPLAY_OVERRIDES.get(self.voice_id)
        if override is not None:
            return override[1]
        return ""

    @property
    def button_label(self) -> str:
        if self.subtitle:
            return f"{self.display_name} - {self.subtitle}"
        return self.display_name


@dataclass(frozen=True, slots=True)
class TTSVoiceCatalog:
    default_voice_id: str
    voices: tuple[TTSVoice, ...]

    def find_voice(self, voice_id: str | None) -> TTSVoice | None:
        if voice_id is None:
            return None
        normalized_voice_id = str(voice_id).strip()
        if not normalized_voice_id:
            return None
        for voice in self.voices:
            if voice.voice_id == normalized_voice_id:
                return voice
        return None

    def resolve_voice_id(self, preferred_voice_id: str | None) -> str:
        preferred_voice = self.find_voice(preferred_voice_id)
        if preferred_voice is not None:
            return preferred_voice.voice_id
        default_voice = self.find_voice(self.default_voice_id)
        if default_voice is not None:
            return default_voice.voice_id
        if self.default_voice_id.strip():
            return self.default_voice_id.strip()
        if self.voices:
            return self.voices[0].voice_id
        raise TTSUnexpectedError("TTS voice catalog is empty.")


class InternalTTSClient:
    def __init__(self, base_url: str, *, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.model_key = get_tts_model_key()

    def fetch_voices(self) -> TTSVoiceCatalog:
        payload = self._request_json("/voices")
        default_voice_id = str(payload.get("default_voice_id") or "").strip()
        raw_voices = payload.get("voices")
        if not default_voice_id or not isinstance(raw_voices, list):
            raise TTSUnexpectedError("TTS /voices response is invalid.")

        voices: list[TTSVoice] = []
        for raw_voice in raw_voices:
            if not isinstance(raw_voice, dict):
                continue
            voice_id = str(raw_voice.get("id") or "").strip()
            label = str(raw_voice.get("label") or "").strip()
            if not voice_id:
                continue
            voices.append(TTSVoice(voice_id=voice_id, label=label))

        if not voices:
            raise TTSUnexpectedError("TTS /voices response is empty.")
        return TTSVoiceCatalog(default_voice_id=default_voice_id, voices=tuple(voices))

    def synthesize(self, *, text: str, voice_id: str) -> bytes:
        normalized_text = str(text).strip()
        normalized_voice_id = str(voice_id).strip()
        if not normalized_text:
            raise TTSValidationError("TTS text is empty.")
        if not normalized_voice_id:
            raise TTSValidationError("TTS voice_id is empty.")

        payload = json.dumps(
            {
                "text": normalized_text,
                "voice_id": normalized_voice_id,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/v1/synthesize",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                content_type = response.headers.get("Content-Type", "")
                body = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 400:
                raise TTSValidationError("TTS rejected synthesize request.") from exc
            if exc.code >= 500:
                raise TTSUnavailableError("TTS service returned a server error.") from exc
            raise TTSUnexpectedError("TTS service returned an unexpected error.") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TTSUnavailableError("TTS service is unavailable.") from exc

        if "audio/ogg" not in content_type.lower():
            raise TTSUnexpectedError("TTS service returned an unexpected content type.")
        if not body:
            raise TTSUnexpectedError("TTS service returned an empty audio payload.")
        return body

    def _request_json(self, path: str) -> dict[str, object]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                content_type = response.headers.get("Content-Type", "")
                body = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code >= 500:
                raise TTSUnavailableError("TTS service returned a server error.") from exc
            raise TTSUnexpectedError("TTS service returned an unexpected error.") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TTSUnavailableError("TTS service is unavailable.") from exc

        if "application/json" not in content_type.lower():
            raise TTSUnexpectedError("TTS service returned an unexpected content type.")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TTSUnexpectedError("TTS service returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise TTSUnexpectedError("TTS service returned invalid JSON.")
        return payload


def is_tts_enabled() -> bool:
    return get_tts_base_url() is not None


def build_tts_client() -> InternalTTSClient | None:
    base_url = get_tts_base_url()
    if base_url is None:
        return None
    return InternalTTSClient(
        base_url,
        timeout_seconds=get_tts_timeout_seconds(),
    )


def get_or_create_learning_item_tts_variant(
    *,
    client: InternalTTSClient,
    learning_item_id: int,
    text: str,
    preferred_voice_id: str | None,
):
    normalized_text = str(text).strip()
    if not normalized_text:
        raise TTSValidationError("TTS text is empty.")
    catalog = client.fetch_voices()
    voice_id = catalog.resolve_voice_id(preferred_voice_id)
    model_key = str(getattr(client, "model_key", "") or get_tts_model_key()).strip()
    variant_row = get_learning_item_tts_variant(
        learning_item_id,
        voice_id=voice_id,
        tts_model_key=model_key,
        source_text=normalized_text,
    )
    if variant_row is not None:
        return variant_row
    audio_bytes = client.synthesize(text=normalized_text, voice_id=voice_id)
    return create_learning_item_tts_variant(
        learning_item_id,
        voice_id=voice_id,
        tts_model_key=model_key,
        source_text=normalized_text,
        audio_bytes=audio_bytes,
    )
