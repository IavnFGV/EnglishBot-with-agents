import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot.build_info import BuildInfo
from englishbot.status_server import build_status_payload, build_status_response


def _build_info() -> BuildInfo:
    return BuildInfo(
        version="1.2.3",
        git_commit="abc1234",
        build_time_utc="2026-04-24T00:00:00Z",
        build_ref="refs/heads/main",
        env_name="production",
    )


def test_build_status_payload_exposes_service_health_and_build_metadata() -> None:
    assert build_status_payload(_build_info()) == {
        "service": "englishbot",
        "status": "ok",
        "version": "1.2.3",
        "commit": "abc1234",
        "build_time_utc": "2026-04-24T00:00:00Z",
        "build_ref": "refs/heads/main",
        "env": "production",
    }


def test_build_status_response_supports_root_healthz_and_version() -> None:
    for path in ("/", "/healthz"):
        status_code, body = build_status_response(path, _build_info())
        assert status_code == 200
        assert json.loads(body) == build_status_payload(_build_info())

    version_status, version_body = build_status_response("/version", _build_info())
    assert version_status == 200
    assert json.loads(version_body) == {
        "service": "englishbot",
        "version": "1.2.3",
        "commit": "abc1234",
        "build_time_utc": "2026-04-24T00:00:00Z",
        "build_ref": "refs/heads/main",
        "env": "production",
    }


def test_build_status_response_returns_not_found_for_unknown_path() -> None:
    status_code, body = build_status_response("/missing", _build_info())

    assert status_code == 404
    assert json.loads(body) == {"error": "not_found"}
