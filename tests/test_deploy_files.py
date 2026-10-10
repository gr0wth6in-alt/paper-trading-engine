import configparser
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
DEPLOY = ROOT / "deploy"
SCRIPTS = sorted(DEPLOY.glob("*.sh"))
UNITS = sorted([*DEPLOY.glob("*.service"), *DEPLOY.glob("*.timer")])


def unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def test_engine_service_runs_one_loopback_worker_as_paper():
    service = unit(DEPLOY / "paper-engine.service")["Service"]
    assert service["User"] == "paper" and service["Group"] == "paper"
    assert service["ExecStart"] == "/opt/paper-trading-engine/.venv/bin/python -m paper_engine"
    assert service["WorkingDirectory"] == "/opt/paper-trading-engine"
    assert service["ReadWritePaths"] == "/opt/paper-trading-engine/data"
    assert service["MemoryMax"] == "900M" and service["ProtectSystem"] == "strict"
    main = (ROOT / "paper_engine" / "__main__.py").read_text(encoding="utf-8")
    assert 'host="127.0.0.1"' in main and "workers=1" in main


def test_units_contain_no_secrets_or_wildcard_binds():
    for path in UNITS:
        text = path.read_text(encoding="utf-8")
        settings = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        assert "0.0.0.0" not in settings, path.name
        assert not re.search(r"PAPER_(API|AGENT|MCP)_TOKEN=", text), path.name
        assert "\r\n" not in text, path.name
        unit(path)  # parses


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_shell_scripts_are_strict_and_lf(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    assert "\r\n" not in text


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="bash -n needs Linux bash"
)
@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_shell_scripts_parse(path):
    subprocess.run(["bash", "-n", str(path)], check=True)


def test_deployment_guide_references_existing_files():
    guide = (ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")
    referenced = set(
        re.findall(
            r"(?<![\w/])((?:deploy|docs/hermes)/[\w./-]+\.(?:sh|ps1|service|timer|conf|yaml|md))",
            guide,
        )
    )
    assert referenced, "guide should reference deploy files"
    missing = [p for p in sorted(referenced) if not (ROOT / p).is_file()]
    assert missing == []
    for module in re.findall(r"-m ((?:paper_engine|tests)\.[\w.]+)", guide):
        assert (ROOT / (module.replace(".", "/") + ".py")).is_file(), module
    assert "cat /etc/os-release; python3 --version" in guide
    for fallback in ("deadsnakes", "pyenv", "Ubuntu 24.04"):
        assert fallback in guide
