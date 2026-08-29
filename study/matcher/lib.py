"""The FULL build() pipeline order, kept in step with build_library.build()."""
import collections, sqlite3
def rowset(BL, rule4=False):
    join=sqlite3.connect("file:join.db?mode=ro",uri=True)
    src=sqlite3.connect("file:sources.db?mode=ro",uri=True); src.execute("PRAGMA query_only=ON")
    kinds,sup,tree=BL.load_vocab(); off_parents=BL.off_tree(src)
    rows,_,be,bb=BL.build_rows(join,src,kinds,sup,off_parents)
    subs=collections.Counter()
    for ps in sup.values():
        for p in ps: subs[p]+=1
    rows=BL.add_overrides(rows,be,bb,kinds,subs)
    try:    rows=BL.add_authored(rows,BL.load_authored()[0],subs,be,bb)
    except TypeError: rows=BL.add_authored(rows,BL.load_authored()[0],subs)
    rows,_=BL.apply_removals(rows,BL.load_removals()[0])
    try: BL.apply_renames(rows, BL.load_renames()[0])
    except AttributeError: pass
    BL.strip_as_food(rows)
    BL.drop_initialism_expansions(rows,be)
    try: BL.drop_dead_language_names(rows, BL.load_dead_languages())
    except AttributeError: pass
    try: BL.drop_agrovoc_symbols(rows, be)
    except AttributeError: pass
    moved=BL.resolve_borrowed(rows,sup,off_parents)
    rows=BL.annotate(rows,sup,off_parents)
    BL.mark_strength(rows)
    rows=BL.annotate(rows,sup,off_parents)
    return rows, moved
def labels():
    db=sqlite3.connect("file:recipes.db?mode=ro",uri=True); db.execute("PRAGMA query_only=ON")
    from build_join import norm_name as n
    L=collections.Counter()
    for (l,) in db.execute("SELECT label FROM recipe_ingredients WHERE is_heading=0 "
                           "AND label IS NOT NULL AND TRIM(label)<>''"): L[n(l)]+=1
    return L
