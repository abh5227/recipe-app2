# Reconciliation, August 2026

A full read of the repository against its own documentation, subsystem by subsystem, producing one
grounded change-list. Every entry below ties to a file and a line checked against the code, not
against a summary of it.

**This document catalogs. It changes nothing.** No divergence recorded here is corrected by this
commit.

## Why it was done

Three sessions of planning were built on a model the schema does not implement. The cost was not a
bug. It was that a design document described the `ingredients` table as having a SHARED tier opposed
to a PERSONAL tier, and every plan written afterwards inherited that shape. Finding out cost more
than fixing it will.

## Method

Ten subsystems plus one gap-closing pass, read in this order:

1. ingredient / library data model
2. library construction
3. the matcher / linkage
4. recipe import
5. recipes / cooking / snapshots
6. auth / users / social
7. photos / images
8. the frontend
9. build / migrations / CI / deploy
10. process docs
10b. `docs/design-decisions.md`, the last unread surface

Surface covered: 285 tracked files, 19.5 MB, plus 6.07 GB of gitignored inputs. Roughly 900 Python
tests and 139 JS tests. 42 app routes plus 6 auth routes. 20 tables. 31 SQLite migrations and 16
Alembic revisions.

---

# 1. The headline finding

**The code is sound. The vision was right. One document misread one correct word.**

`docs/product-vision.md:60` says:

> The **ingredient library stays SHARED / app-global** — the `[[key|label]]` linking vocabulary
> everyone draws on. It is NOT boxed or owned.

Read in context that is **correct and still correct**. "Shared" there contrasts with **boxed**, which
is the recipe-box model's word for per-user ownership. It means one library everyone links against.

`docs/panel-design.md` inherited the word and gave it a second meaning: a **tier inside the
`ingredients` table**, opposed to a personal tier. That tier does not exist and never did.

**The corrected reading is one substitution.** `owner IS NULL` does not mean "shared". It means
**"a library row"**. The predicate is identical, the mechanism is untouched, and the privacy gate
built on it is correct as written.

## The blast radius is bounded, and here it is in full

| where | measured |
| --- | --- |
| `docs/panel-design.md` | 45 occurrences of the word, most in the phantom sense |
| `migrations/031_ingredient_identity.sql` | 7 |
| `alembic/versions/f2a3b4c5d6e7_…py` | 4 |
| `models.py` | lines 86, 93 |
| `app.py` | lines 336, 339, 1098 |
| `build_db.py` | lines 135, 138 |
| `tests/pg_harness.py` | line 109 |
| test names | 5 (listed in A6) |
| the index name `idx_ingredients_shared_concept` | 8 sites, 1 of them schema |

**Nowhere else.** `docs/design-decisions.md` (1,645 lines, 25 hits) carries **zero** instances of the
phantom sense. Neither does `OVERVIEW.md`, `CLAUDE.md`, `README.md`, `SECURITY.md`, the whole import
pipeline, the whole library builder, the matcher, or the client.

## The dominant defect is the opposite of over-claiming

**Six separate places describe shipped work as unbuilt.** `panel-design.md` is the only document that
claimed more than exists, and only about the model. Everything else claims less:

- recipe write-ownership, recorded as an open gap in **two** documents, closed at 7 sites
- upload endpoints, called absent in **two** documents, 6 routes exist
- change-tracking, called "NOT built", 298 snapshots and a consumed diff
- the matcher, called homeless, committed in `b42dd14`

---

# 2. The consolidated change-list

## ⚠️ Status, annotated as entries land

**Everything below this block is as written at `08857c9`, annotated in place.** No entry has been
deleted or reworded.

| pass | commit | entries closed |
| --- | --- | --- |
| Phase 4, the authoritative model doc | `bf80ee4` | A10, A11 |
| D1, the seed-rebuild claim | `7ae120b` | D1 |
| the mechanical nine | `f09fbff` | C1, C2, C4, C9, C11, E2, E3, E4, E7 |
| the A+B safe batch, plus the coupled models.py block | `f0f01e4` | A1, A2, A3, A4, A5, A6, A7, C5, C6, C7, B1, B2, B3, B4 |
| substitutions: drop "manual", symbolize the living refs | `86671ee` | C3, F1, F2, F3 |
| the descriptive-text half, LAST cleanup pass | this commit | B5, B6, C8, and the identity test's module docstring |

## The F policy, decided

