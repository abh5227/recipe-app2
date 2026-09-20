"""apply_renames decides which of two rows keeps a contested name, and a SWAP is not a MERGE.

The collision check used to compare each new name against a snapshot of the canonicals taken
before any rename was applied, so renaming A off a name so that B could take it read as a merge
and was refused. Measured on live data: the cacao pass renames Q34115776 from 'cacao' to
'cacao tree' and Q45912917 from 'cocoa' to 'cacao'. The first applied and the second was refused
against a name no row would still have been holding.

⚠️ THE REFUSAL ITSELF IS LOAD-BEARING AND MUST NOT WEAKEN. A rename that really would leave two
rows on one name destroys the ability to tell them apart, and linkage_matcher refuses a name held
by two rows outright, so both rows go dark rather than one winning. These four cases pin the line
between the two.
"""
import build_library


def row(anchor, ident, canonical, *also):
    """A row shaped the way apply_renames reads one. `also` are other names sitting on it."""
    return {"anchor": anchor, "id": ident, "canonical": canonical,
            "variations": {n: set() for n in (canonical,) + also}}


def rule(name):
    return {"name": name, "reason": "test", "anchor": "wd", "id": "x"}


def test_a_swap_applies_because_the_name_is_vacated_in_the_same_pass():
    """A gives up 'x' and B takes it. Nothing ends up sharing a name, so both renames stand."""
    a, b = row("wd", "A", "x", "xtree"), row("wd", "B", "y", "x")
    done, refused = build_library.apply_renames(
        [a, b], {("wd", "A"): rule("xtree"), ("wd", "B"): rule("x")})
    assert len(done) == 2 and refused == []
    assert a["canonical"] == "xtree" and b["canonical"] == "x"
    # ⚠️ the vacated name is kept ON the row it left, so a line using it still resolves
    assert "x" in a["variations"]


def test_a_real_merge_is_still_refused():
    """B reaches for 'x' while A keeps it. Two rows would answer to one name."""
    a, b = row("wd", "A", "x"), row("wd", "B", "y", "x")
    done, refused = build_library.apply_renames([a, b], {("wd", "B"): rule("x")})
    assert done == [] and len(refused) == 1
    assert "merge rather than a rename" in refused[0][1]
    assert b["canonical"] == "y"                      # untouched


def test_two_rows_renamed_to_the_same_name_refuses_both():
    """Neither is preferred. A person has to say which row keeps the name."""
    a, b = row("wd", "A", "a", "x"), row("wd", "B", "b", "x")
    done, refused = build_library.apply_renames(
        [a, b], {("wd", "A"): rule("x"), ("wd", "B"): rule("x")})
    assert done == [] and len(refused) == 2
    assert a["canonical"] == "a" and b["canonical"] == "b"


def test_a_name_the_row_does_not_carry_is_refused():
    """A rename takes a name a source already stated, never a new string."""
    a = row("wd", "A", "a")
    done, refused = build_library.apply_renames([a], {("wd", "A"): rule("zzz")})
    assert done == [] and len(refused) == 1
    assert "not a name on the row" in refused[0][1]


def test_a_cut_row_does_not_block_a_rename():
    """Only kept rows own a name. A cut row's canonical is not a claim on it."""
    cut = dict(row("wd", "A", "x"), cut_by="some rule")
    b = row("wd", "B", "y", "x")
    done, refused = build_library.apply_renames([cut, b], {("wd", "B"): rule("x")})
    assert len(done) == 1 and refused == []
    assert b["canonical"] == "x"
