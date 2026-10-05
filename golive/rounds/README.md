# Expected changes, one file per round

A go-live declares what it moves, before it moves anything, in a file it commits. The gate then
reads the before and after states and checks them against **that file** and nothing else:

```sh
python3.13 scripts/gates/state.py  --db before.db --out before.json
# ... the round ...
python3.13 scripts/gates/state.py  --db after.db  --out after.json
python3.13 scripts/gates/rounds.py --round golive/rounds/<date>-<name>.json \
                                   --before before.json --after after.json \
                                   --a-db before.db --b-db after.db
```

## Why the declaration is a file and not a block in the script

The gate this replaces kept an `INTENDED` block inside itself, hardcoded to one round's moves. Two
rounds later it was still asserting that migrations should go 59 to 61 and steps 2466 to 2486,
against a database that already had them, so it printed ten failures that were all stale and none
real. A reader learns in one round to ignore a gate like that. With the declaration in a committed
file the script has nothing of its own to go out of date, and each round's claim stays on the record
next to the commit that made it.

## Every key is required

`round`, `why`, `short_circuit`, `annotations`, `counts` and `tables`. A round that leaves one out is
refused rather than defaulted, because the failure this whole mechanism guards against is a check
that passes for lack of a question. **"Nothing moves" is a declaration, not a default:** say
`"short_circuit": "unchanged"`, `"tables": "identical"`, `"counts": {}`.

A missing round file fails too. A go-live with no declaration is not a go-live with an empty one.

`counts` names only what moves, as `[from, to]`. A count that moves and is not named fails, and a
count named that does not move fails the same way, so the round has to know what it is doing in both
directions.
