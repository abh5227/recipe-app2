"""Assert that a cold-started app actually SERVED — not merely that something returned 200.

Used by .github/workflows/cold-start.yml after following README's "Run it" from a fresh clone.
Runnable locally too: python3.13 scripts/cold_start_check.py http://127.0.0.1:8000

WHY FOUR CHECKS AND NOT ONE. A 500 page is a response; so is a Vite dev index that was never
built; so is a stale shell naming a bundle that no longer exists; so is a static file server
that knows nothing about Flask. Each check below kills one of those, and each was PROVEN to
fail against a deliberately sabotaged app rather than assumed to:

    working app                              -> exit 0
    dist/ removed            (today's break) -> exit 1  "GET / returned 500, not 200"
    dist/index.html = dev index, never built -> exit 1  "served the Vite DEV index"
    built index, hashed bundle deleted       -> exit 1  "references /assets/index-*.js but it returned 404"
    a server that 200s EVERY path            -> exit 1  "no content-hashed /assets/index-*.js"

That last one is the control: a check that cannot fail vacuously is worse than no check.
"""
import json
import re
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")


def get(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "cold-start-check"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def fail(msg):
    print(f"COLD START FAILED: {msg}")
    sys.exit(1)


# 1. "/" answers at all. A missing dist/index.html raises FileNotFoundError -> 500.
status, _, body = get("/")
if status != 200:
    fail(f"GET / returned {status}, not 200 (a missing dist/index.html gives 500)")
html = body.decode("utf-8", "replace")

# 2. it is the BUILT shell. Vite emits content-hashed asset names; the dev index does not.
if "/@vite/client" in html:
    fail("GET / served the Vite DEV index, not a production build — `npm run build` was not run")
match = re.search(r"/assets/index-[A-Za-z0-9_-]+\.js", html)
if not match:
    fail("GET / has no content-hashed /assets/index-*.js — this is not Vite build output")

# 3. the bundle it names is really there and really served as JavaScript.
asset = match.group(0)
status, ctype, bundle = get(asset)
if status != 200:
    fail(f"the shell references {asset} but it returned {status}")
if "javascript" not in ctype:
    fail(f"{asset} was served as {ctype!r}, not JavaScript")
if len(bundle) < 10_000:
    fail(f"{asset} is only {len(bundle)} bytes — not a real bundle")

# 4. Flask + the ORM + the freshly built DB answer, not just the static files. /api/me is the
#    only unauthenticated JSON endpoint (the rest are login-gated and 401 on a fresh install).
status, _, body = get("/api/me")
if status != 200:
    fail(f"GET /api/me returned {status} — only static files worked; the app/DB path is broken")
try:
    payload = json.loads(body)
except ValueError:
    fail(f"GET /api/me did not return JSON: {body[:120]!r}")
if "user" not in payload:
    fail(f"GET /api/me JSON has no 'user' key: {payload!r}")

print(f"COLD START OK: / 200 ({len(html)}B) -> {asset} 200 ({len(bundle)}B); /api/me {payload}")
