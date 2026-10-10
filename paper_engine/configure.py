"""Create .env (first run) and optionally add a separate Hermes agent token.

    python -m paper_engine.configure                 # create .env if missing
    python -m paper_engine.configure --agent-token   # also add PAPER_AGENT_TOKEN if absent
    python -m paper_engine.configure --agent-token --print   # show the agent token once

Existing values are never overwritten. Token values are only printed with --print.
"""

import argparse
import os
import re
import secrets
from pathlib import Path

PLACEHOLDER = "replace-with-a-random-token-at-least-32-characters"
AGENT_LINE = re.compile(r"^[ \t]*PAPER_AGENT_TOKEN[ \t]*=[ \t]*(\S*)[ \t]*$", re.MULTILINE)


def _restrict(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - permissions are best effort on Windows
        pass


def create_env(path: Path, template: Path) -> bool:
    content = (
        template.read_text(encoding="utf-8")
        if template.exists()
        else f"PAPER_API_TOKEN={PLACEHOLDER}\n"
    )
    content = content.replace(PLACEHOLDER, secrets.token_urlsafe(48))
    try:
        with path.open("x", encoding="utf-8") as file:
            file.write(content)
    except FileExistsError:
        return False
    _restrict(path)
    return True


def add_agent_token(path: Path) -> tuple[bool, str]:
    """Append PAPER_AGENT_TOKEN if missing or blank. Returns (added, token_value)."""
    text = path.read_text(encoding="utf-8")
    match = AGENT_LINE.search(text)
    if match and match.group(1):
        return False, match.group(1)
    token = secrets.token_urlsafe(48)
    if match:
        text = AGENT_LINE.sub(f"PAPER_AGENT_TOKEN={token}", text, count=1)
    else:
        text = text + ("" if text.endswith("\n") or not text else "\n")
        text += f"PAPER_AGENT_TOKEN={token}\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    _restrict(temporary)
    os.replace(temporary, path)
    _restrict(path)
    return True, token


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", default=".env", help="Path to the .env file")
    parser.add_argument("--agent-token", action="store_true", help="Add PAPER_AGENT_TOKEN")
    parser.add_argument("--print", action="store_true", help="Print the agent token value")
    args = parser.parse_args(argv)
    path = Path(args.env)
    if create_env(path, path.with_name(".env.example")):
        print("Created .env with a private local API token. No exchange credentials are needed.")
    else:
        print("Existing .env left unchanged.")
    if args.agent_token:
        added, token = add_agent_token(path)
        print(
            f"{'Added' if added else 'Kept existing'} PAPER_AGENT_TOKEN in {path.resolve()}."
            " Give this token only to the Hermes MCP server."
        )
        if args.print:
            print(token)


if __name__ == "__main__":
    main()
