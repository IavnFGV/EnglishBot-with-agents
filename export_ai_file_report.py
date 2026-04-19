from __future__ import annotations

import argparse
from pathlib import Path

from englishbot.ai_file_report import write_ai_file_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write a report with AGENTS.md and agent-related files."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root to scan. Defaults to the current directory.",
    )
    parser.add_argument(
        "--output",
        default="ai_file_state.txt",
        help="Output report file. Defaults to ai_file_state.txt.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root).resolve()
    output = Path(args.output).resolve()
    written_path = write_ai_file_report(output, root)
    print(written_path)


if __name__ == "__main__":
    main()
