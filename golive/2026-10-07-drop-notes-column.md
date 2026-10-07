# Go-live: the safety round and the time block, together

Two rounds, one deploy. The order is **the code first, then migration 063**, which is the opposite
of the titles round's order and for a stated reason: 063 is DESTRUCTIVE.

> **A migration's order against the deploy follows its direction.** Additive before the deploy,
> destructive after. The question is which of the two versions names something the other side does
> not have. The new code has stopped naming `recipes.notes`, so it serves a database that still has
> the column. The old code still declares it on `Recipe`, so it cannot serve one without it. The
> version that can serve BOTH schemas is the new one, and that is the one that runs in the middle.

Measured both ways on copies, not reasoned out. See section 8a.

## 0. Before anything

```sh
LIVE="$(python3.13 -c 'import sys; sys.path.insert(0,"scripts"); import corpus_guard; print(corpus_guard.live_db())')"
python3.13 backup.py
shasum -a 256 "$LIVE" backups/recipes-*.db | tail -2      # the two must match
git fetch origin && git rev-parse origin/main             # expected: 848094f, the titles round
echo "DATABASE_URL=[${DATABASE_URL-}]"                    # must print [], see below
```

⚠️ **`$DATABASE_URL` MAKES EVERY PATH IN THIS DOCUMENT A LIE, SO IT IS READ BEFORE ANYTHING RUNS.**
`app.orm_session()` prefers that variable over the file it was handed, so a pass named at a copy
reads and writes somewhere else entirely while printing the copy's name. Neither command in step 3
goes through it (`migrate.py` and `add_missed_waits.py` both open the file with `sqlite3.connect`),
which is why this is a check rather than a disaster waiting. It costs one line and the failure it
catches is silent.

Live's sha256 at the end of the rehearsal, 2026-10-07: unchanged all round. Live was opened
`mode=ro` only.

## 1. Prove it on a branch, not on main

```sh
git push origin HEAD:refs/heads/ci/safety-and-time-block
# read the checks step by step (golive/README.md section 2)
# ⚠️ "Run Postgres integration tests" must read success, not skipped
git push origin main
git push origin --delete ci/safety-and-time-block
```

⚠️ **This is the first CI run since `848094f`.** Five commits have never been through it. Two
defects found in review would have taken it red on their own and are fixed in this round: an
assertion on `library_names` that only passes on a machine holding the untracked server-side CSV,
and `tests/pg_harness.py` naming `notes=` in an INSERT against a model that no longer has the
column, which fails at COMPILE time and takes out every test using the `pg` fixture.

## 2. The CODE goes first

```sh
NEW=$(git rev-parse origin/main)
pkill -f scripts/serve_live.py
cd ../recipe-app-serve && git fetch origin && git checkout --detach "$NEW"
npm install && npm run build
nohup python3.13 scripts/serve_live.py > /tmp/serve8000.log 2>&1 & disown
lsof -a -p "$(pgrep -f scripts/serve_live.py | head -1)" -d cwd -Fn   # must name recipe-app-serve
```

**Then stop and look at the app before touching the schema.** The new code is now serving the OLD
schema, which still has the column. Open three recipe pages, save one, and confirm the time block
reads in two columns. This is the step that makes the whole order safe, and skipping it turns a
reasoned claim back into an unverified one.

## 3. The MIGRATION goes second, and the one ruling with it

```sh
cp "$LIVE" "$SP/before.db"                         # copy, never symlink
python3.13 scripts/gates/state.py --db "$SP/before.db" --out "$SP/before.json"

python3.13 migrate.py --db "$LIVE" --i-mean-live   # applies 063 and nothing else
python3.13 scripts/add_missed_waits.py "$LIVE" --apply --i-mean-live

cp "$LIVE" "$SP/after.db"
python3.13 scripts/gates/state.py --db "$SP/after.db" --out "$SP/after.json"
python3.13 scripts/gates/rounds.py --round golive/rounds/2026-10-07-safety-and-time-block.json \
  --before "$SP/before.json" --after "$SP/after.json" \
  --a-db "$SP/before.db" --b-db "$SP/after.db"
```

The gate must print **THE ROUND DID EXACTLY WHAT IT DECLARED**. It did, on the rehearsal copies.

Measured on a 344 MB copy: migration 063 took **0.07 s**.

**The second command is Andy's ruling on all-butter-pie-crust**, `total_includes_waits = 1`,
declared under `rows` in the round file. `scripts/add_missed_waits.py` is the one committed home for
a ruling and its `TOTAL_RULINGS` dict now holds both. Re-running the whole Round A pass is a no-op on
everything else and says so in its own printout:

