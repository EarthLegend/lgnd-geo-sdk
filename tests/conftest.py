import pytest


@pytest.fixture(autouse=True)
def _no_machine_user(monkeypatch):
    """Sign in through the browser unless a test sets a machine user's credentials itself."""
    monkeypatch.delenv("LGND_GEO_CLIENT_ID", raising=False)
    monkeypatch.delenv("LGND_GEO_CLIENT_SECRET", raising=False)
