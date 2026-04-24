import asyncio
import json
from typing import Final

from .build_info import BuildInfo


STATUS_SERVER_HOST: Final[str] = "0.0.0.0"
STATUS_SERVER_PORT: Final[int] = 8080


def build_status_payload(build_info: BuildInfo) -> dict[str, str]:
    return {
        "service": "englishbot",
        "status": "ok",
        "version": build_info.version,
        "commit": build_info.git_commit,
        "build_time_utc": build_info.build_time_utc,
        "build_ref": build_info.build_ref,
        "env": build_info.env_name,
    }


def build_status_response(path: str, build_info: BuildInfo) -> tuple[int, bytes]:
    if path not in {"/", "/healthz", "/version"}:
        return 404, json.dumps({"error": "not_found"}).encode("utf-8")

    payload = build_status_payload(build_info)
    if path == "/version":
        payload.pop("status")

    return 200, json.dumps(payload, sort_keys=True).encode("utf-8")


def _build_http_response(status_code: int, body: bytes) -> bytes:
    reason = "OK" if status_code == 200 else "Not Found"
    headers = [
        f"HTTP/1.1 {status_code} {reason}",
        "Content-Type: application/json; charset=utf-8",
        f"Content-Length: {len(body)}",
        "Connection: close",
        "",
        "",
    ]
    return "\r\n".join(headers).encode("utf-8") + body


async def _handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    build_info: BuildInfo,
) -> None:
    try:
        request_head = await reader.readuntil(b"\r\n\r\n")
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        writer.close()
        await writer.wait_closed()
        return

    request_line = request_head.splitlines()[0].decode("utf-8", errors="replace")
    parts = request_line.split(" ")
    path = parts[1] if len(parts) >= 2 else "/"

    status_code, body = build_status_response(path, build_info)
    writer.write(_build_http_response(status_code, body))
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def start_status_server(build_info: BuildInfo) -> asyncio.AbstractServer:
    return await asyncio.start_server(
        lambda reader, writer: _handle_connection(reader, writer, build_info),
        STATUS_SERVER_HOST,
        STATUS_SERVER_PORT,
    )