```
  waits added: 0   (of 13 in the table, 1 deliberately not in it)
    ext_step_id=1779 on beans
    ext_step_id=1874 on brioche-bread
    total_includes_waits=1 on all-butter-pie-crust
    total_includes_waits=0 on miso-tofu-recipe
  SKIPPED: [... 13 x 'already stored' ...]
```

⚠️ **THE RULING CHANGES NO FIGURE ON THE PAGE, AND THAT IS THE POINT.** `recipe_total` shows a
stated total unchanged either way, so all-butter-pie-crust reads "1 hr 15 min" before and after.
What the ruling does is end the question, so the recipe leaves the review list instead of being
asked again on every survey. Rehearsed: the survey then reports `unclear: 0` and writes no list.

## 3b. The check the GATE CANNOT MAKE

⚠️ **`recipes` IS IN `tables.except`, AND AN EXCEPTED TABLE IS NOT COMPARED AT ALL.** It has to be,
because 063 drops a column from it and the comparison would fail on every row. The cost is that the
gate is blind to every OTHER cell of `recipes` for this round, which is exactly the table the ruling
writes to. The exception is a hole, so the hole gets its own check.

```sh
python3.13 - "$SP/before.db" "$SP/after.db" <<'EOF'
import sqlite3, sys
EXPECTED = {("all-butter-pie-crust", "total_includes_waits", None, 1)}
a, b = sys.argv[1], sys.argv[2]
ca = sqlite3.connect(f"file:{a}?mode=ro", uri=True); ca.row_factory = sqlite3.Row
cb = sqlite3.connect(f"file:{b}?mode=ro", uri=True); cb.row_factory = sqlite3.Row
cols_a = [c[1] for c in ca.execute("PRAGMA table_info(recipes)")]
cols_b = [c[1] for c in cb.execute("PRAGMA table_info(recipes)")]
ok = True
if sorted(set(cols_a) - set(cols_b)) != ["notes"] or set(cols_b) - set(cols_a):
    print(f"REFUSING: the columns moved by more than the drop: "
          f"-{sorted(set(cols_a) - set(cols_b))} +{sorted(set(cols_b) - set(cols_a))}"); ok = False
shared = [c for c in cols_a if c in cols_b]
sel = ",".join('"' + c + '"' for c in shared)
ra = {r["id"]: dict(r) for r in ca.execute(f"SELECT {sel} FROM recipes")}
rb = {r["id"]: dict(r) for r in cb.execute(f"SELECT {sel} FROM recipes")}
if set(ra) != set(rb):
    print(f"REFUSING: the recipe id set moved"); ok = False
moved = {(rid, c, ra[rid][c], rb[rid][c])
         for rid in set(ra) & set(rb) for c in shared if ra[rid][c] != rb[rid][c]}
print(f"compared {len(ra)} recipes x {len(shared)} shared columns = {len(ra) * len(shared)} cells")
for m in sorted(moved, key=str):
    print(f"  moved: {m}")
if moved != EXPECTED:
    print(f"REFUSING: that is not the one cell this round declared. "
          f"unexpected={sorted(moved - EXPECTED, key=str)} missing={sorted(EXPECTED - moved, key=str)}")
    ok = False
print("THE ONE DECLARED CELL AND NOTHING ELSE" if ok else "STOP")
sys.exit(0 if ok else 1)
EOF
```

Rehearsed 2026-10-07 on a copy: **300 recipes x 17 shared columns = 5,100 cells compared, 1 moved**,
and `notes` was the only column dropped.

## 4. The ORPHAN PHOTO

One file, named in the round's own declaration and nowhere else:
`static/images/baked-cauliflower-...-copy-copy.jpg`.

⚠️ **THE BACKUP COMES FIRST, AND IT IS NOT THE DATABASE BACKUP.** `backup.py` copies
`recipes.db`. It does not touch `static/images/`, so a deleted photo has no way back from step 0.

```sh
IMG="static/images/baked-cauliflower-with-red-onions-feta-and-dill-firinda-karnabahar-mucveri-copy-copy.jpg"
cp "$IMG" "backups/orphan-$(date +%Y%m%d-%H%M%S)-$(basename "$IMG")"
ls -l backups/orphan-*                                  # the copy exists before anything else
```

Then the three conditions, re-read against live rather than taken from this document. The block
exits non-zero unless all three hold.

