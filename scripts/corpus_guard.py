#!/usr/bin/env python3.13
"""The one live guard every corpus pass shares.

⚠️ ONE RULE, ONE COPY, FOUR CALLERS. It lived in four places: three verbatim copies of
`refuse_live` and a fourth inlined in `apply_plan_ahead_proposals.main()`. That is the shape this
round spent its length fixing everywhere else (`move_link_out_of_label` was the one that got away),
and it is a poor shape for the single rule the whole safety story rests on.

⚠️ AND THE TEST THAT COVERS IT MUST NOT CALL `main()`. The first version of that test set
`sys.argv` to the live database path and called `main()`, so the guard was the only thing between an
ordinary `pytest` run and a real migration of the 300-recipe live database. For
`apply_plan_ahead_proposals`, which wrote by default, there was not even an `--apply` to withhold.
`refuse_live` is a pure function and the test calls it directly.
"""
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent


def refuse_live(db, i_mean_live, base=None):
    """Exit unless the caller said `--i-mean-live`, when `db` is the live database.

    Live is `recipes.db` in the repo root and nothing else. A copy under any other name or in any
    other directory passes straight through, which is what every rehearsal relies on.
    """
    root = pathlib.Path(base or BASE).resolve()
    if pathlib.Path(db).resolve() == (root / "recipes.db"):
        if not i_mean_live:
            sys.exit("refusing to write live recipes.db without --i-mean-live")
