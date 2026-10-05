# The gates

Three read-only tools for checking that a change did what it said and nothing else. They were
written for the corpus passes and the notes go-live, lived in a session scratchpad under `/private/tmp`
through both, and are in the repo now so the next round can reach them from a fresh clone.

Nothing here writes to a database. Every connection goes through `state.open_ro`, which spells
`file:<path>?mode=ro`, so SQLite refuses a write rather than these files promising not to make one.
That is why they are on the read-only list in `tests/test_live_guards.py` rather than wiring
`--i-mean-live`: reading live's state **is** the job, and a gate that needed a sentence typed out
would not get run.

## The three

| | what it answers |
|---|---|
| `state.py` | what one database's byte-equal set, annotation set and row counts are, right now |
| `compare.py` | whether two `state.py` readings are identical, as SETS |
| `tablediff.py` | which tables of two databases disagree, row for row, column for column |

## The usual run

Read the state before, make the change, read it after, compare the two readings.

```sh
python3.13 scripts/gates/state.py   --db /tmp/copy.db --out before.json
# ... the pass, the deploy, the spot-check ...
python3.13 scripts/gates/state.py   --db /tmp/copy.db --out after.json
python3.13 scripts/gates/compare.py before.json after.json      # exit 0 means identical
```

When `compare.py` reports a difference and you need to know which rows moved:

```sh
python3.13 scripts/gates/tablediff.py /tmp/before-copy.db /tmp/after-copy.db
```

## The two rules worth knowing before you trust a result

**A gate compares the two readings of the same run, never a fixed number.** "short-circuit 275 of
300" was quoted as a gate figure for a whole round, and it is not a property of the corpus. It is a
property of which recipes have been saved. One spot-check save took it to 274 with no annotation
entry and nothing visible on the page. Read it before, read it after, compare the two.

**And it compares the entries, not their count.** One recipe leaving the byte-equal set while
another joins holds the number still. One annotation entry replacing another holds 49 at 49. Both
are compared entry by entry.

## A reading with nothing in it fails

`compare.py` refuses a reading that has no recipes, no byte-equal set or no annotation entries,
before it reports any comparison. Two empty readings are byte-identical and mean nothing, and a
reading taken against the wrong path is empty rather than wrong-looking. This is the one behaviour
most worth not losing, so `tests/test_gates.py` pins it from both sides, including the case where
both sides are empty and therefore agree.

## What `state.py` does not do

It does not serialize a recipe itself. It calls `snapshot_serialize.content_blob`, the same function
the app writes snapshots with. The scratchpad version projected the fields on its own and drifted the
moment notes left the blob: the copy still emitted `notes`, so every recipe differed from its
baseline and the gate would have passed while comparing nothing.

There is no `--old-serializer` flag. The scratchpad version had one, to put `notes` back in the blob
while the notes round was in flight. Implementing it now would mean a second serializer beside
`content_blob`, which is the duplication above, and all 300 stored baselines were stripped in
lockstep when the round shipped, so there is nothing left to read the old way.
