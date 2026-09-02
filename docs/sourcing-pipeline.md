# The sourcing pipeline

How ingredient library entries get from an unsourced stub to a verified one, and **why the work is
split the way it is.**

**This document is the durable design. It is not the operating manual.** The manual lives in
gitignored working files described at the bottom, changes after most batches, and is mirrored to a
Claude Project that parallel chats read. **This file exists because the design was living only in those
gitignored files**, one machine away from being lost.

For the tiers, gates and the allergen rule the pipeline enforces, see
[sourcing-tiers.md](sourcing-tiers.md). For what the library is for, see
[what-the-library-is-for.md](what-the-library-is-for.md).

## The shape

```
  a stub entry  ->  a sourcing chat drafts + flags  ->  handover  ->  verification  ->  verified
                    (parallel, in the Project)         (clerical)    (Claude Code)
```

Two different agents, doing two different jobs, and **the split is the whole design.**

## The split: draft and flag, never reconcile

**A sourcing chat sees three entries.** It reads a mounted mirror of the queue and the brief, drafts
its batch, opens sources, writes citations, and stops. It cannot read the other sourced drafts, cannot
reach the catalog build, and cannot know whether its work is correct.

**So it flags rather than reconciles.** Where its entry touches another, it says what it saw and what
it could not check. It does not adjust a sibling entry, and it does not claim two entries agree.

**Verification reconciles.** It reads the real drafts, runs the live catalog, and owns everything
cross-entry. It is the only step that can, because it is the only step that sees more than three
entries at once.

⚠️ **This is not a formality, and here is the case that proves it.** A batch sourcing coriander seed
had to reconcile against cilantro. The copy it could read was a pre-sourcing stub, so it marked the
boundary `cannot_assess` rather than claiming agreement. Verification read the real cilantro draft and
found the two **contradicted**: coriander seed stated the soap-genetics flat, re-importing an
overstatement that the cilantro pass had deliberately removed. **The defect was findable only because
the chat reported the limit instead of papering over it.**

## The standing batch-return procedure

**When a sourcing batch comes back, this is what happens. It is not re-specified per batch.**

**1. Output lands in `Library/`.** Always. The folder a browser download creates is arbitrary and its
name means nothing.

**2. Self-locate the batch.** The new work is **the entries in `Library/` that are not yet in
`Library/sourced/`.** The delta is the batch. **No folder needs naming**, which matters because
download folders collide and get reused.

**3. Run THE PROCESS.**

```
inventory   entries present, parse, ASCII, claims closed, flags wired,
            capture fields present
verify      citations against the handoff fetch log as a work-map, cross-entry
            against the REAL sourced drafts, capture-field curation
fix         mechanical directly, content edits shown for approval first
file        TOMLs to Library/sourced/, findings and handoffs to Library/reports/,
            archives to Library/_archive/. Nothing left loose.
record      the verdict to previews/verifications/
track       update sourcing-progress.md
```

**THE PROCESS owns the tracker update.** A batch proposes, and only this step marks anything done.

⚠️ **Cross-entry work reconciles against the real sourced drafts in `Library/sourced/`, never against
a stub or a mirror.** That is the whole reason the step exists, and reading the wrong copy has produced
a defect at least once.

**4. Batches arrive on current specs**, because the brief and the tracker are synced to the Project
before sourcing starts rather than after. A batch drafted against a stale brief has to be backfilled,
and one of those backfills was only possible because the ids were still alive.

## The status vocabulary

```
sourced-pending-verification   drafted, handed over, NOT checked. The ONLY status a
                               sourcing chat may write about its own work.
HARSH-VERIFIED, FIXES PENDING  checked citation by citation, findings recorded, not applied
HARSH-VERIFIED, FIXES APPLIED  checked, findings fed back, corrections on disk
```

**A batch cannot mark its own work verified.** Only the bulk verification moves an entry out of
`sourced-pending-verification`. Taking a handover does not. Filing a record does not. Merging a tracker
update does not.

**Completeness-checked is not verified.** Confirming a file was not truncated says nothing about
whether its sources say what it claims. Those were conflated once and the cost was a batch nobody could
tell the status of.

## The handover

Every batch returns its edited entries plus two files.

**A handoff record**, whose load-bearing part is the **fetch log**: every URL touched, with an outcome
of cited, rejected, blocked or named-not-opened, and a reason on the rejections.

⚠️ **Why the fetch log exists, measured.** Across the first four batches the reports carried **zero
URLs**. Every page a batch had already tried and discarded had to be re-fetched during verification,
because the record of the rejection did not survive the chat. The log turns verification's work into
reading a map rather than re-walking the ground.

**A proposed tracker update**, clearly unmerged, covering only that batch's entries. The next-batch pick
in it is labeled proposed, because it was computed against a mirror that has drifted twice.

## Verification, and why it is bulk

