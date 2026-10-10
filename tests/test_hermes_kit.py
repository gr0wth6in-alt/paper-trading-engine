import re
from pathlib import Path

from paper_engine.mcp_server import TOOL_NAMES

ROOT = Path(__file__).parents[1]
KIT = ROOT / "docs" / "hermes"


def test_config_example_whitelists_exactly_the_implemented_tools():
    text = (KIT / "config.example.yaml").read_text(encoding="utf-8")
    include = text.split("include:", 1)[1].split("\n\n", 1)[0]
    listed = re.findall(r"^\s+- (\w+)$", include, re.MULTILINE)
    assert sorted(listed) == sorted(TOOL_NAMES)
    assert '"-m", "paper_engine.mcp_server"' in text
    assert "/opt/paper-trading-engine/deploy/hermes-mcp.sh" in text


def test_skill_and_readme_only_reference_real_tools():
    known = set(TOOL_NAMES)
    for path in (KIT / "skills" / "paper-trader" / "SKILL.md", KIT / "README.md"):
        text = path.read_text(encoding="utf-8")
        for name in re.findall(r"`((?:get|open|close)_[a-z_]+)`", text):
            assert name in known, f"{path.name} mentions unknown tool {name}"
    skill = (KIT / "skills" / "paper-trader" / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: paper-trader\n")
    assert "paper trading" in skill.lower()


def test_wrapper_execs_the_module_and_prints_nothing_on_stdout():
    script = (ROOT / "deploy" / "hermes-mcp.sh").read_text(encoding="utf-8")
    assert script.startswith("#!/usr/bin/env bash")
    assert 'exec "$APP_DIR/.venv/bin/python" -m paper_engine.mcp_server' in script
    for line in script.splitlines():
        if line.strip().startswith("echo"):
            assert line.rstrip().endswith(">&2"), line
    assert "\r\n" not in script
