#!/usr/bin/env python3
"""mined_combine.py - read many mined sources as one, without writing anything.

⚠️ THE COMBINE IS A READ, NOT A MERGE. Every mined table already carries source_slug in its
primary key, so a second corpus adds rows beside the first rather than overwriting it. Nothing
here writes. Deleting one source's rows returns every table to exactly what the other source
loaded, which is what makes a source reversible per slug.

⚠️ LIFT IS RECOMPUTED FROM SUMMED MARGINALS. IT IS NEVER AVERAGED. Two stored lifts of 3.0 and
9.0 do not combine to 6.0, and a weighted mean of them is wrong too. lift is a ratio of counts,
so the counts add and the ratio is taken once at the end:

    lift = (SUM(n_ab) * SUM(N)) / (SUM(n_a) * SUM(n_b))

Averaging the stored values instead gives a number that looks reasonable and is not a lift of
anything.

⚠️ THE MARGINALS COME FROM mined_occurrences, NOT FROM THE PAIRING ROWS, and the difference is a
silent corruption rather than a rounding question. mined_pairings.n_a is the per-source marginal
for that source, so SUM(n_a) grouped over a pair sums only the sources where THAT PAIR occurs. A
source holding 4,000 recipes with garlic and no recipe pairing garlic with saffron contributes
nothing to that group, so garlic's combined marginal comes out 4,000 short and the lift comes out
too high. Measured on the current copy: 2,992 ingredients occur, 2,983 of them ever pair, so the
gap is real even inside one source. The marginal is a property of the ingredient and is read from
the table that holds ingredients.

The same trap, one table over: a dish's denominator is mined_dish.n, not
mined_dish_ingredient.n_dish, for exactly the reason above. Verified equal per source on the
current copy across all 152,454 (dish, source) rows, which is what makes swapping in the correct
one safe.

⚠️ PER-RECIPE EQUAL. A recipe counts once wherever it came from. No source carries a weight, and
there is no mechanism here to give it one. Summing raw counts is what implements that, so the
decision needs no code.

⚠️ SHARE IS SUM(n) / SUM(n_dish), NEVER A MEAN OF TWO SHARES. n_dish is a per-source denominator.
A dish with 900 recipes in one source at 90% and 100 in another at 10% is 82% combined, not 50%.
"""

__all__ = ["corpus_n", "sources", "pairings", "occurrences", "dish_ingredient", "facet",
           "FACET_TABLES", "dish_view", "facet_view", "id_facet_view", "profile_view",
           "dish", "dish_sources"]

# table -> its value column. The facets that key on a vocabulary word rather than a library row.
FACET_TABLES = {
    "mined_dish_form": "dish_type",
    "mined_dish_method": "method",
    "mined_dish_diet": "diet",
    "mined_dish_structural": "structural",
    "mined_dish_appliance": "appliance",
    "mined_dish_cuisine": "cuisine",
    "mined_dish_course": "course",
}


def _filter(slugs, col="source_slug"):
    """Return (sql_fragment, params). An empty or absent list means every source."""
    if not slugs:
        return "", []
    marks = ",".join("?" * len(slugs))
    return f" WHERE {col} IN ({marks})", list(slugs)


def sources(conn):
    """Every source_slug that has a corpus row, with its recipe count."""
    return [(r[0], r[1]) for r in
            conn.execute("SELECT source_slug, n FROM mined_corpus ORDER BY n DESC")]


def corpus_n(conn, slugs=None):
    """N, the recipes behind the combined view.

    ⚠️ RAISES RATHER THAN GUESSING. A missing corpus row is the failure this module exists to
    stop, and returning 0 or falling back to MAX(n_recipes) would hide it behind a plausible
    number. mined_occurrences' largest row is salt at 960,395, which is 43% of the real corpus.
    """
    where, params = _filter(slugs)
    total, have = conn.execute(
        f"SELECT SUM(n), COUNT(*) FROM mined_corpus{where}", params).fetchone()
    if not have:
        raise ValueError(
            "mined_corpus holds no row for " + (", ".join(slugs) if slugs else "any source") +
            ". N is unknown, so no lift can be computed. Run migration 042 and load the source.")
    if slugs and have != len(set(slugs)):
        found = {r[0] for r in conn.execute("SELECT source_slug FROM mined_corpus")}
        raise ValueError(f"no mined_corpus row for {sorted(set(slugs) - found)}")
    return int(total)


