Task: package this repository into a minimal working devcontainer for development.

Read AGENTS.md and context/englishbot_handoff.md first.

Use agents in this order:
1. architect
2. infra_minimizer
3. complexity_guard
4. coder

Constraints:
- minimal setup only
- no optional AI tooling
- no docker-compose
- no multiple profiles
- no speculative infrastructure

Deliver:
- the devcontainer files
- a short explanation of why each file is needed
- how to reopen in container
- how to run tests