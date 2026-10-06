# The demo data, where it came from and how it left

A record, not a decision file. Nothing reads it. It exists because the rows it describes carried the
owner's own user id, so without this the next person to look would read them as his work.

## What was in the database

Two ad hoc seeding runs wrote a demo social layer into live while the feed was being built. Neither
script was ever committed, and neither survives: both were run from a session scratchpad under
`/private/tmp`, which macOS clears. `git log --all -S` finds no trace of "Alex Rivera", "Mira Chen",
`alex@demo.test` or any of the captions, so nothing in the repo can produce these rows again.

What gives each run away is one wall-clock minute and second stamped on every row it wrote.

| run | stamp | when | wrote |
|---|---|---|---|
| 1 | `30:45` | 2026-07-25 17:30:45 UTC | `shared_posts` 1, 2, 3 and 4, `cook_log` 209 and 210 (`demo-2b`), the friendship 2 to 1 |
| 2 | `16:26` | 2026-07-26 17:16:26 UTC | `shared_posts` 6 to 11, `comments` 1 to 5, `cook_log` 211 to 215 (`demo-seed`), the friendships 1 to 3 and 4 to 1, and the accounts `alex@demo.test` and `mira@demo.test` |

Run 2's instant is pinned by a round number. Both demo accounts carry a `created_at` of
2026-06-26 17:16:26, which is exactly 30 days before it, so the script backdated them to make the
accounts look established. Run 1 came first, which the autoincrement ids settle: `cook_log` 209 and
210 precede 211 to 215, and `shared_posts` 1 to 4 precede 6 to 11.

By the commit timeline, run 1 was made at `fd70404` (the deliberate-share feed backend, sub-stage
2a) and run 2 at `f4d1f5c`.

`test@test.com` was **not** one of these. Invite `PUDlfxJA…` was created at
2026-07-24 04:11:14 and consumed at 04:17:58, which is that account's `created_at` to the second.
Two distinct seconds, seven minutes apart, is a person signing up through the real flow.

## What was removed, and when

**2026-10-05, `scripts/remove_demo_accounts.py`**, round file
`golive/rounds/2026-10-05-remove-demo-accounts.json`. The three extra accounts and the rows they
owned: `users` 4 to 1, `cook_log` 137 to 133, `comments` 5 to 1, `friendships` 3 to 0,
`shared_posts` 10 to 3, `invites` 1 to 0. One of the comments taken was the owner's own, removed by
the `comments.post_id` cascade when a demo account's post went, and the dry run named it before it
happened.

**2026-10-05, `scripts/remove_demo_rows.py`**, round file
`golive/rounds/2026-10-05-remove-demo-rows.json`. The 7 rows the first pass left, because they carry
the owner's user id rather than a demo account's: `shared_posts` 2, 8 and 9, `comments` 3, and
`cook_log` 211, 212 and 213. Measured on live: `shared_posts` 3 to 0, `comments` 1 to 0, `cook_log`
133 to 130, every other table identical row for row, the short-circuit set 280 of 300 unchanged, the
49 annotation entries over 20 recipes unchanged entry by entry, integrity ok and 0 foreign-key
violations. Live went from `90256dc0…0998` to `41459596…6387`.

After it, `cook_log` carries only `app` 14, `paprika-import` 9 and `rating-inferred` 107, so no
`demo-*` source is left anywhere, and the 300 recipes, 177 notes, 135 cook photos, 120 ratings and
132 queue entries are untouched.

⚠️ **This paragraph was written in the past tense before the pass had run, and a review caught it.**
A record is what a future reader trusts, so committing one ahead of its run makes the repo assert a
change to live that might never happen. The commit before the apply carried it as the plan, and this
is the correction. `golive/README.md` now states the rule.

The three cooks carried source `demo-seed`, no rating, no caption and no photo, so no outcome data
was inside them. That clause is a refusal in the script rather than a note here, because `edit_cook`
writes a rating onto an existing row and never rewrites `source`, so a demo-seeded cook somebody
later rated would be machine-made by its source and a person's own work by its content.

Each pass ran against the round gate, which held it to exactly the counts it declared and required
every other table to be identical row for row, the short-circuit set to stay at 280 of 300 and the
49 annotation entries over 20 recipes to stay identical entry by entry. Both printed THE ROUND DID
EXACTLY WHAT IT DECLARED. The backups taken immediately before each are
`backups/recipes-20261005-193914.db` for the accounts and `backups/recipes-20261005-214743.db` for
the rows, both verified byte-identical to live at the time.

⚠️ **The second pass also proved its own claim rather than asserting it.** A review found that the
deletion order protected only the rows the script names, and that `recipe_snapshots.cook_log_id` is
`ON DELETE CASCADE` with a snapshot written for every logged cook, so a cascade could have taken a
row silently with 7 printed and exit 0. It now reads the cascade children out of the schema, refuses
if anything unnamed points at the 7, and compares every table's row count before the commit.
Measured on live: 0 unnamed dependents, and `recipe_snapshots` held at 306 across the run.

## What looked machine-made and is not

Worth stating, because the sweep that found the 7 also found these and a later reader will find them
again. Each is the owner's own data, written in a batch by a recorded pass over it.

| rows | one instant | the pass |
|---|---|---|
| `recipe_queue` 132 | 2026-07-27 17:11:31 | `scripts/applied/backfill_recipe_queue.py`, promoting the Paprika "To Make" tag |
| `cook_log` 9 `paprika-import` | from each recipe's Paprika date | `scripts/applied/seed_made_cooks.py`, from the Paprika "Made" tag |
| `recipes` 300, `recipe_snapshots` 306, `ratings` 120, `import_flags` 33 | 2026-07-01 21:29:10 and 21:29:11 | the Paprika import |
| `cook_log` 107 `rating-inferred` | derived at import | the same import, from those ratings |
| `cook_photos` 120 | 2026-08-05 05:01:18 | the photo import |
| `recipe_notes_original` 177 | 03:11:44 | `scripts/notes_to_rows.py`, the notes round |

## Why the feed looked empty the whole time

`GET /api/feed` is bounded to 14 days by design. The three remaining posts were 72 to 75 days old
and left the window on 2026-08-05 and 2026-08-08, so the page read "Nothing shared yet" while the
rows were still there. That is the feed working, and it is also why the rows sat unnoticed for two
months.
