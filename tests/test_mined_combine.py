"""The arithmetic that combines two mined sources, checked BEFORE a second source exists.

⚠️ WRITTEN BEFORE THE LOAD, NOT AFTER. The combine has never had a second corpus to check it
against, so every number it produces today is unfalsifiable: with one source N cancels out, the
marginals are whole by construction, and a share is its own denominator. Adding Wikibooks makes
all three wrong in ways that raise no error and print plausible numbers. These tests are what
turns that into a failure instead of a quiet corruption.

⚠️ THE LOAD-BEARING TEST IS test_single_source_lift_is_unchanged. It runs against the real
RecipeNLG rows and proves the formula AND the stored N by reproducing 361,138 lifts that were
computed independently, months earlier, by pairing_run.py. If N were wrong, or the marginals read
from the wrong table, that test fails before Wikibooks is ever fetched.

⚠️ THE SYNTHETIC HALF EXISTS BECAUSE CI HAS NO CORPUS. A fresh clone's mined tables are empty, so
a real-data-only suite would pass vacuously forever. The fixtures below build two sources whose
expected values are hand-calculated in the test body, so the arithmetic is checked everywhere.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import mined_combine as MC  # noqa: E402
from harness import make_kitchen  # noqa: E402

# ── the hand-calculated fixture ────────────────────────────────────────────────────────────────
#
# Three sources, chosen so that every wrong way of combining gives a visibly different answer.
#
#   alpha   N=100   x in 40 recipes, y in 25.   (x,y) together in 20.   lift = 20*100/(40*25) = 2.0
#   beta    N= 10   x in  6 recipes, y in  5.   (x,y) together in  4.   lift =  4*10/( 6* 5) = 1.3333
#   gamma   N=1000  x in 500, y in 400.         NO pairing row at all.
#
# gamma is the trap. It holds both ingredients and never pairs them, which is the ordinary case
# for a large corpus and a specific pair. Its marginals belong in the combined denominator and
# its zero belongs in the numerator.
ALPHA, BETA, GAMMA = "alpha", "beta", "gamma"


def _seed(conn, dish_rows=True):
    conn.executemany("INSERT INTO mined_corpus (source_slug, n, mined_at) VALUES (?,?,NULL)",
                     [(ALPHA, 100), (BETA, 10), (GAMMA, 1000)])
    conn.executemany(
        "INSERT INTO mined_occurrences (library_id, n, n_recipes, source_slug) VALUES (?,?,?,?)",
        [("x", 40, 40, ALPHA), ("y", 25, 25, ALPHA),
         ("x", 6, 6, BETA), ("y", 5, 5, BETA),
         ("x", 500, 500, GAMMA), ("y", 400, 400, GAMMA)])
    conn.executemany(
        "INSERT INTO mined_pairings (a_id,b_id,n,n_a,n_b,lift,source_slug) VALUES (?,?,?,?,?,?,?)",
        [("x", "y", 20, 40, 25, 2.0, ALPHA),
         ("x", "y", 4, 6, 5, 4 * 10 / (6 * 5), BETA)])
    if dish_rows:
        # dish d1: 90 recipes in alpha of which 81 carry x, 10 in beta of which 1 carries x.
        # gamma holds the dish 900 times and never records the ingredient.
        conn.executemany("INSERT INTO mined_dish (dish_id, dish, n, source_slug) VALUES (?,?,?,?)",
                         [("d1", "test dish", 90, ALPHA), ("d1", "test dish", 10, BETA),
                          ("d1", "test dish", 900, GAMMA)])
        conn.executemany(
            "INSERT INTO mined_dish_ingredient (dish_id, library_id, n, n_dish, source_slug) "
            "VALUES (?,?,?,?,?)",
            [("d1", "x", 81, 90, ALPHA), ("d1", "x", 1, 10, BETA)])
        conn.executemany(
            "INSERT INTO mined_dish_method (dish_id, method, n, source_slug) VALUES (?,?,?,?)",
            [("d1", "baked", 45, ALPHA), ("d1", "baked", 5, BETA)])
    conn.commit()


@pytest.fixture
def synth(tmp_path):
    """A real migrated database (migration 042 included) holding the fixture above."""
    kdir = tmp_path / "k"; kdir.mkdir()
    k = make_kitchen(kdir)
    conn = sqlite3.connect(str(k.db))
    _seed(conn)
    yield conn
    conn.close()


def live():
    """The real mined rows, when this machine has them. Absent in CI, which is correct."""
    for name in ("recipes-preview.db", "recipes.db"):
        p = BASE / name
        if not p.exists():
            continue
        c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        has = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                        "AND name IN ('mined_pairings','mined_corpus')").fetchone()[0]
        if has == 2 and c.execute("SELECT COUNT(*) FROM mined_pairings").fetchone()[0]:
            return c
        c.close()
    return None


# ── the load-bearing test ──────────────────────────────────────────────────────────────────────

def test_single_source_lift_is_unchanged():
    """⚠️ THE ONE THAT PROVES N. Recompute every stored lift through the combine path, over one
    source, and demand the stored value back. pairing_run.py computed those 361,138 numbers
    months earlier from its own in-memory N. If mined_corpus holds the wrong N, or the marginals
    are read from the wrong table, this fails.

    ⚠️ THE TOLERANCE IS ABSOLUTE, NOT RELATIVE, and the first draft got that wrong. lift is
    stored to 4 decimal places, so the honest bound is half the last place, 5e-5. A relative
    bound fails on the small lifts for a reason that is pure storage: the pair Q103795986 with
    Q1329680 recomputes to 0.00053865 and is stored as 0.0005, which is 3.9e-5 out and correctly
    rounded, yet reads as 7.7% relative error. An absolute bound still catches everything worth
    catching, because a wrong N is wrong by a factor rather than by a rounding step.
    """
    conn = live()
    if conn is None:
        pytest.skip("no mined corpus on this machine, which is the normal state for a clone")
    rows = MC.pairings(conn, slugs=["recipenlg-2020"], min_n=1)
    stored = {(a, b): (lf, n) for a, b, n, na, nb, lf in
              conn.execute("SELECT a_id,b_id,n,n_a,n_b,lift FROM mined_pairings "
                           "WHERE source_slug='recipenlg-2020'")}
    conn.close()
    assert len(rows) == len(stored), (
        f"the combine returned {len(rows):,} pairs and the table holds {len(stored):,}. A JOIN "
        f"onto mined_occurrences dropped rows, which means a pair references an ingredient with "
        f"no occurrence row.")
    worst, worst_key, exact = 0.0, None, 0
    for a, b, n, n_a, n_b, lift in rows:
        want_lift, want_n = stored[(a, b)]
        assert n == want_n, f"{a}+{b}: combined n {n} against stored {want_n}"
        d = abs(lift - want_lift)
        if d > worst:
            worst, worst_key = d, (a, b, lift, want_lift)
        exact += round(lift, 4) == want_lift
    assert worst <= 5e-5 + 1e-9, (
        f"recomputed lift diverges from stored by {worst:.2e} at {worst_key}, past the 5e-5 that "
        f"4-decimal storage can explain. Either mined_corpus.n is not the N that pairing_run.py "
        f"used, or the marginals are read from the wrong table.")
    assert exact / len(rows) > 0.999, (
        f"only {exact:,} of {len(rows):,} recompute to the stored value under the same rounding")


def test_the_stored_n_is_rederivable_from_the_pairing_rows():
    """⚠️ N IS CHECKED AGAINST THE DATA, NOT AGAINST A NUMBER IN A DOC. Every stored row satisfies
    lift = n * N / (n_a * n_b), so each one implies N = lift * n_a * n_b / n. The median across
    all of them is the corpus size, and it has to match what migration 042 backfilled."""
    conn = live()
    if conn is None:
        pytest.skip("no mined corpus on this machine")
    implied = sorted(lf * na * nb / n for n, na, nb, lf in conn.execute(
        "SELECT n,n_a,n_b,lift FROM mined_pairings WHERE source_slug='recipenlg-2020' "
        "AND lift>0 AND n_a>0 AND n_b>0"))
    stored = MC.corpus_n(conn, ["recipenlg-2020"])
    conn.close()
    median = implied[len(implied) // 2]
    assert abs(median - stored) / stored < 1e-4, (
        f"mined_corpus says {stored:,} and the pairing rows imply {median:,.0f}")


# ── the arithmetic, on hand-calculated numbers ─────────────────────────────────────────────────

def test_lift_is_recomputed_from_summed_counts_never_averaged(synth):
    """alpha + beta. Every wrong method lands somewhere else, which is what makes this a test."""
    [(a, b, n, n_a, n_b, lift)] = MC.pairings(synth, slugs=[ALPHA, BETA])
    assert (a, b, n, n_a, n_b) == ("x", "y", 24, 46, 30)
    want = 24 * 110 / (46 * 30)                      # 1.913043...
    assert lift == pytest.approx(want, rel=1e-9)
    assert lift != pytest.approx((2.0 + 4 * 10 / 30) / 2, rel=1e-3), "a plain mean of two lifts"
    assert lift != pytest.approx((2.0 * 20 + (4 * 10 / 30) * 4) / 24, rel=1e-3), "an n-weighted mean"


def test_the_marginal_comes_from_occurrences_not_from_the_pairing_rows(synth):
    """⚠️ THE SILENT ONE. gamma holds x and y 500 and 400 times and never pairs them. Summing n_a
    off the pairing rows misses gamma entirely and overstates the lift by 170x."""
    [(a, b, n, n_a, n_b, lift)] = MC.pairings(synth)
    assert (n, n_a, n_b) == (24, 546, 430), "gamma's marginals are missing from the combine"
    correct = 24 * 1110 / (546 * 430)                # 0.11346...
    naive = 24 * 1110 / (46 * 30)                    # 19.30, the bug
    assert lift == pytest.approx(correct, rel=1e-9)
    assert naive / correct > 100, "the fixture no longer separates the two methods"


def test_share_is_sum_over_sum_not_a_mean_of_shares(synth):
    """alpha says 90% of d1 carries x, beta says 10%. Combined is 82%, not 50%."""
    got = {(d, l): sh for d, l, n, nd, sh in MC.dish_ingredient(synth, slugs=[ALPHA, BETA])}
    assert got[("d1", "x")] == pytest.approx(82 / 100, rel=1e-9)
    assert got[("d1", "x")] != pytest.approx(0.5, rel=1e-2), "the mean of two shares"


def test_a_source_holding_the_dish_and_not_the_ingredient_stays_in_the_denominator(synth):
    """⚠️ THE SHARE TRAP, one table over from the marginal trap. gamma holds d1 900 times and
    records no ingredient, so the honest combined share is 82/1000 and not 82/100."""
    got = {(d, l): (n, nd, sh) for d, l, n, nd, sh in MC.dish_ingredient(synth)}
    n, n_dish, share = got[("d1", "x")]
    assert (n, n_dish) == (82, 1000), "the denominator came from mined_dish_ingredient.n_dish"
    assert share == pytest.approx(0.082, rel=1e-9)


def test_a_facet_share_uses_the_same_denominator_rule(synth):
    [(d, v, n, n_dish, share)] = MC.facet(synth, "mined_dish_method", slugs=[ALPHA, BETA])
    assert (v, n, n_dish) == ("baked", 50, 100)
    assert share == pytest.approx(0.5, rel=1e-9)


def test_per_recipe_equal_means_no_source_carries_a_weight(synth):
    """A source with 10x the recipes moves the answer 10x as much, and that is the whole
    mechanism. There is no weight column and nothing here reads one."""
    both = MC.pairings(synth, slugs=[ALPHA, BETA])[0]
    just_alpha = MC.pairings(synth, slugs=[ALPHA])[0]
    assert both[2] == just_alpha[2] + 4, "beta's 4 co-occurrences did not count once each"


# ── direction and reversibility ────────────────────────────────────────────────────────────────

def test_adding_a_source_never_shrinks_a_count(synth):
    """⚠️ DIRECTION SANITY. Counts only add. A combined n below the single-source n means rows
    were replaced rather than accumulated, which would be a merge and is forbidden."""
    one = {(a, b): n for a, b, n, *_ in MC.pairings(synth, slugs=[ALPHA])}
    many = {(a, b): n for a, b, n, *_ in MC.pairings(synth)}
    for key, n in one.items():
        assert many[key] >= n, f"{key} fell from {n} to {many[key]} when a source was added"
    occ_one = {i: n for i, n, nr in MC.occurrences(synth, slugs=[ALPHA])}
    for i, n, nr in MC.occurrences(synth):
        assert n >= occ_one.get(i, 0), f"{i} shrank when a source was added"


def test_deleting_a_slug_restores_the_other_source_exactly(tmp_path):
    """⚠️ REVERSIBILITY TESTED, NOT ASSERTED. Build alpha alone, snapshot every mined table.
    Build alpha plus beta plus gamma, delete the two, snapshot again. The two snapshots must be
    identical row for row. This is the claim that a source can be taken back out."""
    d1 = tmp_path / "one"; d1.mkdir()
    k1 = make_kitchen(d1)
    c1 = sqlite3.connect(str(k1.db))
    _seed(c1)
    c1.execute("DELETE FROM mined_corpus WHERE source_slug IN (?,?)", (BETA, GAMMA))
    for t in ("mined_occurrences", "mined_pairings", "mined_dish", "mined_dish_ingredient",
              "mined_dish_method"):
        c1.execute(f"DELETE FROM {t} WHERE source_slug IN (?,?)", (BETA, GAMMA))
    c1.commit()

    d2 = tmp_path / "two"; d2.mkdir()
    k2 = make_kitchen(d2)
    c2 = sqlite3.connect(str(k2.db))
    c2.executemany("INSERT INTO mined_corpus (source_slug, n, mined_at) VALUES (?,?,NULL)",
                   [(ALPHA, 100)])
    c2.executemany(
        "INSERT INTO mined_occurrences (library_id, n, n_recipes, source_slug) VALUES (?,?,?,?)",
        [("x", 40, 40, ALPHA), ("y", 25, 25, ALPHA)])
    c2.execute("INSERT INTO mined_pairings (a_id,b_id,n,n_a,n_b,lift,source_slug) "
               "VALUES ('x','y',20,40,25,2.0,?)", (ALPHA,))
    c2.execute("INSERT INTO mined_dish (dish_id,dish,n,source_slug) VALUES "
               "('d1','test dish',90,?)", (ALPHA,))
    c2.execute("INSERT INTO mined_dish_ingredient (dish_id,library_id,n,n_dish,source_slug) "
               "VALUES ('d1','x',81,90,?)", (ALPHA,))
    c2.execute("INSERT INTO mined_dish_method (dish_id,method,n,source_slug) "
               "VALUES ('d1','baked',45,?)", (ALPHA,))
    c2.commit()

    for t in ("mined_corpus", "mined_occurrences", "mined_pairings", "mined_dish",
              "mined_dish_ingredient", "mined_dish_method"):
        a = sorted(c1.execute(f"SELECT * FROM {t}"))
        b = sorted(c2.execute(f"SELECT * FROM {t}"))
        assert a == b, f"{t} did not come back to the alpha-only state after the delete"
    c1.close(); c2.close()


# ── the guard against guessing N ───────────────────────────────────────────────────────────────

def test_a_missing_corpus_row_raises_rather_than_guessing(synth):
    """⚠️ THE 588x FAILURE, made loud. Without a corpus row the only numbers in reach are the
    occurrence counts, and the largest of them is 43% of the real N. Silence is the bug."""
    synth.execute("DELETE FROM mined_corpus")
    synth.commit()
    with pytest.raises(ValueError, match="N is unknown"):
        MC.corpus_n(synth)
    with pytest.raises(ValueError):
        MC.pairings(synth)


def test_a_source_with_no_corpus_row_is_named(synth):
    with pytest.raises(ValueError, match="wikibooks"):
        MC.corpus_n(synth, [ALPHA, "wikibooks"])


# ── the shape invariants, on whatever rows this machine has ────────────────────────────────────

def test_pairs_are_stored_in_canonical_order_and_never_with_themselves():
    conn = live()
    if conn is None:
        pytest.skip("no mined corpus on this machine")
    bad = conn.execute("SELECT COUNT(*) FROM mined_pairings WHERE a_id >= b_id").fetchone()[0]
    conn.close()
    assert bad == 0, (
        f"{bad:,} rows are out of canonical order or are self-pairs. Both break the combine: "
        f"(a,b) and (b,a) would group separately and sum to half the count each.")


def test_every_loaded_source_has_a_corpus_row():
    """⚠️ A SOURCE WITHOUT AN N CANNOT BE COMBINED. This is the check that will catch a Wikibooks
    load that forgets to register its own corpus size."""
    conn = live()
    if conn is None:
        pytest.skip("no mined corpus on this machine")
    loaded = {r[0] for r in conn.execute("SELECT DISTINCT source_slug FROM mined_pairings")}
    known = {s for s, _ in MC.sources(conn)}
    conn.close()
    assert not (loaded - known), f"loaded with no mined_corpus row: {sorted(loaded - known)}"


# ── the view helpers, which library_viewer reads the whole dish section through ────────────────
#
# ⚠️ THESE GUARD 54 RECIPE PAGES. Before the viewer was wired through them it built a dict keyed
#    on dish_id over a bare SELECT, so the last row scanned won and Wikibooks silently replaced
#    RecipeNLG on all 1,687 shared dishes. `Banana Bread` reported 3 recipes instead of 3,250.
#    The defect was invisible: a plausible small number where a plausible large one belonged.
#    A test that only checked the module's row-returning functions would not have caught it,
#    because the viewer does not call those. It embeds the fragments.


def test_dish_view_returns_one_row_per_dish_summed_over_sources(synth):
    """The shape the viewer pages over. One row per dish, never one per shard."""
    sql, params = MC.dish_view()
    rows = synth.execute(f"SELECT dish_id, dish, n FROM {sql} d ORDER BY n DESC", params).fetchall()
    assert rows == [("d1", "test dish", 1000)], (
        "alpha 90 + beta 10 + gamma 900 is one dish at 1,000, not three rows")
    assert synth.execute("SELECT COUNT(*) FROM mined_dish").fetchone()[0] == 3, (
        "the underlying table must still hold the three shards, unmerged")


def test_dish_view_honors_a_source_filter(synth):
    sql, params = MC.dish_view([ALPHA])
    assert synth.execute(f"SELECT n FROM {sql} d", params).fetchone()[0] == 90
    sql, params = MC.dish_view([ALPHA, BETA])
    assert synth.execute(f"SELECT n FROM {sql} d", params).fetchone()[0] == 100


def test_dish_returns_the_combined_row_and_none_for_a_stranger(synth):
    assert MC.dish(synth, "d1")[2] == 1000
    assert MC.dish(synth, "d1", [BETA])[2] == 10
    assert MC.dish(synth, "no-such-dish") is None


def test_dish_sources_is_the_per_source_breakdown_largest_first(synth):
    """What the dish page prints as `900 gamma + 90 alpha + 10 beta = 1,000`."""
    got = MC.dish_sources(synth, "d1")
    assert [tuple(r) for r in got] == [(GAMMA, 900), (ALPHA, 90), (BETA, 10)]
    assert sum(n for _s, n in got) == MC.dish(synth, "d1")[2], (
        "the breakdown must add up to the combined number it breaks down")


def test_facet_view_groups_a_value_across_sources(synth):
    sql, params = MC.facet_view("mined_dish_method")
    rows = synth.execute(f"SELECT dish_id, method, n FROM {sql} f", params).fetchall()
    assert rows == [("d1", "baked", 50)], "alpha 45 + beta 5 is one row at 50, not two rows"
    with pytest.raises(ValueError):
        MC.facet_view("mined_dish_nonsense")


def test_id_facet_view_groups_a_library_id_facet(tmp_path):
    """base and accompaniment key on library_id rather than a vocabulary word."""
    d = tmp_path / "k"; d.mkdir()
    k = make_kitchen(d)
    conn = sqlite3.connect(str(k.db))
    _seed(conn)
    conn.executemany("INSERT INTO mined_dish_base (dish_id, library_id, n, source_slug) "
                     "VALUES (?,?,?,?)", [("d1", "x", 70, ALPHA), ("d1", "x", 8, BETA)])
    conn.commit()
    sql, params = MC.id_facet_view("mined_dish_base")
    assert conn.execute(f"SELECT dish_id, library_id, n FROM {sql} b",
                        params).fetchall() == [("d1", "x", 78)]
    conn.close()


def test_profile_view_takes_its_denominator_from_the_dish_not_the_stored_n_dish(synth):
    """⚠️ THE SAME TRAP dish_ingredient() AVOIDS, and the viewer reads this one instead.

    gamma holds d1 900 times and records no ingredient. The honest denominator is 1,000.
    mined_dish_ingredient.n_dish would give 100, and every share on the page would be 10x high.
    """
    sql, params = MC.profile_view()
    rows = synth.execute(f"SELECT dish_id, library_id, n, n_dish FROM {sql} i",
                         params).fetchall()
    assert rows == [("d1", "x", 82, 1000)]
    stored = {r[0] for r in synth.execute("SELECT n_dish FROM mined_dish_ingredient")}
    assert stored == {90, 10}, "the per-source n_dish values the view must NOT use"


def test_the_view_helpers_agree_with_the_row_returning_functions(synth):
    """One combine, two doors. The viewer uses the fragments and a script uses the functions,
    and a divergence between them would mean the page and the analysis disagree."""
    sql, params = MC.profile_view()
    via_view = synth.execute(f"SELECT library_id, n, n_dish FROM {sql} i", params).fetchall()
    via_fn = [(r[1], r[2], r[3]) for r in MC.dish_ingredient(synth, dish_id="d1")]
    assert [tuple(r) for r in via_view] == via_fn

    sql, params = MC.facet_view("mined_dish_method")
    v = synth.execute(f"SELECT method, n FROM {sql} f", params).fetchall()
    f = [(r[1], r[2]) for r in MC.facet(synth, "mined_dish_method")]
    assert [tuple(r) for r in v] == f


def test_the_viewer_helpers_reproduce_the_real_combined_chicken():
    """⚠️ THE HAND CALCULATION, ON THE REAL ROWS, THROUGH THE PATH THE PAGE TAKES.

    `chicken` is 10,264 RecipeNLG recipes and 6 Wikibooks ones. The dish page prints 10,270 and
    the per-source line under it prints both halves. Skips on a machine with no corpus.
    """
    conn = live()
    if conn is None:
        pytest.skip("no mined corpus on this machine")
    row = conn.execute("SELECT dish_id FROM mined_dish GROUP BY dish_id "
                       "HAVING COUNT(*) > 1 ORDER BY SUM(n) DESC LIMIT 1").fetchone()
    if row is None:
        conn.close()
        pytest.skip("only one source loaded, so there is no shared dish to check")
    did = row[0]
    per = MC.dish_sources(conn, did)
    combined = MC.dish(conn, did)
    sql, params = MC.dish_view()
    via_view = conn.execute(f"SELECT n FROM {sql} d WHERE d.dish_id = ?",
                            params + [did]).fetchone()[0]
    conn.close()
    hand = sum(n for _s, n in per)
    assert len(per) > 1, "the chosen dish should be held by more than one source"
    assert combined[2] == hand == via_view, (
        f"{combined[1]}: dish() says {combined[2]}, the sources add to {hand}, the view says "
        f"{via_view}. All three are the same number or the page is lying.")
    assert combined[2] > max(n for _s, n in per), "combining must exceed every single source"


def test_a_single_source_dish_reads_the_same_through_every_door():
    """A dish only RecipeNLG holds must be untouched by the combine, which is what makes adding a
    source safe for the 157,841 dishes Wikibooks never mentions."""
    conn = live()
    if conn is None:
        pytest.skip("no mined corpus on this machine")
    row = conn.execute("SELECT dish_id, dish, n FROM mined_dish GROUP BY dish_id "
                       "HAVING COUNT(*) = 1 ORDER BY SUM(n) DESC LIMIT 1").fetchone()
    did, name, n = row
    combined = MC.dish(conn, did)
    per = MC.dish_sources(conn, did)
    conn.close()
    assert combined[2] == n, f"{name} moved from {n} to {combined[2]} with one source holding it"
    assert len(per) == 1
