# What the ingredient library is for

The standing purpose. Read this before writing any rule that admits, cuts, renames, or merges a
library row.

## The library is a list of cooking-facing ingredient names

A row is something a person buys or cooks with. Garlic, cilantro, black pepper, kosher salt,
gochugaru, fish sauce.

It exists to serve **other people's recipe imports across every cuisine**, Filipino, Ethiopian,
Peruvian, anything. It is not scoped to the recipes in this repo. Those 298 recipes are a **test
set** for checking that matching works. They are never the definition of what belongs.

## The five sources were gathered for names, not for concepts

Wikidata, Open Food Facts, AGROVOC, Wikipedia and Wiktionary were harvested for one thing:
**names**. Every spelling, language, and alternate name a real ingredient goes by, so that whatever
string an import arrives in resolves to the one right ingredient. "coriander", "cilantro",
"Coriandrum sativum", "香菜", a misspelling.

The sources are **provenance for where a name came from**. They were never meant to define the list
of ingredients. **A concept a source happened to contain is not, by that fact, an ingredient.**

Three consequences follow, and they govern every rule written after this.

## A real ingredient's name in any language or in Latin is an alias, not a row

"Allium sativum" is a name for garlic. It belongs as an alias on the garlic row, kept so a Latin
import still resolves and its provenance retained, not as a second row competing with garlic.

A row's canonical is **the common name a cook writes**. Every other name the sources carried for
that same ingredient folds onto it as an alias. When one ingredient exists as both a common-name row
and a binomial or other-language row, they collapse to **one** row, common name as canonical, the
rest as aliases.

**The common name wins the canonical even when the binomial carries more aliases.** The aliases come
along. The display name does not.

## The display name defaults to US English, and speaker population only breaks match ties

Every row carries many names across many languages. Two different jobs use that pile of names, and
they are not the same job.

**The canonical (what the app displays) defaults to US English.** When an ingredient has more than one
name, the display name is the US-English name the ingredient actually goes by. This is a flat default,
not a computation.

- When two names are both everyday English, US English wins. "cilantro" not "coriander", "eggplant"
  not "aubergine", "scallion" not "spring onion". The other name stays on the row as an alias so a
  recipe written the other way still resolves. The app just shows the US one.
- **US English means the real US-English name, not a translation into English.** "gochugaru" stays
  "gochugaru". It does not become "Korean chili powder", because the name an American cook actually
  writes for it is the borrowed word. The same holds for miso, tahini, harissa, mirin. Defaulting to
  US English selects among the names a thing is really called. It never translates an ingredient out
  of the name a cuisine uses.
- **Where an ingredient has no US-English name at all, the canonical is simply the name it actually
  goes by** in its own language. The rule is US English where one exists, otherwise the real name.
  Nothing is required to have an English name, and "make one up by translating" is exactly the failure
  the point above rules out.

**Speaker population is a separate, narrower signal, and it is only for breaking a match tie.** When a
recipe line could resolve to two different rows, weight toward the reading the app's users are more
likely to have meant. It ranks nothing on the display side and it never decides whether a row
survives. A rare-language ingredient is exactly the kind of thing another person will import, so
speaker population must never be used to drop a row or a name for being in a small language.

## A concept that is not a cooking ingredient is not a row at all

A mango cultivar reached through a homograph. An economics concept reached through a Catalan word. A
mushroom reached through a German color name. A Wikipedia article title like "Coffee in Italy". A
grape's hundred-name synonym register standing as its own row. None is something a person cooks
with. They are in the data only because a source contained them and the intake admitted them. They
come out.

## Keep all real cooking ingredients

**The default is keep.**

Basic food knowledge is enough to tell garlic from a mango cultivar. Do not over-cut.

**Do not use recipe-line count as a cut signal.** A real ingredient nobody in these 298 recipes
happens to use, a regional spice or an obscure sauce, stays, because it will be in someone else's
import. A zero-line row is evidence about this corpus and never about the row. See
[docs/parent-child-gap.md](parent-child-gap.md) for the corpus-as-target error in full.

The only things that leave are:

- concepts that are not cooking ingredients, and
- rows that are really just an other-language or Latin **name** for an ingredient that already has a
  common-name row, and those become **aliases**. They do not disappear.

## What this does not tell you how to do

Stated so that a rule written from the section above does not get read as more decisive than it is.

**There is no merge operation.** `apply_renames` refuses a rename whose target is another kept row's
canonical, and says so in the refusal text. `resolve_borrowed` moves a name and never a row.
`hand_removals.csv` removes a name from a row. `ingredient_cuts.py` cuts a row and keeps nothing.
Folding row A's names onto row B and retiring A is machinery that does not exist yet.

**The US-English default picks a display name. It does not decide what counts as one ingredient.**
The default settles which name to show when an ingredient has several (US English, "cilantro" over
"coriander"). It does not settle whether two things are the same ingredient or two. Whole peppercorns
and ground black pepper are one ingredient by one reading and two by another, and no naming rule
decides that. It is a reading call about the food.

**A category is not an alias and reads like one.** The butter row carries "food paste" and the
peppercorn row carries "black pepper". Neither pair is a common name and its Latin twin.

**Shape does not find these.** Binomial shape alone was measured at 8.3% precision over a read 60,
95% confidence interval [3.6%, 18.1%]. The Latin language tag finds 123 rows and is right about
them. See `build_library.py::is_binomial`.
