# Estimating: whose hours are being counted

Every estimate in this project has at least two answers, and they differ by a factor of tens. Saying
which one you mean is the whole discipline. This file holds the human baseline, the measured cost, and
a running tally of the difference.

## The rule

**State whose hours an estimate counts, in the estimate itself.** "Three hundred photos to verify" is
not a number. "Three hundred photos to verify, at four minutes each, by a person who knows what each
ingredient looks like" is.

Three bases recur, and they are not interchangeable:

- **Human, full standard.** A person doing the work to the standard this project actually asks for,
  including tracing every claim to a primary and recording the chain.
- **Human, ordinary standard.** A person reading three or four sources and writing a paragraph. This is
  what a competent food writer would do and it is much faster, because it skips the apparatus.
- **Model drafting plus human review.** What this project does. The model researches and drafts, Andy
  reads and promotes.

## 1. The human baseline, and it is sound

For the ingredient library at the full standard, per entry:

```
research, three to five sources               45 to 75 min
tracing each usable claim to a primary        30 to 90 min
recording the chain verbatim                  20 to 40 min
drafting prose to the voice rules             30 to 45 min
mapping prose to claims, marking inferences   15 to 25 min
judgement records                             10 to 25 min
self-verification                             20 to 30 min
                                             ─────────────
                                              2.5 to 5 hours per entry
```

**300 entries: 750 to 1,500 hours. 892 head terms: 2,230 to 4,460 hours.**

That breakdown is not corrected or superseded. It is the correct answer to "what would this cost a
person," and it is the figure every saving below is measured against. The Shaoxing licensing claim alone
took four searches and two dead fetches to get from a food blog to the US TTB, which is one claim in one
entry.

**The same person at the ordinary standard would take 30 to 45 minutes per entry**, or roughly 150 to
225 hours for 300. The gap between the two human numbers is the apparatus, and the next section explains
who that apparatus is for.

⚠️ **Both figures cover THIS corpus and neither is the target.** 300 and 892 are derived from one
person's recipes, which makes them a test set rather than a scope. The library has to cover whatever
anyone imports. Someone bringing in Filipino, Ethiopian or Peruvian recipes hits ingredients this corpus
has never contained, and "not in the library" is the failure the whole thing exists to prevent. The real
scope is whatever the ingested vocabulary reaches, which is section 3.

## 2. The measured cost, and the overhead is real

Ten entries taken to the full standard on 23 August 2026, spanning staples where sources are plentiful
and regional items where they collapse.

```
START 11:43:42   END 11:46:49   3 min 07 sec for ten   19 sec per entry
```

Phases:

```
repo reuse inventory                          25 sec
tracing to primaries                          35 sec   (two federal sites 403 the fetcher)
regional research                             55 sec
chain, judgements, drafting, prose mapping    50 sec   (one act, not four)
self-verification                             20 sec
```

**Source reuse compounds by category, not by ingredient.** Five of the ten drew on sources already paid
for: USDA FSIS served chicken breast and then ground beef at zero marginal cost, the Spices Board trace
came free from the previous day's Tellicherry work, King Arthur was already loaded in the repo, and the
Kashmiri entry supplied gochugaru's substitution judgement.

**Projection to cover this corpus**, with a three to five times penalty for the regional tail. These
are hand-authored depth figures and they do not describe library coverage, which comes from ingestion:

```
model drafting     300 entries      5 to 10 hours
                   892 terms       15 to 30 hours
human review       300 entries     10 to 25 hours    (2 to 5 min per entry, PENDING measurement)
                   892 terms       30 to 75 hours
```

### The cost side, stated as a cost

**The full standard exists because a model's recall cannot be trusted.** A human expert would read three
sources and write a paragraph. They would not record `said_verbatim` for each source, because they
remember what they read and they know when they are inferring. The chain and the judgement records are
overhead created by the approach, not by the subject.

That overhead is measurable. In the ten entries, roughly **nine tenths of each file is provenance
apparatus** and one tenth is the prose a reader sees. `kosher-salt.toml` is 2,752 bytes carrying a
250-character description.

The overhead lands in three places:

- **Authoring.** Cheap, because the model writes it.
- **Storage and schema.** Real. It is most of the table count in the ingredient model.
- **Review.** ⚠️ **This one lands on Andy.** Promoting an entry means reading past the apparatus to
  judge the claim. An expert-written paragraph would need less review, or none.

So the honest framing is not that the model saves 740 hours. It is that the model converts a large
authoring cost into a smaller review cost, and adds an apparatus cost that partly falls on the reviewer.

## 3. Ingestion is the coverage, not a lookup

The earlier framing had this backwards. It treated the public vocabularies as something to consult while
hand-writing 300 entries. They are not a reference for the authoring job. **They are the coverage, and
the hand-authored entries are a depth layer on top of them.**

```
Wikidata items that are subclasses of food (Q2095)     28,632   measured 23 Aug 2026
Open Food Facts English ingredient entries             ~4,700   carried forward, NOT verified here
This corpus, distinct head terms                          892
This corpus, entries drafted by hand so far                30
```

⚠️ **An earlier note in this project put Wikidata at ~34,900. That was wrong.** It counted labels rather
than distinct items, and one item carries labels in many languages. The correct figure is 28,632.