def pairings(conn, slugs=None, min_n=1, ids=None, limit=None):
    """Combined co-occurrence with lift recomputed over summed marginals.

    Yields (a_id, b_id, n, n_a, n_b, lift). With one source loaded the lift returned equals the
    stored lift, which is the invariant that proves the formula and N before a second source
    exists. See tests/test_mined_combine.py.
    """
    N = corpus_n(conn, slugs)
    where, params = _filter(slugs, "p.source_slug")
    ow, oparams = _filter(slugs)
    clauses = [where[7:]] if where else []
    if ids:
        marks = ",".join("?" * len(ids))
        clauses.append(f"(p.a_id IN ({marks}) OR p.b_id IN ({marks}))")
        params = params + list(ids) + list(ids)
    body = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT p.a_id, p.b_id, SUM(p.n) AS n, oa.n_a, ob.n_b,
               (SUM(p.n) * {N}.0) / (oa.n_a * 1.0 * ob.n_b) AS lift
          FROM mined_pairings p
          JOIN (SELECT library_id, SUM(n_recipes) AS n_a
                  FROM mined_occurrences{ow} GROUP BY library_id) oa ON oa.library_id = p.a_id
          JOIN (SELECT library_id, SUM(n_recipes) AS n_b
                  FROM mined_occurrences{ow} GROUP BY library_id) ob ON ob.library_id = p.b_id
         {body}
         GROUP BY p.a_id, p.b_id
        HAVING SUM(p.n) >= ?
         ORDER BY lift DESC
    """ + (f" LIMIT {int(limit)}" if limit else "")
    return conn.execute(sql, oparams + oparams + params + [min_n]).fetchall()


def occurrences(conn, slugs=None):
    """Combined per-ingredient counts. (library_id, n, n_recipes)."""
    where, params = _filter(slugs)
    return conn.execute(
        f"SELECT library_id, SUM(n), SUM(n_recipes) FROM mined_occurrences{where} "
        f"GROUP BY library_id ORDER BY 3 DESC", params).fetchall()


def dish_ingredient(conn, dish_id=None, slugs=None):
    """Combined dish profile. (dish_id, library_id, n, n_dish, share).

    ⚠️ n_dish comes from mined_dish, so a source that holds the dish and not the ingredient still
    counts in the denominator. Taking it from mined_dish_ingredient.n_dish instead would silently
    inflate every share on a dish that two sources disagree about.
    """
    where, params = _filter(slugs)
    dw, dparams = _filter(slugs, "i.source_slug")
    clauses = [dw[7:]] if dw else []
    if dish_id:
        clauses.append("i.dish_id = ?")
        dparams = dparams + [dish_id]
    body = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return conn.execute(f"""
        SELECT i.dish_id, i.library_id, SUM(i.n) AS n, d.n_dish,
               SUM(i.n) * 1.0 / d.n_dish AS share
          FROM mined_dish_ingredient i
          JOIN (SELECT dish_id, SUM(n) AS n_dish FROM mined_dish{where} GROUP BY dish_id) d
            ON d.dish_id = i.dish_id
         {body}
         GROUP BY i.dish_id, i.library_id
         ORDER BY share DESC
    """, params + dparams).fetchall()


def facet(conn, table, dish_id=None, slugs=None):
    """Combined facet counts for any of FACET_TABLES. (dish_id, value, n, n_dish, share)."""
    if table not in FACET_TABLES:
        raise ValueError(f"{table} is not a facet table. Known: {sorted(FACET_TABLES)}")
    col = FACET_TABLES[table]
    where, params = _filter(slugs)
    fw, fparams = _filter(slugs, "f.source_slug")
    clauses = [fw[7:]] if fw else []
    if dish_id:
        clauses.append("f.dish_id = ?")
        fparams = fparams + [dish_id]
    body = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return conn.execute(f"""
        SELECT f.dish_id, f.{col}, SUM(f.n) AS n, d.n_dish,
               SUM(f.n) * 1.0 / d.n_dish AS share
          FROM {table} f
          JOIN (SELECT dish_id, SUM(n) AS n_dish FROM mined_dish{where} GROUP BY dish_id) d
            ON d.dish_id = f.dish_id
         {body}
         GROUP BY f.dish_id, f.{col}
         ORDER BY n DESC
    """, params + fparams).fetchall()


# ── views, for a caller that has to filter, sort and page in SQL ───────────────────────────────
#
# ⚠️ WHY A SQL FRAGMENT AND NOT A LIST OF ROWS. library_viewer pages a 159,528-row dish list 60 at
#    a time and filters it on the way. Returning every combined row so the caller can slice it
#    would materialize the whole table on every request. Returning the fragment lets the caller
#    put WHERE, ORDER BY and LIMIT on top while the SUM still happens in exactly one place, which
#    is the point: nothing outside this module writes a SUM over a mined table.
#
# ⚠️ MIN(dish) IS SAFE AND NOT A GUESS. dish_id is sha256(dish)[:16], so two rows sharing a
#    dish_id share the string by construction. Checked on the loaded copy: 0 dish_ids carry more
#    than one spelling.


def dish_view(slugs=None):
    """(sql, params) for the combined dish list as a subquery. Columns: dish_id, dish, n."""
    where, params = _filter(slugs)
    return (f"(SELECT dish_id, MIN(dish) AS dish, SUM(n) AS n FROM mined_dish{where} "
            f"GROUP BY dish_id)", params)


def facet_view(table, slugs=None):
    """(sql, params) for one combined facet as a subquery. Columns: dish_id, <value col>, n."""
    if table not in FACET_TABLES:
        raise ValueError(f"{table} is not a facet table. Known: {sorted(FACET_TABLES)}")
    col = FACET_TABLES[table]
    where, params = _filter(slugs)
    return (f"(SELECT dish_id, {col}, SUM(n) AS n FROM {table}{where} "
            f"GROUP BY dish_id, {col})", params)


def id_facet_view(table, slugs=None):
    """(sql, params) for a facet keyed on library_id: base, accompaniment."""
    where, params = _filter(slugs)
    return (f"(SELECT dish_id, library_id, SUM(n) AS n FROM {table}{where} "
            f"GROUP BY dish_id, library_id)", params)


def profile_view(slugs=None):
    """(sql, params) for the combined dish profile. Columns: dish_id, library_id, n, n_dish.

    ⚠️ n_dish COMES FROM mined_dish, NOT FROM mined_dish_ingredient.n_dish, the same rule
    dish_ingredient() follows. A source holding the dish and not the ingredient belongs in the
    denominator, and taking the stored per-source n_dish would leave it out.
    """
    where, params = _filter(slugs)
    dv, dp = dish_view(slugs)
    return (f"(SELECT i.dish_id, i.library_id, SUM(i.n) AS n, d.n AS n_dish "
            f"FROM mined_dish_ingredient i{where} JOIN {dv} d ON d.dish_id = i.dish_id "
            f"GROUP BY i.dish_id, i.library_id)", params + dp)


def dish(conn, dish_id, slugs=None):
    """One combined dish. (dish_id, dish, n), or None."""
    sql, params = dish_view(slugs)
    return conn.execute(f"SELECT dish_id, dish, n FROM {sql} d WHERE d.dish_id = ?",
                        params + [dish_id]).fetchone()


def dish_sources(conn, dish_id):
    """What each source contributed to one dish. [(source_slug, n)], largest first.

    This is the accumulation made visible: `chicken` is 10,264 from RecipeNLG and 6 from
    Wikibooks, and a combined 10,270 that says neither is the whole story.
    """
    return conn.execute("SELECT source_slug, n FROM mined_dish WHERE dish_id = ? "
                        "ORDER BY n DESC", (dish_id,)).fetchall()
