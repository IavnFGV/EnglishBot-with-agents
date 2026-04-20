#!/usr/bin/env python3
"""
Count lines of code in a project directory.

Features:
- Recursively scans directories
- Counts lines for selected file extensions
- Skips common junk directories
- Prints totals by file extension
- Prints totals by top-level directory
- Supports optional inclusion of blank lines and comments

Usage examples:
    python count_loc.py
    python count_loc.py /path/to/project
    python count_loc.py /path/to/project --include-blank
    python count_loc.py /path/to/project --include-comments
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Set, Tuple


DEFAULT_EXTENSIONS: Set[str] = {
    ".py",
    ".java",
    ".kt",
    ".kts",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".vue",
    ".sql",
    ".xml",
    ".yml",
    ".yaml",
    ".json",
    ".properties",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".md",
    ".html",
    ".css",
    ".scss",
    ".sass",
    ".dockerfile",
}

DEFAULT_IGNORED_DIRS: Set[str] = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "target",
    ".gradle",
    ".next",
    ".nuxt",
    ".output",
    "coverage",
}

DEFAULT_IGNORED_FILES: Set[str] = {
    ".DS_Store",
}

COMMENT_PREFIXES_BY_EXTENSION: Dict[str, Tuple[str, ...]] = {
    ".py": ("#",),
    ".sh": ("#",),
    ".bash": ("#",),
    ".zsh": ("#",),
    ".yml": ("#",),
    ".yaml": ("#",),
    ".properties": ("#",),
    ".java": ("//",),
    ".kt": ("//",),
    ".kts": ("//",),
    ".js": ("//",),
    ".ts": ("//",),
    ".tsx": ("//",),
    ".jsx": ("//",),
    ".vue": ("//",),
    ".sql": ("--",),
    ".css": ("/*", "*", "*/"),
    ".scss": ("/*", "*", "*/"),
    ".sass": ("/*", "*", "*/"),
    ".html": ("<!--", "-->"),
    ".xml": ("<!--", "-->"),
    ".md": ("<!--",),
}


@dataclass(frozen=True)
class FileStats:
    """Statistics for a single file."""

    path: Path
    total_lines: int
    counted_lines: int


@dataclass
class AggregateStats:
    """Aggregated statistics for the whole scan."""

    total_files: int
    total_lines: int
    counted_lines: int
    by_extension: Dict[str, int]
    by_top_level_dir: Dict[str, int]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Count lines of code in a project directory."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Project root directory. Defaults to current directory.",
    )
    parser.add_argument(
        "--include-blank",
        action="store_true",
        help="Include blank lines in the counted result.",
    )
    parser.add_argument(
        "--include-comments",
        action="store_true",
        help="Include comment-only lines in the counted result.",
    )
    parser.add_argument(
        "--extensions",
        nargs="*",
        default=None,
        help=(
            "Optional list of extensions to include, for example: "
            "--extensions .py .java .ts"
        ),
    )
    parser.add_argument(
        "--show-files",
        action="store_true",
        help="Print per-file statistics.",
    )
    return parser.parse_args()


def normalize_extensions(raw_extensions: Iterable[str] | None) -> Set[str]:
    """
    Normalize file extensions.

    Each extension must start with a dot, except 'Dockerfile',
    which is treated as a special file name pattern.
    """
    if raw_extensions is None:
        return DEFAULT_EXTENSIONS.copy()

    normalized: Set[str] = set()
    for ext in raw_extensions:
        value: str = ext.strip()
        if not value:
            continue

        if value.lower() == "dockerfile":
            normalized.add(".dockerfile")
            continue

        if not value.startswith("."):
            value = f".{value}"

        normalized.add(value.lower())

    return normalized


def is_included_file(file_path: Path, allowed_extensions: Set[str]) -> bool:
    """Return True if the file should be included in the scan."""
    if file_path.name in DEFAULT_IGNORED_FILES:
        return False

    if file_path.name.lower() == "dockerfile" and ".dockerfile" in allowed_extensions:
        return True

    return file_path.suffix.lower() in allowed_extensions


def iter_source_files(root: Path, allowed_extensions: Set[str]) -> Iterator[Path]:
    """Yield source files recursively, skipping ignored directories."""
    for path in root.rglob("*"):
        if path.is_dir():
            continue

        if any(part in DEFAULT_IGNORED_DIRS for part in path.parts):
            continue

        if is_included_file(path, allowed_extensions):
            yield path


def is_blank_line(line: str) -> bool:
    """Return True if the line is blank."""
    return line.strip() == ""


def is_comment_only_line(line: str, extension: str) -> bool:
    """
    Return True if the line looks like a comment-only line.

    This is a pragmatic heuristic, not a parser.
    It works reasonably well for quick project statistics.
    """
    stripped: str = line.strip()
    if stripped == "":
        return False

    prefixes: Tuple[str, ...] = COMMENT_PREFIXES_BY_EXTENSION.get(extension, ())
    return any(stripped.startswith(prefix) for prefix in prefixes)


def count_file_lines(
    file_path: Path,
    include_blank: bool,
    include_comments: bool,
) -> FileStats:
    """Count lines for a single file."""
    total_lines: int = 0
    counted_lines: int = 0

    extension: str
    if file_path.name.lower() == "dockerfile":
        extension = ".dockerfile"
    else:
        extension = file_path.suffix.lower()

    try:
        with file_path.open("r", encoding="utf-8", errors="ignore") as file:
            for line in file:
                total_lines += 1

                if not include_blank and is_blank_line(line):
                    continue

                if not include_comments and is_comment_only_line(line, extension):
                    continue

                counted_lines += 1
    except OSError as exc:
        raise RuntimeError(f"Failed to read file: {file_path}") from exc

    return FileStats(
        path=file_path,
        total_lines=total_lines,
        counted_lines=counted_lines,
    )


def top_level_bucket(root: Path, file_path: Path) -> str:
    """
    Return the top-level directory bucket for the file.

    Example:
    - src/englishbot/bot.py -> src
    - README.md -> .
    """
    relative: Path = file_path.relative_to(root)
    parts: Tuple[str, ...] = relative.parts

    if len(parts) <= 1:
        return "."

    return parts[0]


def aggregate_stats(
    root: Path,
    files: Iterable[Path],
    include_blank: bool,
    include_comments: bool,
) -> Tuple[AggregateStats, List[FileStats]]:
    """Aggregate statistics for all matching files."""
    total_files: int = 0
    total_lines: int = 0
    counted_lines: int = 0
    by_extension: Dict[str, int] = {}
    by_top_level_dir: Dict[str, int] = {}
    file_stats_list: List[FileStats] = []

    for file_path in files:
        file_stats: FileStats = count_file_lines(
            file_path=file_path,
            include_blank=include_blank,
            include_comments=include_comments,
        )

        total_files += 1
        total_lines += file_stats.total_lines
        counted_lines += file_stats.counted_lines
        file_stats_list.append(file_stats)

        extension: str
        if file_path.name.lower() == "dockerfile":
            extension = ".dockerfile"
        else:
            extension = file_path.suffix.lower()

        by_extension[extension] = by_extension.get(extension, 0) + file_stats.counted_lines

        bucket: str = top_level_bucket(root=root, file_path=file_path)
        by_top_level_dir[bucket] = by_top_level_dir.get(bucket, 0) + file_stats.counted_lines

    stats: AggregateStats = AggregateStats(
        total_files=total_files,
        total_lines=total_lines,
        counted_lines=counted_lines,
        by_extension=dict(sorted(by_extension.items(), key=lambda item: (-item[1], item[0]))),
        by_top_level_dir=dict(
            sorted(by_top_level_dir.items(), key=lambda item: (-item[1], item[0]))
        ),
    )

    file_stats_list.sort(key=lambda item: (-item.counted_lines, str(item.path)))
    return stats, file_stats_list


def print_report(
    root: Path,
    stats: AggregateStats,
    file_stats_list: List[FileStats],
    show_files: bool,
    include_blank: bool,
    include_comments: bool,
) -> None:
    """Print the formatted report."""
    print(f"Root: {root}")
    print(f"Files scanned: {stats.total_files}")
    print(f"Total physical lines: {stats.total_lines}")
    print(f"Counted lines: {stats.counted_lines}")
    print(f"Include blank lines: {include_blank}")
    print(f"Include comment lines: {include_comments}")
    print()

    print("By extension:")
    for extension, line_count in stats.by_extension.items():
        print(f"  {extension:<12} {line_count}")

    print()
    print("By top-level directory:")
    for bucket, line_count in stats.by_top_level_dir.items():
        print(f"  {bucket:<20} {line_count}")

    if show_files:
        print()
        print("By file:")
        for item in file_stats_list:
            relative_path: Path = item.path.relative_to(root)
            print(
                f"  {str(relative_path):<80} "
                f"counted={item.counted_lines:<8} total={item.total_lines}"
            )


def validate_root(root: Path) -> Path:
    """Validate and normalize the root directory."""
    resolved_root: Path = root.resolve()

    if not resolved_root.exists():
        raise FileNotFoundError(f"Directory does not exist: {resolved_root}")

    if not resolved_root.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {resolved_root}")

    return resolved_root


def main() -> int:
    """Program entry point."""
    args: argparse.Namespace = parse_args()

    try:
        root: Path = validate_root(Path(args.root))
        extensions: Set[str] = normalize_extensions(args.extensions)
        source_files: List[Path] = list(iter_source_files(root, extensions))

        stats, file_stats_list = aggregate_stats(
            root=root,
            files=source_files,
            include_blank=args.include_blank,
            include_comments=args.include_comments,
        )

        print_report(
            root=root,
            stats=stats,
            file_stats_list=file_stats_list,
            show_files=args.show_files,
            include_blank=args.include_blank,
            include_comments=args.include_comments,
        )
        return 0

    except (FileNotFoundError, NotADirectoryError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())