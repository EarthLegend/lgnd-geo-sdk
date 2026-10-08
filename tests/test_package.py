"""The core needs no agent framework: each framework's adapter is a submodule, opted into."""

import subprocess
import sys


def test_importing_the_core_loads_no_agent_framework():
    loaded = subprocess.run(
        [sys.executable, "-c", "import sys, lgnd_geo_sdk; print(*sys.modules)"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    assert "pydantic_ai" not in loaded