```sh
python3.13 - <<'EOF'
import hashlib, pathlib, sqlite3, sys
sys.path.insert(0, "scripts")
import corpus_guard, images
NAME = "baked-cauliflower-with-red-onions-feta-and-dill-firinda-karnabahar-mucveri-copy-copy.jpg"
root = pathlib.Path(images.IMAGES_DIR)
orphan, twin = root / NAME, root / "adventist-gumbo.jpg"
ok = True
if not orphan.is_file():
    print(f"REFUSING: {NAME} is not there to check. If a previous run deleted it, this step is "
          f"already done and the backup is the thing to verify.")
    sys.exit(1)
a, b = (hashlib.sha256(p.read_bytes()).hexdigest() for p in (orphan, twin))
print(f"orphan {a[:16]}…\ntwin   {b[:16]}…")
if a != b:
    print("REFUSING: it is no longer byte-identical to adventist-gumbo.jpg, so it is not the "
          "file this round described"); ok = False
# ⚠️ THE BACKUP IS CHECKED BY ITS BYTES, NOT BY ITS NAME. A glob matches a zero-byte file, which
#    is what an interrupted cp or a full disk leaves behind, and the whole point of this condition
#    is that the photo has a way back.
saved = [q for q in pathlib.Path("backups").glob(f"orphan-*-{NAME}")
         if hashlib.sha256(q.read_bytes()).hexdigest() == a]
print(f"backups holding those exact bytes: {[q.name for q in saved] or 'none'}")
if not saved:
    print("REFUSING: no copy of it in backups/ with matching bytes"); ok = False
con = sqlite3.connect(f"file:{corpus_guard.live_db()}?mode=ro", uri=True)
hits = []
# ⚠️ recipe_snapshots.content IS IN HERE BECAUSE AN IMAGE FILENAME DEMONSTRABLY LIVES THERE.
#    Measured over all 59 tables and every text column of live: 0 rows name the orphan, and
#    adventist-gumbo.jpg is named by cook_photos AND by recipe_snapshots. The condition says "no
#    row names it", so the check reads every place a row can.
for t, c in (("recipes", "image"), ("cook_photos", "path"),
             ("library_sourced_content", "sourced_image"), ("recipe_snapshots", "content")):
    for (v,) in con.execute(f'SELECT "{c}" FROM "{t}" WHERE "{c}" LIKE ?', ("%" + NAME + "%",)):
        hits.append(f"{t}.{c} = {str(v)[:80]!r}")
con.close()
print(f"references: {hits or 'none'}")
if hits:
    print("REFUSING: something names it now"); ok = False
print("ALL THREE HOLD" if ok else "DO NOT DELETE")
sys.exit(0 if ok else 1)
EOF
```

Only on `ALL THREE HOLD`:

```sh
rm "$IMG"
```

⚠️ **THE GATE DOES NOT CHECK THIS, AND THE ROUND FILE SAYS SO.** `scripts/gates/rounds.py` compares
databases, and a photo is a file. The declaration names exactly one path so the record is specific,
and the block above is the check.

## 5. Confirm, and record

- A recipe page, a save, the notes still there, the time block in two columns.
- **earl-grey-tea-cake reads "Total 2 hr 30 min+ (incl. plan ahead)"** with "Author's total: 1 hr,
  before the waits" under it. It is the one recipe of the 300 whose Total this round changes, and
  nothing is written to do it: the figure is computed at display like every other total.
- **all-butter-pie-crust still reads "Total 1 hr 15 min"**, with no "(incl. plan ahead)" and no
  author's line under it. The ruling is meant to change nothing on the page. A figure that MOVED
  here is the sign the wrong value went in.
- The photo is gone and `backups/orphan-*` holds it.
- Live's new sha256, recorded.
- The commit serving :8000.
- A record in `docs/data-repairs/`, in the past tense, **after** the run.

## 6. Rollback

There are two, and which one you need depends on whether 063 has run.

### Before 063: repin, and nothing else

The schema has not moved, so the code rolls back on its own.

```sh
pkill -f scripts/serve_live.py
cd ../recipe-app-serve && git checkout --detach 7d703b7 && npm run build
nohup python3.13 scripts/serve_live.py > /tmp/serve8000.log 2>&1 & disown
```

### After 063: put the column back, THEN repin

⚠️ **REPINNING ALONE IS NOT A ROLLBACK ONCE 063 HAS RUN, AND THE SYMPTOM IS TOTAL.** Measured: live's
own code at `7d703b7`, served against a copy 063 had been applied to, answers

```
GET /                          200
POST /api/login                200
GET /api/recipes               200      <- the home list survives: it names its columns in text() SQL
GET /api/recipes/brioche-bread 500      <- every recipe page, all 300
```

```
app.py:1809 in get_recipe
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such column: recipes.notes
```

`models.py` at `7d703b7` declares `notes = Column(Text)`, so `select(Recipe.__table__)` names it.

**The column comes back EMPTY, and it does not need to come back full.**