**Symbolize `file:line` refs in LIVING docs. Leave them in DATED or SUPERSEDED docs**, where the date or
the supersede header is already the disclaimer. F1, F2 and F3 are converted to symbol references. F4 and
F5 sit in a dated survey and F6 and F7 sit in a superseded document, so all four are **WONTFIX**.

⚠️ **F7 is the evidence for the policy, and we produced it ourselves.** The change-list recorded F7's six
`app.py` citations as "all still correct". The one-line comment edit in `f0f01e4` shifted every one of them
by one. `app.py:1169` is the worst of them, because it still lands on a plausible 404 return, so a reader
would not notice it is the wrong one. **A line number went stale inside the very pass that was cataloguing
stale line numbers.**

## ✅ The cleanup is COMPLETE

**Every actionable entry is DONE, WONTFIX-with-a-reason, or OPEN-with-a-stated-reason.** Counted at this
commit over all 63 numbered entries:

| state | n | |
| --- | --- | --- |
| ✅ **DONE** | 36 | fixed and tagged with the commit that did it |
| 🛑 **WONTFIX** | 7 | A8, A9, C10, F4, F5, F6, F7, each with the reason on its row |
| 🛑 **WITHDRAWN** | 1 | E6, a false finding |
| ⏸️ **OPEN** | 9 | D2, D3, D4, D5, E1, E5, E8, E9, E10, each carrying why |
| not actionable | 10 | all of **G**, data-shape anomalies rather than doc defects, and all of **H**, which says in as many words "do not act on these" |

**Nothing is silently unaddressed.** The nine OPEN entries fall into three kinds. **D2** is the one live
wording call, cook-gating across `CLAUDE.md:13` and `ROADMAP.md:689`. **D3, D4 and D5** are largely moot,
since `panel-design.md` is superseded and `ingredient-model.md` settles the vocabulary. **E1, E5, E8, E9
and E10** each need something a doc pass cannot supply: the gitignored library, a live suite run, the real
generator, a seven-site comment sweep, or a decision about where new prose belongs.

⚠️ **Two entries turned out to be unactionable as written**, and are marked below rather than removed.
**E6 is WITHDRAWN as a false finding.** **C10's quoted phrase is not findable anywhere in the repo.**

⚠️ **Every `docs/panel-design.md` line number in this document is now off by 31.** The supersede header
added by `bf80ee4` sits at the top of that file, so F6's `:547` reads `:578` today. F7's citations point
into `app.py` and `build_db.py` and are unaffected.

## A. The phantom "shared tier"

The corrected word throughout is **library**. `owner IS NULL` = a library row. `owner` set = one
user's private row.

| # | file:line | what it says | risk |
| --- | --- | --- | --- |
| A1 | ✅ **DONE (`f0f01e4`).** `models.py:93` | `# NULL = shared, else the owner` | code comment |
| A2 | ✅ **DONE (`f0f01e4`).** `models.py:86` | "`owner` NULL means shared" | code comment |
| A3 | ✅ **DONE (`f0f01e4`).** ⚠️ TWO sites, not one: the gate comment AND `get_ingredient`'s docstring at `:1076`. `app.py:1098` | `# shared, readable by everyone` | code comment |
| A4 | ✅ **DONE (`f0f01e4`).** `app.py:336,339` | "ONE shared row at any concept", "the shared marker" | code comment |
| A5 | ✅ **DONE (`f0f01e4`).** `build_db.py:135,138` | same two phrases | code comment |
| A6 | ✅ **DONE (`f0f01e4`).** `:106`'s index name deliberately left. `tests/pg_harness.py:109` | "the shared marker" | code comment |
| A7 | ✅ **DONE (`f0f01e4`).** Five renamed, plus 7 further tier-sense comments and docstrings inside the two files. Zero tier-sense hits remain there. 5 test names: `test_every_existing_row_is_backfilled_to_concept_equals_id_and_shared`, `test_1_two_shared_rows_for_one_concept_are_REJECTED`, `test_2_a_shared_and_a_personal_row_for_one_concept_COEXIST` (`test_ingredient_identity.py:39,86,97`), `test_all_36_shared_rows_still_serve_to_the_harness_user`, `test_a_shared_row_serves_to_a_DIFFERENT_user_too` (`test_ingredient_privacy.py:41,55`) | rename | test rename |
| A8 | 🛑 **WONTFIX.** Migrations are historical artifacts and the corrected model lives in `docs/ingredient-model.md`. Editing comments in an applied or soon-applied migration rests on an unenforced convention anyway (`migrate.py` records `filename` only, with no checksum), so they are left exactly as written. `migrations/031_ingredient_identity.sql` header, 7 hits, including line 4's rationale "a user's personal gochujang and **the shared gochujang**" | applied history | ⚠️ do NOT edit an applied migration. Correct it in the doc that explains it |
| A9 | 🛑 **WONTFIX**, same reason as A8. `alembic/versions/f2a3b4c5d6e7_…py`, 4 hits | applied history | ⚠️ same |
| A10 | ✅ **DONE (`bf80ee4`)**, leave-and-document, explained in `docs/ingredient-model.md` section 3. **`idx_ingredients_shared_concept`**, a schema object, named in `migrations/031:44`, `alembic/…:37,43`, `models.py:96`, `tests/pg_harness.py:106`, `tests/test_ingredient_identity.py:137`, `tests/test_pg_integration.py:97`, `docs/panel-design.md:505` | ⚠️ **NEEDS A MIGRATION** on both dialects. The cheapest correct answer may be to leave the name and document it |
| A11 | ✅ **DONE (`bf80ee4`)**, SUPERSEDED by `docs/ingredient-model.md`, body untouched. `docs/panel-design.md`, 45 hits | ⚠️ **NEEDS A DECISION**, not an edit. The document's structure is built on the tier. Phase 4 should decide whether it is rewritten or superseded |

