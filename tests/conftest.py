from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures():
    return FIXTURES


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.content = text.encode("utf-8")
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def fake_get(monkeypatch):
    """Replace requests.get with a stub; returns the list of requested URLs.

    Set the reply with fake_get.reply = FakeResponse(...) or an exception instance.
    """
    import requests

    calls = []

    def get(url, timeout=None):
        calls.append(url)
        if isinstance(get.reply, Exception):
            raise get.reply
        return get.reply

    get.reply = FakeResponse("")
    get.calls = calls
    monkeypatch.setattr(requests, "get", get)
    return get
