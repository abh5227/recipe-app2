# Measuring the premise: six times the shape of the data was assumed

`docs/estimating.md` records a lesson about arithmetic that was right and a label that was
wrong. This is the same lesson one level down. Six defects in a single ingestion, all one
error class: **an assumption about the SHAPE of the data, made instead of a measurement.**

Every one produced working code. Every one was caught by real data. Every one would have
been caught earlier by looking first.

## The six

**1. An ASCII slug erased every non-Latin name.** The Open Food Facts text parser derived
an identifier with `re.sub(r'[^a-z0-9]+', '-', name.lower())`. Ten Bulgarian and two
Russian blocks reduced to the ids `bg:` and `ru:` and collided. **The assumption was that
names are Latin script**, inside ingestion built to fix an anglocentric gap.

**2. A derived identifier assumed the source was self-consistent.** Replacing the slug
with the plain first name still collided, because Open Food Facts duplicates entries.
`little-millet` and `kodo-millet` each appear twice under `< en: millet`. **The assumption
was that a source does not repeat itself.** It does, and Wikidata does too, where xawaash
exists as two items.

**3. `lang:word:pos` assumed one record per word.** English Wiktionary splits a word by
etymology and wiktextract emits one record for each, so `en:may:verb` exists under
etymology 2 and `en:may:noun` under etymology 3. Measured on the stored payload, 216 of
1,924 food keys collided, about 11 percent. **The assumption was that a natural key
existed.**

**4. The food filter assumed food is tagged as food.** English Wiktionary categorises by
grammar and etymology, never by domain. `gochugaru` carries only "English lemmas",
"English nouns" and "English terms borrowed from Korean". A topic filter kept 16,931
entries, ran clean, satisfied its invariant, and **missed nine of the ten terms the source
was added for**. This is the worst of the six, because nothing failed.

**5. The coverage check assumed aliases live in the name column.** Having built a label
table precisely so that aliases live in it, the ten-term check queried `entry.name`.
`za'atar` reported missing while sitting in the store as a form label on `zaatar`,
alongside `za'tar`, `zatar` and Arabic and Syriac translations. **The assumption was about
the shape of the answer rather than of the data.**

**6. A constant was trusted over the catalogue.** `src_url = url or WIKT_URL` meant asking
for the Chinese edition re-fetched 2.83 GB of the English dump and stored it under the
Chinese dataset. `source_catalogue.url` is the record of what a dataset IS, and reaching
past it to a module constant makes that record a decoration. **The assumption was that the
default was right.**

## What they have in common

None was a logic error. Each was a **premise** about how the data is shaped, held
confidently enough that it never got checked: names are Latin, sources do not duplicate, a
natural key exists, food is labeled food, answers live where you put them, defaults are
right.

The cost was uneven and not proportional to the mistake. Defect 4 cost the least to write
and the most to find, since it produced a clean run and a wrong answer. Defect 1 announced
itself immediately with a constraint violation.

**Two of the six were caught only because the raw payload is stored.** Defects 3 and 4
were diagnosed by re-reading 2.83 GB already on disk, with no network access. The
whole-payload rule was argued for on license grounds and paid for itself twice within an
hour on a completely different one.

## The rule this produces

**Measure the shape before writing the parser, not after the constraint fires.**

Concretely, before a filter or a key is committed to:

- Count how many records the candidate key is actually unique over.
- Count what fraction of records carry the field the filter depends on.
- Take the terms the source is being added for and check that the filter keeps them.
- Report the expected yield before running, so a wrong number is visible as a prediction
  rather than as a result.

This is not a general call for more caution. It is four counts, each of which costs one
pass over data already on disk.

## The one that went right

The Chinese Wiktionary edition was probed before anything was parsed. The probe showed
`topics` present on zero entries, categories that are grammatical rather than semantic, and
99.9 percent of glosses in Chinese. **The English filter would have kept 386 entries of
2,916,811 from a 225 MB download and looked like a working ingest.** The union that
replaced it kept 327,964, inside the 288,183 to 332,697 bound the probe predicted.

That is the same class of defect as the other six, caught before it happened, for the cost
of one scan.

## Why this sits beside the estimating note

[docs/estimating.md](estimating.md) is about a projection that was arithmetically sound and
labeled wrong, so the fix was to state whose hours were being counted rather than to redo
the sums. This note is about parsers that were logically sound and premised wrong, so the
fix is to state what shape the data has rather than to debug the code.

**Both are failures of the premise, not of the work done on top of it, and both are
invisible from inside the work.** A projection cannot tell you it counted the wrong
person's hours. A filter cannot tell you it kept the wrong 16,931 rows.
