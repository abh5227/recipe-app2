# vocab/ — the classification model the ingredient library is built on

Five files. Four of them **cannot be regenerated** and one can. Read the next section
before deleting anything here.

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

Total 6.1 MB.

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
