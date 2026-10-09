"""The reload bar's server half (decisions-4, variant 1 of :8003/reload-prompt/).

The server names the commit it runs on every API answer, and writes the same commit into the
index.html it serves, so an open tab can tell that the server under it has moved on. The client
half is tests/js/update-check.test.js.
"""
import re
import subprocess
from pathlib import Path

import pytest

import app
from harness import make_kitchen

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def kitchen(tmp_path):
    return make_kitchen(tmp_path)


def test_the_commit_is_the_checkout_s_own(monkeypatch):
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert app.APP_COMMIT == head
    assert re.fullmatch(r"[0-9a-f]{40}", app.APP_COMMIT)


def test_every_api_answer_names_the_commit(kitchen, tmp_path):
    for path in ("/api/recipes", "/api/me"):
        r = kitchen.client.get(path)
        assert r.headers.get("X-App-Commit") == app.APP_COMMIT, path
    # a refusal is an answer too: the gate's 401 carries it, so a logged-out tab still hears it
    anon = app.app.test_client()
    r = anon.get("/api/recipes")
    assert r.status_code == 401
    assert r.headers.get("X-App-Commit") == app.APP_COMMIT


def test_the_page_carries_the_same_commit_and_is_never_cached(kitchen, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><html><head><title>x</title></head>"
                                     "<body></body></html>", encoding="utf-8")
    monkeypatch.setattr(app, "BASE_DIR", tmp_path)
    r = kitchen.client.get("/")
    html = r.get_data(as_text=True)
    assert f'<meta name="app-commit" content="{app.APP_COMMIT}">' in html
    assert html.index('name="app-commit"') < html.index("</head>")
    assert r.headers["Cache-Control"] == "no-cache"


def test_a_server_git_cannot_name_sends_nothing(kitchen, tmp_path, monkeypatch):
    """No commit, no header and no meta, and the page then never shows the bar."""
    monkeypatch.setattr(app, "APP_COMMIT", "")
    assert "X-App-Commit" not in kitchen.client.get("/api/recipes").headers
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><head></head><body></body></html>", encoding="utf-8")
    monkeypatch.setattr(app, "BASE_DIR", tmp_path)
    assert "app-commit" not in kitchen.client.get("/").get_data(as_text=True)


def test_only_a_commit_shaped_answer_is_trusted(monkeypatch):
    for out, want in (("0123456789abcdef0123456789abcdef01234567\n", "0123456789abcdef0123456789abcdef01234567"),
                      ("fatal: not a git repository\n", ""), ("", ""), ('" onload="x\n', "")):
        monkeypatch.setattr(app.subprocess, "run",
                            lambda *a, _o=out, **k: subprocess.CompletedProcess(a, 0, _o, ""))
        assert app._running_commit() == want