Verification opens every URL, checks every `taken` against what the source actually says, tests every
tier, applies the fixes it finds, and writes a durable record per batch.

**It reads the handoff records as a work-map.** Which chains are snippet-depth, which hosts are blocked,
which primaries were named but never opened, which fits the batch itself called loose, and which URLs
were already rejected so it does not re-fetch them.

**A verification that lives only in a conversation did not happen**, as far as the next person is
concerned. That is why the records are files.

## The four capture fields

All four are **observations, not claims.** They carry no tier, no chain and no source, and they sit at
the top level of an entry rather than inside `[[claims]]`. A claim needs a falsifier and a citation.
These need neither, because they assert nothing about the world.

**They are captured cheaply while a chat already has the ingredient open**, and reconciled or
represented later by someone with more context.

| field | what it records | why the chat is the right place |
| --- | --- | --- |
| `library_canonical` | the catalog canonical the entry's `library_id` pointed at, on the day it was written | ⚠️ **perishable.** Ids die when a curation change flips a row's anchor. Once dead, the name it pointed at cannot be recovered, only guessed |
| `possible_parent` | the broader ingredient a cook would name, if there is one | the catalog knows the taxonomy and calls things `spice`. Only the chat knows which broader thing a cook reaches for |
| `form` | the physical form, paste, powder, dried, oil | it cannot write a description without knowing this |
| `cuisine` | the tradition, where the ingredient is genuinely anchored | **left blank on most entries, which is correct.** Flour and salt belong to everybody |

⚠️ **`form` is not the `[[forms]]` block.** `[[forms]]` records **name** disposition, whether a name
belongs on this row. `form` records what the **product** physically is. Filling one does not fill the
other.

⚠️ **`possible_parent` is not a borrowed name either.** A `[[forms]]` entry marked `belongs_elsewhere`
says a name sits on the wrong row. `possible_parent` says an ingredient is a specific form of another.
Both can be true at once and neither implies the other.

## The entry field is `library_id`

Entries formerly carried `wikidata = "Q..."`. **The field is now `library_id`**, matching the catalog
column, because the value is not always a Wikidata id. Open Food Facts rows key on `en:cumin-seeds` and
authored rows carry no id at all. Naming the field after one of its three possible sources was
misleading on 4,100 rows.

## What is deliberately deferred

Each of these is capture-now, use-later. **They are deferred for a reason, not overlooked.**

**Integration.** The verified entries are not in the library. They live outside the repo and integration
has not run. Several other deferrals hang off this one, because how integration handles ids decides what
the healing code has to do.

**The dual-key reconcile.** `library_canonical` is captured so a future pass can heal a dead id by
matching the stored name. **The snapshot was taken now anyway because it is perishable and the reconcile
is not.** The pairing is only knowable while the id is alive. The healing code can be written any time.

**Parent-child representation.** `possible_parent` markers accumulate and verification curates a
proposed structure, but nothing is linked. The library has no parent-child mechanism, and the closest
operation, the fold, merges duplicates rather than relating two genuinely different rows. See
[parent-child-gap.md](parent-child-gap.md) and the flour case in
[open-library-queues.md](open-library-queues.md).

**`form` and `cuisine` representation.** No column, no filter, no facet. Values are collected and
reconciled to canonical lists, nothing more.

⚠️ **And one naming collision to settle before any of that is represented.** `regions` in the database
means **where an ingredient is grown**, sitting beside `season` in `seed.py`. The new `cuisine` field
means **whose cooking it belongs to**. Two axes, confusable names, and they will sit next to each other
the moment anything renders them. **`regions` should be renamed `grown_in` at that point.**

## Where the operational files live

**All gitignored working files, not repo content.** They change after most batches and are mirrored to
the Project that sourcing chats read.

```
previews/SOURCING-OPERATOR-BRIEF.md   the manual a chat reads. Every rule in it exists
                                      because a batch got something wrong
previews/sourcing-progress.md         the queue tracker. Chats self-select their batch from it
previews/allergen-routing-card.md     where to fetch allergen facts, since the FDA page
                                      is bot-blocked to fetchers
previews/PROJECT-SYNC-PROCESS.md      when to re-sync the mirror, and what happens if you do not
previews/verifications/               one durable record per batch
previews/handoffs/                    the fetch logs, read as the verification work-map
previews/metadata-vocabularies.md     the canonical form and cuisine lists.
                                      ⚠️ NEVER synced. A chat that sees the list matches it
                                      instead of reporting what it observed
Library/sourced/                      the verified drafts, outside the repo, awaiting integration
```

⚠️ **The mirror going stale is silent.** A chat reading an old tracker does not error, it does the wrong
work and reports success. That has happened twice, once double-sourcing salt and once sending a batch to
reconcile against a stub. **There is no automatic guard, only the sync discipline.**