## B. Docs under-claiming shipped work

| # | file:line | claims | reality | risk |
| --- | --- | --- | --- | --- |
| B1 | ✅ **DONE (`f0f01e4`).** `docs/SECURITY.md:65-69` | `PUT`/`DELETE /api/recipes` "do **not** check `owner`". The image route is "the **one exception**… the single genuine write-ownership gap" | 7 owner gates: `app.py:848, 940, 964, 1529, 1596, 1638, 1896` | doc edit |
| B2 | ✅ **DONE (`f0f01e4`).** `docs/design-decisions.md:807-809` | the same gap, "recorded here as a follow-up, **not fixed in this stage**" | same. **Contradiction J: one closed follow-up recorded as open in two documents** | doc edit |
| B3 | ✅ **DONE (`f0f01e4`).** `ROADMAP.md:1049` | images served off local disk "with **no upload endpoint**" | 6 photo routes: `app.py:951, 1499, 1564, 1583, 1604, 1624` | doc edit |
| B4 | ✅ **DONE (`f0f01e4`).** `docs/migration-plan.md:91` | "an upload path (**none today**)" | same | doc edit |
| B5 | ✅ **DONE (this commit).** Rewritten to say the locked design SHIPPED, absorbing the `manual` mentions at `:704`, `:705` and `:716` into one correct statement of the `original` / `cook` vocabulary. `docs/design-decisions.md:1417`'s stale "`'cook'`-only for now" was fixed in the same pass. `ROADMAP.md:691` | "**change-tracking is NOT built**… no before/after, no timestamp, no per-change identity" | 298 `recipe_snapshots`, `snapshot_diff` consumed at `app.py:619`, `get_recipe` returns `annotations` | doc edit |
| B6 | ✅ **DONE (this commit).** All three sites replaced with the five measured blockers: 91.2% unread, no write path, the absent library CSV, the 36-row scale assumption, and 299 ambiguous links needing a tiebreak rule. The matcher is recorded as FINISHED, re-run at 9.0 seconds. `docs/ingredient-linkage-state.md:11,123-125,327` | the matcher "has no committed home", "if the scratch directory is lost, the matcher is lost", "**the binding constraint**" | committed in `b42dd14` to `study/matcher/`, runs from there in 9.5 seconds. ⚠️ The constraint is now verification effort and a write path, not the matcher | doc edit |

## C. Stale docstrings claiming live code is inert

Each of these tells a reader the code is unused. Each is wrong, and each sits on code that is
load-bearing.

