Task: update this repository devcontainer setup to be practical and minimal for daily development.

Before making changes:
1. Read AGENTS.md
2. Read context/englishbot_handoff.md
3. Use architect to propose the smallest practical devcontainer setup
4. Use infra_minimizer to preserve useful developer ergonomics
5. Use complexity_guard to remove non-essential complexity
6. Use coder to implement the approved result

Requirements:
- This is dev environment work, not a business feature
- Keep the setup minimal, but not stripped down to the point of losing useful workflow
- The devcontainer must share Codex configuration between host and container
- Add a bind mount from host ~/.codex to /home/vscode/.codex
- Preserve SSH access with a readonly mount from host ~/.ssh to /home/vscode/.ssh
- Preserve pip cache across rebuilds using /home/vscode/.cache/pip
- Set PIP_CACHE_DIR accordingly
- Automatically install useful VS Code extensions for this repository
- Keep the default profile lightweight
- Do not add optional AI services, Ollama, ComfyUI, docker-compose, GPU setup, or decorative environment notes
- Do not add permission-fix scripts unless they are truly required
- Prefer one .devcontainer/devcontainer.json and reuse the existing Dockerfile if appropriate
- If postCreateCommand is used, it should install dependencies in the most practical way for this project
- use as base mcr.microsoft.com/devcontainers/python:3.12-bookworm

Expected output:
- updated devcontainer files
- short explanation of every added or removed field
- how to reopen in container
- how to verify that Codex config, SSH, and pip cache are available inside the container