```sh
pkill -f scripts/serve_live.py
sqlite3 "$LIVE" 'ALTER TABLE recipes ADD COLUMN notes TEXT;'
cd ../recipe-app-serve && git checkout --detach 7d703b7 && npm run build
nohup python3.13 scripts/serve_live.py > /tmp/serve8000.log 2>&1 & disown
```

Measured: the re-add took **0.003 s** on the 344 MB copy, and the old code then answers 200 on every
recipe page. Section 8c is the proof that an empty column costs the page nothing.

### The ruling needs no rollback, in either direction

`recipes.total_includes_waits` arrived in migration 058, so `7d703b7` reads the column too and reads
it the same way. A 1 on all-butter-pie-crust tells both versions "the author counted the waits", and
both answer by showing the stated total unchanged, which is what both showed before the write. So a
repin leaves it in place and nothing on the page moves. Undo it only if the ruling itself turns out
to be wrong, which is a decision and not a rollback:

```sh
sqlite3 "$LIVE" "UPDATE recipes SET total_includes_waits=NULL WHERE id='all-butter-pie-crust';"
```

⚠️ **A FULL RESTORE FROM THE BACKUP IS THE HEAVIER OPTION AND IT IS NOT THE ONE TO REACH FOR FIRST.**
It is correct, but it discards everything written to live since step 0, and the thing that broke is a
column nothing reads. Re-adding it empty is a 3 ms, lossless repair. Restore from the backup only if
something OTHER than the column is wrong.

## 7. What was rehearsed, and on what

Everything below ran on copies made with `scratchpad/make_copy.py`, which refuses a destination that
is live by resolved path or by device and inode and refuses one outside the session scratchpad.
Three servers, all from pinned worktrees, none of them `:8000` or `:8002`:

| port | code | data |
|---|---|---|
| 8004 | `7d703b7`, live's commit | `sweep.db`, a copy, column populated |
| 8005 | `9d780a8` plus this round | the same `sweep.db` |
| 8006 | `7d703b7` | `rollback063.db`, 063 applied |
| 8007 | `7d703b7` | `rollback063_readded.db`, 063 applied then the column re-added empty |

## 8. What was proven on a copy

### 8a. The deploy order, forwards

The new code against a database that still HAS the column: `:8005` served all 300 recipes.

### 8b. The page outside the time block is live's page, to the pixel

`:8004` against `:8005`, the same copy, 9 recipes at 1400px and at 390px, 18 comparisons. With
`.above-ing` (the time block and the scaler) hidden on BOTH sides, every page matched in height and
**0 pixels differed**, with no tolerance.

⚠️ **HIDDEN, NOT NEUTRALISED, AND THAT IS THE OPPOSITE OF THE LAST ROUND'S CHOICE.** The titles round
changed a colour, so `display: none` would have been wrong: it removes the element from the flow and
everything under it moves. This round changes the block's HEIGHT, so a raw comparison measures the
displacement rather than the content. Hiding the same element on both sides puts what is above it and
what is below it on identical rows.

The block's own height, before to after, at 1400px: brioche-bread 212 to 190, morning-buns 184 to
232, italian-two-bean-soup 77 to 166, coconut-curried-golden-lentils 94 to 166, no-knead-bread 174 to
195, apple-pie 194 to 171, earl-grey-tea-cake 181 to 180, waffle 58 to 171, beans 52 to 126. Every
page's total height moved by that amount and by nothing else, within a pixel of rounding.

### 8c. The rollback loses nothing on the page

`:8004` (column populated) against `:8007` (column re-added empty), same code, 9 recipes at both
widths, nothing hidden: **18 of 18 pixel-identical, 0 pixels differing**.

The only difference anywhere is in the API payload: `recipe.notes` echoes the raw column, `""` or
`null` instead of the stored text, on 111 of the 300. Nothing on the client reads it. The payload's
top-level `notes` key, which is what the page renders, is the `recipe_notes` ROWS and is byte-equal
on all 300.

### 8d. Nothing is lost by the drop

Measured on live, read-only: 300 recipes, 95 carrying note rows, 95 carrying `recipe_notes_original`,
**0 needing a backfill**. 19 of the 95 already had a derived column that no longer agreed with their
rows, which is what a derived copy that nothing re-derives does.

### 8e. The thirteen migration wraps change nothing

A fresh install built from `migrations/` as it stands, and again with every `BEGIN;`/`COMMIT;`
stripped out, compared as a full `iterdump()`. Identical. `tests/test_migration_equivalence.py`.

⚠️ **Live and every other database past these files is untouched by the edit**, because `migrate.py`
tracks by filename and never by checksum. The wrap protects a FRESH INSTALL, which is the only thing
that still runs them.
