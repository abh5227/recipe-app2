"""scripts/serve_live.py — the guard that keeps :8000 off the shared dist/.

⚠️ WHY THIS FILE EXISTS. The rule was written at length in CLAUDE.md and in the script's own
docstring, and nothing enforced it. `CODE` comes from `__file__`, so running the script from the main
working tree (`python3.13 scripts/serve_live.py`) served that tree's dist/ on :8000 — the exact folder
both documents forbid. It happened during the commit-3 round. The commits matched by luck at that
moment, and the next `npm run build` behind a preview is what makes it dangerous: a client that sends
a newer payload shape in front of an older server is a silent data-loss hazard, which is the
measured incident the rule was written for in the first place.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import serve_live                                   # noqa: E402


def test_it_refuses_to_serve_live_from_the_main_working_tree(monkeypatch):
    """CODE == the tree that owns recipes.db means the bundle being served is the shared dist/."""
    monkeypatch.setattr(serve_live, "live_root", lambda: serve_live.CODE)
    with pytest.raises(SystemExit) as e:
        serve_live.main()
    assert "refusing to serve live from the main working tree" in str(e.value)
    assert "recipe-app-serve" in str(e.value), "the message has to say what to do instead"


def test_a_pinned_checkout_is_accepted_and_points_at_the_live_data(monkeypatch, tmp_path):
    """The other side of the guard: a CODE that is NOT the live root gets past it, and the live
    database and photo folder it resolves are the ones under that root. Stops before app.run."""
    root = tmp_path / "main"
    (root / "static" / "images").mkdir(parents=True)
    (root / "recipes.db").write_bytes(b"")
    monkeypatch.setattr(serve_live, "live_root", lambda: root)
    seen = {}
    monkeypatch.setitem(sys.modules, "app", type(sys)("app"))
    monkeypatch.setitem(sys.modules, "images", type(sys)("images"))
    monkeypatch.setitem(sys.modules, "models", type(sys)("models"))
    sys.modules["app"].app = type("F", (), {"run": lambda self, **k: seen.update(k)})()
    serve_live.main()
    assert sys.modules["app"].DB == root / "recipes.db"
    assert sys.modules["models"].DB == root / "recipes.db"
    assert sys.modules["images"].IMAGES_DIR == root / "static" / "images"
    assert seen["debug"] is False and seen["use_reloader"] is False


def test_a_missing_live_database_stops_it(monkeypatch, tmp_path):
    """No silent fallback to an empty DB. The whole point is that :8000 serves the real data."""
    root = tmp_path / "empty"
    (root / "static" / "images").mkdir(parents=True)
    monkeypatch.setattr(serve_live, "live_root", lambda: root)
    with pytest.raises(SystemExit) as e:
        serve_live.main()
    assert "live database not found" in str(e.value)
