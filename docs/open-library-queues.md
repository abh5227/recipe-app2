# Open library queues

A **living register** of what is known-wrong or known-unfinished in the ingredient library, and where
the detail sits. Items get added when a read finds them and struck when they close. This is not a
dated snapshot. [reconciliation-2026-08.md](reconciliation-2026-08.md) is one, and it stays that way.

⚠️ **This file exists because none of these queues has a committed home.** The detail lives in
`previews/library-audit.xlsx`, `previews/library-duplicate-scan.xlsx` and `preview/entries-v3/`, and
all three are gitignored. Lose the machine and the queues go with it. So this is a pointer, not a
re-analysis: what is open, how big it is, and which artifact holds the rest.

**Opened 2026-08-31**, after the fold (`178dfae`), the commonality tier (`86bb61e`) and the browse port
(`dd89a05`, `1253206`, `fe8f7d1`). The catalog is **10,515 kept rows** at that point.

---

## 1. The commonality tier is in the file and not in the database

`build_library.mark_commonality` gives every kept row one of **staple, common, everyday, speciality or
obscure**, and `write_library_names` writes it as a third column. **The `library_names` TABLE is still
two columns, so the app cannot query the tier.**

`build_db.seed_library_names` reads its two fields by name through a `DictReader`, which is what lets a
three-column file load into a two-column table without error. Nothing is broken, and nothing is
available either.

Closing it needs a numbered migration plus an Alembic revision. ⚠️ **`build_db.py` never runs against
Postgres** ([migration-plan.md](migration-plan.md)), so the PG side needs its own answer rather than
falling out of the same change. Deferred deliberately, not overlooked.

## 2. Library correctness

The fold closed the twelve pairs the charter settles, where a Latin binomial stood beside the
common-name row it names. It closed nothing else.

- **118 duplicate pairs remain**, where one row's English name is another row's canonical and the two
  share at least two names. **7** are binomial-shaped without a Latin tag, **111** are plain English.
  ⚠️ **Direction is settled by no rule for any of them**, and several are probably two ingredients
  rather than one row duplicated (`cassava` and `tapioca`, `meat` and `fresh meat`, `bacon` and
  `Speck`). The detector points the wrong way on `cookie` and `biscuit`, and on `whole-wheat flour` and
  `wholemeal flour`, where the charter's US-English rule says the left side wins. **A review queue, not
  a defect list.**
- **297 lone rows** carry a common English name with no sibling row to fold into, the shape
  `Tamarindus indica` has. These need a rename rather than a fold.
- **5 entry pairs need merging by hand**, where both rows carry a developed entry:
  `coriandrum-sativum` with `cilantro` (now on one row, `Q65523167`, exposed by the fold),
  `peppercorn` with `black-pepper`, `cassava` with `tapioca`, `ground-beef` with `minced-meat`, and
  `cookie` with `biscuit`.
- **`tamarind`, `lemongrass` and `chile_powder`** have no catalog row that slugifies to the seed id.
  `green_onion` is a naming mismatch against the catalog's correct `scallion`.

Detail: `previews/library-duplicate-scan.xlsx`, four tabs, gitignored.

## 3. Sourcing has barely started

The 142 entries in `preview/entries-v3/` carry **220 claims**, of which **185 are GENERATED** stubs with
`source_class = inference`, **32 CURATED** and **3 CITED**. **102 claims are `unresolved`.**

⚠️ **No citation resolves.** 22 entries carry a `[[claims.chain]]` block naming 35 source slugs
(`pubmed-24266426`, `legifrance-decret-88-1204-art-2`), and **no registry maps a slug to a reference**.
**0 of 142 entries contain a URL.** `review_state` is `unreviewed` on all 142. Even the 3 CITED claims
name their authority only in prose, with no citation field.

The tiers, gates and axes these are judged against are in [sourcing-tiers.md](sourcing-tiers.md).

Detail: `previews/library-audit.xlsx`, four tabs, gitignored.

## 4. Known limits that are accepted rather than open

Recorded so they are not re-discovered as bugs.

- **Commonality mis-tiers a specific form of a common thing.** `light brown sugar` holds 0 variation
  names, `Shaoxing wine` 0, `light soy sauce` 9, while their parents hold hundreds. Fixing it properly
  means parent-child inheritance, which is the unbuilt gap in [parent-child-gap.md](parent-child-gap.md).
  A shallow version would be worse than the miss.
- **`n_variations` measures how many languages named a thing**, not kitchen frequency, so `sumac` and
  `gochujang` read everyday.
- **Neither the binomial shape test nor the Latin language tag is complete.** Shape finds 864 rows at
  low precision, the tag finds 121 and is right about them, and `Tamarindus indica` carries no Latin tag
  at all. The duplicate scan therefore keys on the defect (two rows, one ingredient) rather than on
  either test.
