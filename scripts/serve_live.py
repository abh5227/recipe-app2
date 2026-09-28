"""Serve the app against the LIVE database and the LIVE photo folder, from a PINNED checkout.

⚠️ :8000 NEVER SERVES THE WORKING REPO'S dist/. That folder is rebuilt by every `npm run build`,
including the ones that go into building a preview, and a bundle can stop matching the server that
serves it. Measured consequence: a preview build put a client that sends `{id, text}` steps in front
of a server old enough to read a non-string step as "", which would have blanked every method step
of the first recipe saved. Nothing about that is visible until someone saves.

So :8000 runs from its own git worktree, pinned to a pushed commit, with its own dist/ that no
build in the working repo can reach. This script is what points that checkout at the real data:

    git worktree add ../recipe-app-serve <pushed-sha>
    cd ../recipe-app-serve && npm install && npm run build
    python3.13 scripts/serve_live.py            # serves :8000 against the real DB and photos

THE CODE comes from THIS checkout (the one this file is in), so the bundle and the server are the
same commit by construction. THE DATA comes from the main working tree, found through git rather
than hardcoded. Nothing is symlinked: app.DB, models.DB and images.IMAGES_DIR are all redirectable
module globals, which is how the test harness already points them at a temp directory.

⚠️ NOTHING ELSE IN THIS CHECKOUT REACHES LIVE. build_db.py, migrate.py and every script resolve
their own BASE_DIR, so they operate on this worktree's (absent) recipes.db, not on the real one.
That is deliberate: a symlinked recipes.db would let a stray build_db.py run rebuild live.
"""
import os
import pathlib
import subprocess
import sys

CODE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))


def live_root():
    """The main working tree, which owns recipes.db and static/images. From LIVE_ROOT if set, else
    from git: a worktree's common git dir is the MAIN checkout's .git, whose parent is that tree."""
    env = os.environ.get("LIVE_ROOT")
    if env:
        return pathlib.Path(env).resolve()
    out = subprocess.run(
        ["git", "-C", str(CODE), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, check=True).stdout.strip()
    return pathlib.Path(out).resolve().parent


def main():
    root = live_root()
    db = root / "recipes.db"
    photos = root / "static" / "images"
    for name, path in (("database", db), ("photo folder", photos)):
        if not path.exists():
            sys.exit(f"live {name} not found at {path} — set LIVE_ROOT to the main checkout")

    import app
    import images
    import models
    app.DB = models.DB = db
    images.IMAGES_DIR = photos          # BOTH the write path and, since this commit, the read path

    port = int(os.environ.get("PORT", "8000"))
    print(f"code   : {CODE} ({subprocess.run(['git', '-C', str(CODE), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()})")
    print(f"bundle : {CODE / 'dist'}")
    print(f"db     : {db}")
    print(f"photos : {photos}")
    app.app.run(port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
