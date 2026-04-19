from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class AiFileEntry:
    name: str
    full_path: str
    relative_path: str
    size_bytes: int
    content: str


def is_ai_related_path(path: Path) -> bool:
    if path.name.lower() == "agents.md":
        return True
    return any("agent" in part.lower() for part in path.parts)


def collect_ai_file_entries(root: Path) -> list[AiFileEntry]:
    entries: list[AiFileEntry] = []
    root_path = root.resolve()

    for path in sorted(root_path.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root_path)
        if not is_ai_related_path(relative_path):
            continue
        entries.append(
            AiFileEntry(
                name=path.name,
                full_path=str(path.resolve()),
                relative_path=str(relative_path),
                size_bytes=path.stat().st_size,
                content=path.read_text(encoding="utf-8"),
            )
        )

    return entries


def build_ai_file_report(root: Path, entries: list[AiFileEntry]) -> str:
    lines = [
        f"generated_at_utc: {datetime.now(timezone.utc).isoformat()}",
        f"root: {root.resolve()}",
        f"total_files: {len(entries)}",
        "",
    ]
    for entry in entries:
        lines.extend(
            [
                f"name: {entry.name}",
                f"relative_path: {entry.relative_path}",
                f"full_path: {entry.full_path}",
                f"size_bytes: {entry.size_bytes}",
                "content:",
                entry.content,
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_ai_file_report(output_path: Path, root: Path) -> Path:
    entries = collect_ai_file_entries(root)
    report = build_ai_file_report(root, entries)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return output_path
