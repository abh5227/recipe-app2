"""Serve the app against a REHEARSAL COPY of the database, from a pinned checkout, for a look.

⚠️ THIS IS NOT serve_live.py AND THE DIFFERENCE IS THE DATA. serve_live.py points a pinned worktree
at the REAL database so :8000 is the owner's app. This points a pinned worktree at a COPY, so a
round can be clicked through before it is applied to anything. Everything a click writes lands in
the copy and in a copy of the photo folder, and live is never opened.

⚠️ IT RUNS FROM ITS OWN WORKTREE, FOR THE REASON serve_live.py SPELLS OUT AT LENGTH. The working
repo's dist/ is rebuilt by every `npm run build`, including the ones behind a test run, so a server
started from the working tree can end up serving a bundle from a different commit than its own code.
Measured once already: a preview build put a client that sends `{id, text}` steps in front of a
server old enough to read a non-string step as "", which would have blanked every method step of the
first recipe saved.

    git worktree add ../recipe-app-rehearse HEAD
    cd ../recipe-app-rehearse && npm install && npm run build
    python3.13 scripts/serve_rehearsal.py --db <the copy> --photos <a copy of static/images>

THE CODE comes from THIS checkout, so the bundle and the server are the same commit by
construction. THE DATA is whatever copy you hand it.

⚠️ AND THE PHOTO FOLDER IS A COPY TOO. images.IMAGES_DIR is both the read path and the WRITE path,
so handing it live's folder would let one click during a rehearsal drop a file into the real
library. It is required rather than defaulted, for the same reason --db is.
"""
import argparse
import os
import pathlib
import subprocess
import sys

CODE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
sys.path.insert(0, str(CODE / "scripts"))

from corpus_guard import refuse_live                                        # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, help="the rehearsal copy to serve")
    ap.add_argument("--photos", required=True, help="a COPY of static/images")
    ap.add_argument("--port", type=int, default=8002)
    # ⚠️ PRESENT AND ALL BUT UNUSABLE, DELIBERATELY. Every script that can open a database wires the
    #    shared guard the same way, and tests/test_live_guards.py reads the folder rather than a
    #    list of names. Typing it here still runs into the working-tree refusal below, so there is
    #    no path from this script to the owner's app on :8000.
    ap.add_argument("--i-mean-live", action="store_true")
    a = ap.parse_args(argv)
    refuse_live(a.db, a.i_mean_live)

    # The main working tree, found through git: a worktree's common git dir is the MAIN checkout's
    # .git, whose parent is that tree.
    out = subprocess.run(
        ["git", "-C", str(CODE), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, check=True).stdout.strip()
    root = pathlib.Path(out).resolve().parent
    if CODE == root:
        sys.exit(f"refusing to serve from the main working tree ({CODE}).\n"
                 f"  Its dist/ is rebuilt by every npm run build, so the bundle and the server can\n"
                 f"  stop being the same commit. Run this from a pinned worktree instead:\n"
                 f"    git worktree add ../recipe-app-rehearse HEAD\n"
                 f"    cd ../recipe-app-rehearse && npm install && npm run build\n"
                 f"    python3.13 scripts/serve_rehearsal.py --db <copy> --photos <copy>")

    db, photos = pathlib.Path(a.db).resolve(), pathlib.Path(a.photos).resolve()
    for name, path in (("database", db), ("photo folder", photos)):
        if not path.exists():
            sys.exit(f"rehearsal {name} not found at {path}")
    if photos == (root / "static" / "images").resolve():
        sys.exit(f"refusing to serve the REAL photo folder ({photos}).\n"
                 f"  images.IMAGES_DIR is the write path too, so one click would drop a file into\n"
                 f"  the owner's library. Copy it first:\n"
                 f"    cp -R '{root / 'static' / 'images'}' <somewhere>/images")

    import app
    import images
    import models
    app.DB = models.DB = db
    images.IMAGES_DIR = photos

    sha = subprocess.run(["git", "-C", str(CODE), "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    print(f"code   : {CODE} ({sha})")
    print(f"bundle : {CODE / 'dist'}")
    print(f"db     : {db}    <- A COPY. Live is not open.")
    print(f"photos : {photos}")
    print(f"port   : {a.port}")
    app.app.run(port=a.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
