# The relationship the row model cannot hold

Every row in the ingredient library is flat. A row has a canonical name, a set of variations
with provenance, sources, languages and flags. **Nothing records that one row is a kind of
another, or a form of another, or the same thing at a different strength.**

This file exists because that gap has surfaced five times in five different shapes, and each
time it was patched with a flag rather than a model. It is a record for whoever builds the
model, not a proposal.

## The five surfacings, in the order they appeared

**1. The general terms had no row at all.** `salt` was 52 recipe lines and 32 dependents and
the library had nothing for it, so a line saying salt reached `table salt` or `sea salt`,
which is the wrong specific rather than the general thing. Six rows were hand-authored to fix
it: salt, sugar, water, egg, oil, pepper. `authored_rows.csv` says in its own header that
those six are flat and that nothing records `kosher salt` as a specific of `salt`.

**2. The strength shape, in two forms.** 148 rows carry several strengths at once and 148
families spread one strength each across 402 rows. `tamarind paste` holds paste, concentrate,
extract, water and juice on one row, so a reader gets a plausible answer at the wrong ratio.
`mark_strength` marks both forms and can express neither.

**3. Extraction, which is what most of this work has been.** A category row holds real
ingredients as names. `fortified wine` held port, sherry, Madeira, Marsala and vermouth and
none had a row. `cinnamon` held three different species. `Foeniculum vulgare` held dill,
fenugreek and cumin. Extraction creates the child row and the link is still not recorded, so
the reason a row exists lives in a sentence in `authored_rows.csv`.

**4. Members that need a parent instead.** `bread` at 4 recipe lines sat on `cereal` and on
`roti`. `pasta` was carried by twelve rows and owned by none. `nutmeg` at 2 lines had a wine
for its only holder. Those are not children needing a parent, they are parents needing to
exist, and the flat model cannot tell the two cases apart before someone reads them.

**5. ⚠️ The tomato family, which is the clearest case and is not the worst.**

## Tomato: three independent axes, and the sources have enumerated six combinations

62 kept rows mention tomato. **Exactly one carries a recipe line.**

The rows vary on three axes at once, and the axes are independent:

```
  cultivar     Roma, San Marzano, cherry, plum, beefsteak, Campari, Heirloom, grape,
               Pear, vine, Santorini, Hanover, blue, celebrity, garden peach, White
               Queen, Vittoria, Rivolo                                    18 rows, 0 lines
  cut          paste, purée, peeled, crushed, mashed, cubes, pulp, powder        8 rows
  preservation canned, pickled, sun-dried, fresh, stewed                         5 rows
```

35 recipe lines mention tomato, and they state the axes independently. `canned crushed
tomato` and `28 oz Whole Canned Tomatoes, pureed` state two. `Roma tomatoes, finely diced`
states a cultivar and a cut and no preservation.

**⚠️ The corpus asks for combinations no row holds.** `Whole Peeled Tomatoes` at 3 lines,
`diced tomatoes` at 6 across spellings, `canned crushed tomato`. Meanwhile 18 cultivar rows
carry nothing at all.

**And the sources have already begun multiplying the axes out, arbitrarily.** Six combination
rows exist: `Canned concentrated tomato paste`, `Canned double concentrate tomato paste`,
`crushed peeled tomato`, `pickled sun-dried tomato`, `diced tomatoes in tomato juice`,
`concentrated tomato purée`. Six of the roughly 800 the three axes allow, chosen by whichever
source happened to file them.

**A row per combination is not the answer.** No rows have been created for this family.

## ⚠️ Tomato is not the worst, and the guess that it was is wrong

Measured over every head noun shared by six or more kept rows, using four axis word lists
plus a capitalized-modifier test for cultivar or origin:

```
  families varying on 2 axes    49
  families varying on 3 axes    27
  families varying on 4 axes    15
  families varying on 5 axes     9
```

Tomato is one of the nine, and it is the smallest of them. The arithmetic elsewhere is worse
by an order of magnitude:

```
  family    rows   distinct values per axis                              combinations
  cheese     163   cultivar 80, strength 7, preservation 5, color 4, cut 3      33,600
  juice      145   cultivar 11, color 6, preservation 5, cut 3                     990
  flour      143   color 8, cultivar 7, strength 5, cut 3                          840
  tomato      36   cultivar 10, color 5, preservation 4, cut 2, strength 2         800
  rice        99   cultivar 25, color 4, strength 2, preservation 2                400
  milk       104   preservation 6, strength 5, cultivar 5, cut 2                   300
  oil        260   cultivar 20, color 4, cut 3                                     240
  cream       44   strength 6, preservation 4, cultivar 3, cut 2                   144
  egg         49   preservation 5, cultivar 4, cut 2                                40
  sugar       43   color 3, cultivar 3, preservation 2, cut 2                       36
```

**Cheese already has 163 rows against 33,600 possible combinations**, which is a quarter of a
percent of the space enumerated, chosen by nobody. Tomato at 36 of 800 is four and a half
percent, so tomato is the family where the gap is easiest to SEE rather than the family where
it is largest.

⚠️ **The axis word lists are hand-written and the cultivar test is a heuristic**, so these
counts describe the shape rather than measure it exactly. A capitalized modifier that is not
an axis word reads as a cultivar or origin, which catches `San Marzano` and also catches any
proper noun. Treat the ordering as sound and the absolute numbers as approximate.

## What a model would have to hold

Stated as requirements rather than as a design, since the design is not this file's job.

- **is a kind of.** `cassia` is a kind of `cinnamon`. `panko` is a kind of `breadcrumbs`.
- **is a form of, with the ratio.** `ground cinnamon` is `cinnamon`, ground. The ratio is what
  makes a substitution safe and it is the part a flat row loses.
- **is the same thing at another strength.** `tomato paste` and `tomato purée` and
  `tomato passata`, with what converts between them.
- **varies on an axis that another row also varies on**, independently. This is the tomato
  requirement and it is the one no flag has ever approximated.
- **is the general term for.** The inverse of the first, and the one the six authored rows
  needed.

Honey with 37 varietal children and sesame oil with 4 distinct products are different
relationships, and nothing measured so far separates them. That is why the link has not been
built yet, and it is a good reason rather than an excuse. Building it on one family's shape
means building it twice.