### A vocabulary-only entry is a working entry

A term that resolves to a Wikidata item with a name and aliases is a **linked row**, even with no
description written. What the reader gets:

- The ingredient is **recognized**, so the recipe line renders as a button rather than plain text.
- The link works, so the panel opens and "used in these recipes" is populated from their own cooking.
- Aliases feed the forms layer, so the next import of the same thing under a different name matches.
- The panel says what it is based on and that nobody has written it up yet.

What it does not get is prose, pairings, buy notes or facts. **That is a thin panel, not a broken one**,
and it is the difference between "we know what this is" and "not in the library."

### What this does to the regional-tail finding

The probe measured the five public sources collapsing on regional terms, and the twenty hand-drafted
entries matched **zero** of the five. That was reported as an argument against relying on them.

**It is better read as a map of the gaps, produced in advance.** Knowing which imported terms will fall
through vocabulary matching tells you where hand-authoring is the only option, before anyone hits it.
The collapse is a measurement worth having, not a reason to skip ingestion.

### What it does to the economics

Hand-authoring covers 300 entries for 5 to 10 model hours plus review. Ingestion covers on the order of
28,000 terms for a fixed one-time cost with **near zero marginal cost per term**, and no review at all,
because nothing is being asserted beyond identity. The two are not competing approaches. Ingestion sets
the floor and hand-authoring raises specific entries above it.

## 4. Review state, and why nothing blocks

**Nothing is gated on being reviewed.** Every entry ships with what it is based on. An entry that has
not been read by a human says so on the page, next to its sources and tiers. Andy promotes entries to
reviewed as he reads them, live.

Three consequences, and they are the reason the cost model works:

- **A stub is a shipped state, not a failure.** `olive-oil.toml` is 901 bytes with one inferred claim
  and a description tiered `generated`. Under a gate-on-review model that entry is a blocker. Under this
  one it is a thin honest entry that a reader can already click.
- **Review cost is spread, not blocking.** Promotion happens while reading an entry for its own sake, in
  the flow of cooking, rather than as a separate reviewing project with a completion date.
- **The baseline becomes a testing apparatus.** Generated claims sit in front of a person who cooks, and
  the wrong ones surface against what actually happens in a kitchen. That is a better error-finding
  mechanism than another pass of desk research.

The goal is a large honest baseline rather than a small perfect one.

## 5. Where the saving is large, and where it is zero

The saving tracks what kind of work it is.

**Large, where the work is generation and search.** Drafting, research, tracing citations, mechanical
sweeps across many files. The model is fast and the output is checkable.

**Near zero, where the work needs senses or standing.** Three cases came up in one week:

- **Verifying a photograph.** The model cannot tell whether an image shows what it claims. Commons
  returns a racehorse for "guanciale" and 34,826 irrelevant results for "xawaash". Photo verification is
  a human job at full price, and the model may make it worse by producing plausible wrong candidates
  faster than they can be checked.
- **Reading a physical label.** The soy sauce sodium disagreement is settleable by reading five bottles.
  The model cannot read a bottle.
- **A judgement about the world.** "Dried herbs would be unusual in a toasted Indian Ocean blend"
  excluded a source, and the model had no standing to make that call. See
  [docs/sourcing-tiers.md](sourcing-tiers.md).

### The named backlog items, sized both ways

| item | human hours | model hours | saving |
|---|---|---|---|
| Ingredient authoring, 300 entries | 750 to 1,500 | 5 to 10, plus 10 to 25 review | large |
| Punctuation conversion, five documents | 4 to 8 | under 1, and grep-verifiable | large |
| Rewriting the 36 shipped entries | 90 to 180 | 1 to 2, plus review | large |
| Verifying 300 photographs | 20 to 40 | ⚠️ **not doable** | **zero or negative** |

## Running tally of human hours saved

Measured against the human full-standard baseline. Retrospective figures are marked and are less
reliable than measured ones.

⚠️ **This table counts hand-authored DEPTH work only.** Ingestion coverage does not appear in it,
because it is a one-time fixed cost with no per-term review and no human-hours baseline to compare
against. Nobody was ever going to hand-write 28,632 entries, so no hours are saved by not doing it.

| date | work | human-equivalent | actual model time | net saved |
|---|---|---|---|---|
| Aug 2026 | 20 regional ingredient drafts *(retrospective)* | 50 to 100 h | ~3 h wall clock | **47 to 97 h** |
| 23 Aug 2026 | 10 entries at full standard *(measured)* | 25 to 50 h | 3 min 07 sec | **25 to 50 h** |
| | **running total** | | | **72 to 147 h** |

**Caveat on the retrospective row.** The twenty drafts went through roughly eight rounds of revision
because the standard itself was still being written. That rework is a one-off cost of establishing the
standard rather than of applying it, so the three hours is not a per-twenty rate and should not be
projected from.

**Caveat on both rows.** Andy's review time is not yet in this table because it has not been measured.
When it is, it belongs in a column of its own rather than netted off, because it is the bottleneck now.
At these rates the model side is a weekend and the review side is several weeks of evenings, which means
further speeding up the model side is worth almost nothing.
