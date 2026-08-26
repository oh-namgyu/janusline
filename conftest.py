import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

# every test states the mode it needs, so the developer's own environment must
# not decide it — and no test may ever reach a real provider
AMBIENT = ("AUTH_TOKEN", "JANUSLINE_FAKE", "JANUSLINE_MODEL", "ANTHROPIC_API_KEY")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in AMBIENT:
        monkeypatch.delenv(name, raising=False)
