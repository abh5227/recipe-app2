# vocab/ — the classification model the ingredient library is built on

Eleven files. Read the next section before deleting anything here. Five of them came from live
fetches that would not reproduce, six are hand-reviewed decisions, and one is derived.

## What cannot be regenerated, and why it is committed

`wikidata-kinds.json`, `wikidata-superclasses.json`, `wikidata-class-labels.json` and
`wikidata-kind-anchors.json` came from roughly 80 live Wikidata fetches on 23 August 2026,
across an eight-round fixpoint closure that resolved 3,725 class items. Wikidata has moved
since.

**Re-running the fetch would produce a different model.** Every count in
`ingredient_cuts.py`, every threshold measured against the grouping, and the 11,153-row
library itself would shift. These are **inputs** to `build_library.py`, not outputs of it,
and the same `_README` warning is inside each file so it survives losing this page.

`off-taxonomy-tree.json` is the exception. It is derived from `sources.db` and
`build_library.py` rebuilds it when that file is present. It is committed because
`sources.db` is 5.18 GB and git-ignored, so a fresh clone would need a 5 GB refetch to
derive 262 KB.

## The files

| file | entries | what it holds |
| --- | --- | --- |
| `wikidata-kinds.json` | 28,630 | supertype plus subtypes per food item, with the anchor that reached each kind |
| `wikidata-superclasses.json` | 32,146 | item to the classes it names as a superclass |
| `wikidata-class-labels.json` | 27,612 | class QID to its English label |
| `wikidata-kind-anchors.json` | 4 keys | the anchor QIDs per kind, their priority order, the generic fallback, the hop cap |
| `off-taxonomy-tree.json` | 5,745 | the Open Food Facts parent and child tree |
| `dish-vocab.csv` | 800 | the dish FORM vocabulary, with a `keep` column and `style-not-form` flags |
| `base-vocab.csv` | 147 | the BASE vocabulary, what a dish is made of, with `keep` and `EXCLUDE` |
| `method-vocab.csv` | 63 | the METHOD vocabulary, participles only |
| `diet-vocab.csv` | 27 | the DIET vocabulary |
| `structural-vocab.csv` | 15 | the STRUCTURAL vocabulary |
| `appliance-vocab.csv` | 36 | the APPLIANCE vocabulary |

Total 6.2 MB.

## ⚠️ The six dish vocabularies, and why they moved here

`dish_facets.py` reads all six at import. They carry a `keep` column the owner edited by hand, one
row at a time, and the rejections carry as much meaning as the entries. `light` is out of diet at
83.3% ambiguous. `dump` is out of structural because 86% of its 461 titles are `Dump Cake`. Bare
verb stems are out of method because `dip` is a trailing noun 96% of the time. **None of that
reproduces from anything.**

⚠️ **They were read from `previews/` first, which is gitignored.** That made `dish_facets.py`
unimportable on a fresh clone and the whole dish extraction unreproducible from the repository
alone. The corpus may be absent, since it is 2.29 GB and licensed derive-only. **The decisions
about it may not.** Same test as everything else on this page.

## How the grouping was built

A nearest-anchor breadth-first walk up P279 with a **two-hop cap**, trying specific anchors
before a generic food fallback. A full transitive closure was tried first and collapsed the
grouping to 97.5% "Brand or trademark", which is why the cap exists.

Multiple kinds on one item is the **dual nature, not an error**. Ingredient plus Taxon is
gochugaru. Ingredient plus Dish is holy trinity.

## Three known holes, stated because silence reads as a pass

**"Cultivar or plant variety" matched zero of the 28,630 items.** The cultivar exclusion
never fired, so roughly 1,176 cultivars entered the library under the strongest rule. The
`cultivar_register` cut in `ingredient_cuts.py` is a patch over this, not a fix.

**Q177, pizza, carries no English label.** It has a German label and English aliases. Every
English-label lookup silently missed 157 references until this was found. Absence of a label
is not absence of an item.

**7,187 items carry no kind at all.** Rule 2 in `build_library.py` reaches 487 of them by
cross-checking Open Food Facts, and 6,700 are still out. doubanjiang is one of the 6,700 and
is in the library only as a hand-written override.