| # | file:line | says | reality | risk |
| --- | --- | --- | --- | --- |
| C1 | ✅ **DONE.** `snapshot_diff.py:3` | "Nothing consumes it yet" | consumed at `app.py:619` | code comment |
| C2 | ✅ **DONE.** `snapshot_headsync.py:5` | "nothing calls it yet" | called on **every save**, `app.py:591-592` via `:888`, and `assert_content_safe` aborts the save | code comment |
| C3 | ✅ **DONE (this commit).** Six sites: `app.py`'s `snapshot_recipe` docstring and four in `models.py`'s `RecipeSnapshot`. Measured reasons are `original` and `cook`, four call sites, and `manual` exists nowhere in code or data. `app.py:525,527` | "reason ('cook' \| 'manual')" and "Nothing reads snapshots yet" | live reasons are `cook` and `original`, `manual` does not exist, and annotations read them | code comment |
| C4 | ✅ **DONE.** `models.py:397` | "INERT: nothing reads this table" (`library_names`) | 2 readers: `app.py:314`, `app.py:1266-1268` | code comment |
| C5 | ✅ **DONE (`f0f01e4`).** `models.py:74` | `library_id`, "Nothing on a page reads it" | the whole-row drawer select serves it, and `search_library` reads it | code comment |
| C6 | ✅ **DONE (`f0f01e4`).** `models.py:75` | "Both columns are inert until stage 5" | stage 5 shipped | code comment |
| C7 | ✅ **DONE (`f0f01e4`).** `models.py:68` | "stage 5 **will** also create rows" | it does | code comment |
| C8 | ✅ **DONE (this commit).** The header names the shipped capability, TipTap steps with `[[key\|label]]` chips, rather than a stage label nothing defines. `{{...}}` and autocomplete are still correctly listed as not handled. `static/step-editor.js:1-5` | "Stage 1a… **PLAIN TEXT ONLY**… NO link chips, NO `[[key\|label]]` parsing" | `IngredientLink` at `:30`, `renderHTML` at `:39`, `step-adapter.js` imported | code comment |
| C9 | ✅ **DONE.** `docs/design-decisions.md:1419` heading | "shipped; pure engine, **nothing consumes it yet**" | superseded 154 lines later by O-c-1 at `:1573`. ⚠️ The risk is the **heading**, which a table-of-contents reader trusts | doc edit |
| C10 | 🛑 **WONTFIX, UNLOCATABLE.** Cannot be actioned as written. `docs/migration-plan.md` holds ZERO occurrences of "invite", and the quoted phrase appears nowhere in the repo except this row. `docs/migration-plan.md` schema note | `invites.expires_at` "present now, unused until a later stage" | `signup` checks it, `auth.py:120-121` | doc edit |
| C11 | ✅ **DONE.** `auth.py:9-10` | "NO *existing* app route is gated yet (that's auth-3b)" | auth-3b shipped, and every route is gated by `_require_login` | code comment |

## D. Doc-versus-doc contradictions

| # | contradiction | risk |
| --- | --- | --- |
| **D1** | ✅ **DONE (`7ae120b`)**, both sides corrected. The direction is settled, the mechanism is still open. ⚠️ **WAS HIGHEST PRIORITY.** `CLAUDE.md:349` says the 36-row library is "*still* seed-rebuilt on every `build_db` (**intended**, the seed 'bones' stay)". `docs/panel-design.md`'s corpus decision says the rebuild must stop and the 36 become durable rows. **`CLAUDE.md` is the file every session reads first.** | ⚠️ needs a decision, then a doc edit |
| D2 | ⏸️ **OPEN, the one live entry left.** Needs a wording call across BOTH `CLAUDE.md:13` and `ROADMAP.md:689`, and `single-user-assumptions.md` says the design intent is real, so it may want rephrasing rather than deletion. Cook-gating. `CLAUDE.md:13` and `ROADMAP.md:689` say "cook-gated star ratings". `app.py:1449` says `# NOT cook-gated: rating an uncooked recipe is allowed`. `docs/single-user-assumptions.md:156` already records the correction. The gate is client-side only (`static/app.js:185,221`) | doc edit |
| D3 | ⏸️ **OPEN but largely moot.** `docs/ingredient-model.md` settles the vocabulary ("the owner's corpus") and `CLAUDE.md:349` was corrected in `7ae120b`. What remains is propagating the term. **Four vocabularies for the same 36 rows**: "the owner's corpus" (`panel-design`), "the seed 'bones'" (`CLAUDE:349`), "the 36 library descriptions" (`CLAUDE:103`), "a shared ingredient field guide" (`OVERVIEW:12`, `README:46`, `models.py:67`) | needs a decision |
| D4 | ⏸️ **OPEN but largely moot.** `panel-design.md` is SUPERSEDED, so its rule 8 is no longer a live claim against `product-vision.md`. Moderation. `docs/product-vision.md:71` says "**No moderation/review.**" `docs/panel-design.md:279` rule 8 says "It **must** have a review UI" | needs a decision |
| D5 | ⏸️ **OPEN**, a one-line `product-vision.md` correction nobody has scoped. The per-line change layer. `docs/product-vision.md:55` lists "per-line edits/additions" as the personal layer. `recipe_line_changes` and `recipe_additions` were dropped in migration 020 and neither table exists | doc edit |
| D6 | ✅ **DONE (this commit)**, resolved by B5. Change-tracking, B5 above, is also a doc-versus-doc: `ROADMAP:691` versus `design-decisions:1392,1573` | doc edit |
| D7 | ✅ **DONE (`f0f01e4`)**, both sides corrected together. The two security under-claims, B1 and B2, are the same claim in two documents | doc edit |
| D8 | ✅ **DONE (`f0f01e4`)**, both sides corrected together. The two upload under-claims, B3 and B4 | doc edit |

