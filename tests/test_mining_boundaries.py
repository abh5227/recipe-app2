"""The machine-checked half of docs/mining-decision.md.

⚠️ THESE TESTS ARE THE AUTHORIZATION GATE. The decision says a boundary with no test beside it is
not yet a boundary, and that extraction is blocked until boundary (g) has one. This file is that
test. It is written BEFORE the first extraction rather than after, because a boundary retrofitted
to a schema that already broke it is not a boundary.

⚠️ IT CHECKS EVERY DATABASE THE PROJECT OWNS, and that is not a flourish. The first version of
test_mined_tables_hold_no_corpus_text ran only against the sources.db fixture. Mined facts key on
library_id and would live in recipes.db, which has all 13 library_* tables while sources.db has
none, so that test guarded a database the mined tables will never appear in. It would have passed
vacuously forever. Anything named mined_* is checked wherever it turns up.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import brand_guard  # noqa: E402
import build_sources_db as bsd  # noqa: E402
from harness import make_kitchen  # noqa: E402

MINED_PREFIX = "mined_"
ALLOWED_MINED_TEXT_COLS = {"source_slug", "source_url", "library_id", "a_id", "b_id",
                           "from_id", "to_id", "dish_type", "method", "role", "cuisine",
                           "technique", "course", "fact_kind"}
# the columns a mined fact would carry a NAME in, which is what the brand check reads
NAME_COLS = {"library_id", "a_id", "b_id", "from_id", "to_id", "dish_type", "name", "canonical"}


def mined_tables(conn):
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
        (MINED_PREFIX + "%",))]


@pytest.fixture
def dbs(tmp_path):
    """Every database the project owns, so a mined table cannot hide in one of them."""
    kdir = tmp_path / "k"
    kdir.mkdir()
    k = make_kitchen(kdir)
    recipes = sqlite3.connect(str(k.db))
    sources = sqlite3.connect(bsd.build(tmp_path / "sources.db"))
    yield {"recipes.db": recipes, "sources.db": sources}
    recipes.close(); sources.close()


def check_no_corpus_text(conn):
    for t in mined_tables(conn):
        cols = list(conn.execute(f"PRAGMA table_info({t})"))
        for col in cols:
            name, decl = col[1], (col[2] or "").upper()
            if "CHAR" in decl or "TEXT" in decl or "CLOB" in decl:
                assert name in ALLOWED_MINED_TEXT_COLS, (
                    f"{t}.{name} is a free-text column on a mined table. Facts leave the "
                    f"extractor as tuples and the sentence is never retained. "
                    f"docs/mining-decision.md boundary (b) and (f).")
        assert "n" in {c[1] for c in cols}, (
            f"{t} has no `n` column. Boundary (c): only aggregates across recipes are stored, "
            f"and a row that cannot say how many recipes it came from is not an aggregate.")


def check_no_brand_names(conn, brands=None):
    b = brands if brands is not None else brand_guard.load_brands()
    assert b, "brands.csv is empty or missing. Boundary (g) has no list to enforce."
    for t in mined_tables(conn):
        cols = [c[1] for c in conn.execute(f"PRAGMA table_info({t})")]
        for col in [c for c in cols if c in NAME_COLS]:
            for (v,) in conn.execute(f"SELECT DISTINCT {col} FROM {t} WHERE {col} IS NOT NULL"):
                verdict, mark = brand_guard.classify(v, brands=b)
                assert verdict != "brand", (
                    f"{t}.{col} holds {v!r}, which is the mark {mark}. Boundary (g): a brand is "
                    f"never stored as a generic ingredient or dish type, and it is not mapped to "
                    f"a near neighbor either.")


def test_mined_tables_hold_no_corpus_text(dbs):
    for name, conn in dbs.items():
        check_no_corpus_text(conn)


def test_mined_facts_carry_no_brand_names(dbs):
    """⚠️ BOUNDARY (g). This test existing is what unblocks extraction."""
    for name, conn in dbs.items():
        check_no_brand_names(conn)


# ── the list itself has to hold up, or the test above enforces nothing ──────────────────────

def test_brand_list_loads_and_is_not_trivially_small():
    b = brand_guard.load_brands()
    assert len(b) >= 40, f"only {len(b)} surface forms. The probe found more than that."
    assert len(set(b.values())) >= 20, "too few distinct marks to be the real list"


def test_known_marks_are_caught_in_every_surface_form_seen():
    for form in ("velveeta", "velveeta cheese", "crisco", "crisco oil", "strawberry jello",
                 "jell o", "bisquick mix", "campbell s tomato soup", "cool whip", "oreos"):
        assert brand_guard.is_brand(form), f"{form!r} is a mark and was not caught"


def test_generic_foods_are_never_blocked():
    """⚠️ DEFAULT IS KEEP, and these two are why the rule exists.

    The probe's heuristic called `oleo` and `graham cracker` brands, 9,016 of the 30,114
    occurrences it flagged, 29.9% of them. `oleo` is short for oleomargarine, a generic term for
    margarine. `graham cracker` is a generic food and the mark in that aisle is Honey Maid.
    Blocking either would have cut a real food out of the library.
    """
    for food in ("oleo", "graham cracker crumbs", "graham cracker crust", "butter", "pecans",
                 "ground beef", "hamburger", "cherries", "mayo", "pretzels", "crabmeat",
                 "cream style corn", "brussels sprouts"):
        assert not brand_guard.is_brand(food), f"{food!r} is a real food and was blocked"


def test_the_heuristic_flags_and_never_excludes():
    """An unlisted mark is SUSPECT, which is a review queue and not an exclusion."""
    for unlisted in ("hellmann s mayonnaise", "kraft brand cheddar", "newman s own dressing"):
        verdict, _ = brand_guard.classify(unlisted)
        assert verdict == "suspect", f"{unlisted!r} should be flagged, got {verdict}"
        assert not brand_guard.is_brand(unlisted), "a suspect must never be excluded"