## E. Stale numbers, correct when written

| # | file:line | says | measured | risk |
| --- | --- | --- | --- | --- |
| E1 | ⏸️ **OPEN.** The corrected number needs the gitignored library to re-derive and cannot be checked from a clean tree. `docs/ingredient-linkage-state.md:78` | ASCII folding "erases **56** of the 10,527" | **39** | doc edit |
| E2 | ✅ **DONE.** `OVERVIEW.md:72` | "50 of **3,384** ingredient lines" | **3,332** non-heading (3,555 rows all told) | doc edit |
| E3 | ✅ **DONE.** `OVERVIEW.md:73` | "**125 of 304** recipes have one" | **298** recipes, and 120 have a real image path. ⚠️ **Fixing this caught an UNCATALOGUED sibling three lines up**, `OVERVIEW.md:70` carried the same wrong **304** for the baseline count. Measured 298 recipes and 298 `recipe_snapshots`, all `reason='original'`. Fixed in the same pass | doc edit |
| E4 | ✅ **DONE.** `OVERVIEW.md:26` | `seed.py` holds "the ingredient library **and the people**" | `PEOPLE` no longer exists (migration 020) | doc edit |
| E5 | ⏸️ **OPEN.** A moving target: the counts must be measured by a live suite run at the moment of the edit. `docs/migration-plan.md:31,52` | "SQLite suite (**288 + 6 skipped**) AND the PG integration suite (**6**)" | **1,238 + 22 skipped**, and **21** PG | doc edit |
| E6 | ~~`CLAUDE.md` setup block~~ | ~~"7 packages"~~ | 🛑 **WITHDRAWN, THIS ENTRY WAS WRONG.** `CLAUDE.md`'s "7 packages" is CORRECT. Re-measured: `requirements.txt` has **7** uncommented lines (flask, flask-login, SQLAlchemy, alembic, psycopg, pillow, pillow-heif). The "6" was a miscount. **Acting on this would have introduced an error.** | 🛑 do not fix |
| E7 | ✅ **DONE.** `docs/design-decisions.md:575` | "the real **3,385**-row corpus in `recipe_ingredients`" | **3,555** | doc edit |
| E8 | ⏸️ **OPEN.** The artifact is gitignored and regenerating it means running the real generator against `join.db` / `sources.db`. `previews/current-coverage.csv` | 11,217 rows / 10,387 kept / 183,651 keys | **11,357 / 10,527 / 184,891** at this HEAD. ⚠️ The artifact labels its own HEAD, and is gitignored | regenerate |
| E9 | ⏸️ **OPEN**, a deferred comment sweep over seven sites. `ingredient_cuts.py:25` and `build_library.py:21, 580, 866, 2027, 2235, 2245`. ⚠️ **Re-measured: SEVEN sites across two files, not the two cited here, and both line numbers in the original row had drifted** | "the 11,153-row list" | 11,357. The reasoning around them is unaffected | code comment |
| E10 | ⏸️ **OPEN.** A doc ADDITION rather than a correction, and where it belongs is a choice. ⚠️ Partly satisfied already: the matcher README states it, and B6 now states it too. The linkage denominator. `3,332` (all non-heading, the seg0-core denominator) versus `2,997` (with a label, `LINK.py`'s input). **Both are correct over their own set, and no document says so.** 2,771/3,332 = 83.2%, 2,214/2,997 = 73.9% | doc addition |

## F. Stale line references

| # | citation | points at now |
| --- | --- | --- |
| F1 | ✅ **DONE (this commit)**, symbolized to `app.py::write_recipe_rows`. `CODE_WALKTHROUGH.md:322` cites `app.py:298-311` for `write_recipe_rows` | `_promote_library_row`'s docstring. The function is at **`app.py:446`** |
| F2 | ✅ **DONE (this commit)**, symbolized to app.py's `Flask()` constructor. `ROADMAP.md:1480` cites `app.py:49` for the `Flask()` constructor | **`app.py:55`** |
| F3 | ✅ **DONE (this commit)**, symbolized to app.py's `_secret_key` dev fallback. `ROADMAP.md:1482` cites `app.py:79` for the dev `SECRET_KEY` fallback | **`app.py:84`** |
| F4 | 🛑 **WONTFIX.** The host doc is a DATED point-in-time survey, not living documentation, and the date is the disclaimer. Refs not maintained. `docs/import-damage-survey-2026-08.md:285` cites `app.py:298-311` | same as F1 |
| F5 | 🛑 **WONTFIX**, same dated-survey reason as F4. `docs/import-damage-survey-2026-08.md:332` cites `app.py:373`, `:906`, `:985`, `:1022` | cook snapshots are at **`app.py:1351`, `:1430`** |
| F6 | 🛑 **WONTFIX.** The host doc is SUPERSEDED (`bf80ee4`) and its header freezes its citations in as many words. Editing them would contradict the freeze. `docs/panel-design.md:547` cites `ROADMAP.md` line 1040 for the ephemeral-filesystem flag. ⚠️ **This citation has itself drifted to `:577` since, and we caused it**, see the status block | the item is at **`ROADMAP.md:1049`** |
| F7 | 🛑 **WONTFIX**, same superseded-doc reason as F6. ⚠️ **AND THE 'all still correct' BELOW IS NO LONGER TRUE.** `f0f01e4`'s one-line comment edit shifted all six `app.py` citations by one: 1062→1063, 1071→1072, 1096→1099, 1103→1104, 1135→1136, 1169→1170. Only `build_db.py:152-154` still holds. `docs/panel-design.md` cites `app.py:1062, 1071, 1096, 1103, 1135, 1169` and `build_db.py:152-154` | ~~**all still correct**~~, and all fragile |

⚠️ **The principle, stated once.** Every document that cites `file:line` has drifted, and the ones
that cite function and symbol names have not. `docs/design-decisions.md` makes exactly **one** code
reference in 1,645 lines, and it names a function rather than a line. It is the only large document
with no drift. **Phase 4's authoritative document should cite symbols, not line numbers.**

## G. Data-shape anomalies

Not documentation problems. Actual data, recorded so a later change does not trip over them.

| # | finding | measured |
| --- | --- | --- |
| G1 | 15 recipes carry `image = ''` rather than NULL, so `image IS NOT NULL` overcounts heroes by 15 | 135 non-NULL, 120 with a real path |
| G2 | **Every `cook_photos` row has `cook_log_id IS NULL`.** The per-cook album that migrations 025 to 027 and several backfills exist to support has never held a row | 129 of 129 |
| G3 | `import_flags` has **no status column**, so a flag cannot be marked reviewed. The one code path that reads the table gates on `flag='imported_via'`, which has **0 live rows**, so it has never fired | 593 flags over 209 recipes |
| G4 | One orphaned image file, `images/baked-cauliflower-…-copy-copy.jpg`, nothing points at it | 130 files, 129 referenced |
| G5 | `recipe_snapshots` holds 298 rows, **all `reason='original'`, zero `'cook'`**, though both cook paths exist in code | 298 / 0 |
| G6 | The live `recipes.db` is at **28 of 31** migrations. 029, 030 and 031 are pending and will apply together on the next `build_db.py` | 28 / 31 |

## H. Corrections to earlier, wrong, logged items

⚠️ **Do not act on these. They were logged as cleanups and are not.**

| # | previously logged | actual |
| --- | --- | --- |
| H1 | "`.season-none` at `styles.css:1479` is dead CSS, trivial future cleanup" | ⚠️ **It is LIVE.** `static/app.js:557` uses it for the home season rail's empty state. Stage 7 removed the **drawer's** year-round line by making `buildSeason` return `""`. The home rail is a different, live use |
| H2 | "`library_names.csv` exists on no machine" | It is absent from the **repo root**, where `build_db` looks. A copy exists in the session scratch directory |
| H3 | "the matcher is 328 untracked files, one reset from gone" | True when written. Committed in `b42dd14`. 24 files, 172 KB of source and hand judgment |
| H4 | "`ingredients` has exactly two writers and both were fixed" | **Three.** `tests/pg_harness.py` was the third and only ran under Postgres. Fixed in `3ac4799` |

---

# 3. Greenfield and plan inputs

**Not changes.** Findings that constrain whatever gets built next, kept separate on purpose.

## The panel's review model

`@admin_required` exists at `auth.py:67` and works: `@login_required` then an `is_admin` check, 401
and 403 kept distinct. It gates exactly **two** routes, both `/api/invites`.

⚠️ **No status column exists anywhere in the schema.** Not on `invites`, not on `import_flags`, not
on anything. `friendships` has `pending`/`accepted` and that is the whole of it. **The panel's review
queue would introduce the first one.** The decorator is one line of reuse. Everything behind it is
greenfield.

## The backfill

The matcher emits `(anchor, library_id, canonical)`, which is **not a valid foreign key value**.
`recipe_ingredients.ingredient_id` points at `ingredients.id`.

So writing the backfill requires, in order:

1. resolve `library_id` to an `ingredients` row, which is what `_promote_library_row` does
2. which needs `library_names` populated, which needs the 330 KB gitignored CSV
3. only then `UPDATE recipe_ingredients SET ingredient_id = …`

⚠️ **Scale consequence nobody has costed.** 2,771 matches would materialize up to 2,771 `ingredients`
rows against **36** today. **25 test assertions across 10 files, and every documented count, are written against 36.** ⚠️ This row said **23** when written. Re-measured at `86671ee`: **25**. Same class of internal error as E6 and E9.

⚠️ **And 3,038 lines (91.2%) have never been individually read**, 2,410 of them in an AGREE block
where two matchers concurred and neither was checked. The confidence bands are **computed** from
n-gram length and coverage (`AGREE.py:46-51`), with no human input. HIGH means the algorithm is
confident.

## Auto-link-at-import

`import_write.py:128` writes `ingredient_id: None`, three times stated. The import pipeline imports
nothing library-related, correctly.

⚠️ **The constraint is not plumbing.** On a server only `library_names` exists, which holds **10,527
canonical names**. The matcher indexes **184,891 variation keys** over the same rows. Import-time
linking against canonicals alone would be a far weaker matcher, and the variation index has no
server-side representation.

⚠️ **A second constraint.** `plan_recipe` is pure by contract and takes no connection, which is what
makes the dry-run exact. Adding linkage means either giving the pure planner a data source or moving
it into `commit_plan`, which weakens that guarantee.

## The browse / add / manage surface

Entirely greenfield on the client. Confirmed from both sides: the router has 5 routes and none is
ingredients, there is no create, edit or search UI, and the three shipped backend features have
**zero** client callers (`item_library_id`, `/api/library/search`, `DELETE /api/ingredients` all
return 0 occurrences across `static/`).

## Per-reader `[[key]]`

`static/app.js:65-71` is a pure regex substitution. It never consults `INGREDIENT_LIST` and has no
branch for a missing key. A dead key renders as a normal link and silently does nothing on click,
because the bare `catch` in `openPanel` swallows the 404.

**That function is where per-reader resolution has to be built**, and Decision I in `panel-design.md`
(what a `[[key]]` does when the reader has nothing) lands exactly there.

## Deploy

**The data layer is done. The serving layer does not exist.**

Present: a working `DATABASE_URL` switch, a Postgres-complete Alembic chain at head `f2a3b4c5d6e7`, a
one-time data-migration script, dual-dialect CI, and a `SECRET_KEY` fence that refuses to start on
Postgres without one.

Absent: `Dockerfile`, `docker-compose`, `Procfile`, `render.yaml`, `fly.toml`, `railway.json`,
`vercel.json`, `app.yaml`, `.env.example`, any WSGI server in `requirements.txt`, and any deploy
automation. Neither CI workflow deploys and the only secret is `SONAR_TOKEN`.

Two gaps carry forward:

- ⚠️ **The Postgres loader gap is structural.** `build_db.py` and `migrate.py` use `sqlite3.connect`
  and never touch SQLAlchemy. `seed_library_names` cannot run on Postgres at all, so Alembic creates
  `library_names` and nothing fills it. This is a documented decision (`migration-plan.md:51`), not an
  oversight, and a dialect-neutral loader is needed under every hosting option and decided by none.
- ⚠️ **Four local-filesystem artifacts have no persistence story.** `migration-plan.md:92` names
  three (the SQLite file, `static/images/`, `backups/`). The library CSV is the fourth and postdates
  the plan. **The asymmetry matters: the library file regenerates in ten seconds, a user's photo does
  not.**

⚠️ **Nothing enforces the SQLite-to-Alembic pairing.** The baseline `72e165e6482e` is a snapshot of
migrations 001 to 016 autogenerated from `models.py`, and 017 to 031 map one-to-one onto 15
revisions. The arithmetic works (16 + 15 = 31, 1 + 15 = 16) but **no test asserts that a new
migration has a twin.**

---

# 4. Verified correct, and to be preserved

These are load-bearing and right. **Do not "fix" them.**

- **The anchor clause** (`ingredient_cuts.py:14-40`). Any cut phrased as "single source and no
  variations" without naming an anchor kills every override at once. Measured: cuts C, E and F each
  removed Shaoxing wine. The existing cuts miss the overrides **only by luck**.
- **The license-driven source separation** (`build_sources_db.py:20-30`). Whole, unmodified,
  source-labelled tables side by side are a Collective Database under ODbL. Merging them attaches
  share-alike to the product. The separation is not tidiness.
- **The import rules**: honest user agent, never `html.unescape()` a `<script>` body, cascade not
  merge. Each is measured and each has a stated failure it prevents.
- **Decline-over-guess**, the import core's governing principle. The failure mode is a flagged line,
  never a wrongly structured one.
- **The ISLAND INVARIANT** (`static/step-editor.js:8-13`). `paintRecipe` fires only at load, enter and
  exit. A mid-session repaint must destroy and remount, or the editors are orphaned.
- **`linkify` and `renderHTML` emit the same markup on purpose**, which is why the drawer listener
  needs the `.step-editor-host` exclusion.
- **The box model.** All recipes visible to everyone, the personal layer scoped per user by
  correlated subquery, writes gated on owner. `docs/SECURITY.md:78` describes it accurately.
- **The fail-safe direction of `source` defaulting to `'seed'`** (`migrations/030`). A writer that
  forgets leaves a row undeletable rather than deletable.
- **The materialization boundary.** Recipes link to materialized `ingredients` rows, not to library
  rows, because library ids are not durable across a rebuild (7 died in `460cae5`) and the library
  itself is 6 GB of gitignored databases. `migrations/030` states it: "the durable link target is the
  `ingredients` row itself".
- **The four-step order in `_promote_library_row`**: lookup, then `library_id`, then slug, then
  insert. Step 2 was missing once and a pre-push review found what it cost.
- **Ownership folded into the lookup** in `get_ingredient`, so there is one refusal branch and a
  hidden row is never fetched.
- **404 rather than 403 for a row you may not read.** A 403 would let anyone recover the answer by
  probing the detail route and the delete route together.

## ⚠️ The valid senses of "shared". Do not find-replace

| sense | where |
| --- | --- |
| the library is app-global, **not boxed** | `docs/product-vision.md:60` |
| a shared **corpus of recipes**, the box model | `docs/SECURITY.md:79` |
| shared **brain modules** (`weights.py`, `stepscale.py`, `images.py`, `scaler.js`) | `CLAUDE.md:80`, `docs/design-decisions.md` ×12 |
| a shared **image file** between a copy and its original | `docs/design-decisions.md` ×5, `app.py::unlink_unreferenced` |
| `shared_posts`, the table | throughout the social layer |
| a shared **CSS token or DOM element** | `docs/design-decisions.md` ×4 |
| the hero caption slot, shared between hero and album | `docs/design-decisions.md:1246,1249` |
| **SHARED (a recipe)**, a feed post type | `docs/design-decisions.md:681` |

**Only the tier sense is wrong, and only in the places enumerated in section A.**

---

# What this document is not

It corrects nothing. It records what a complete read found, so that Phase 4's authoritative document
and the eventual fixes start from measurement rather than from memory.
