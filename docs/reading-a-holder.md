# Reading a holder: three shapes that a member count cannot see

Extraction reads a big row, groups its names into concepts, and creates a row for each concept
that is an ingredient. The sort that picks which row to read next is the English-name count.

This file records three shapes where that sort is wrong, or where the reading has nothing to
reach. Each is a class rather than a case, and each was found by being wrong about a specific
row first. It is a record for the next extraction pass, not a proposal.

## 1. The cultivar register, which looks exactly like a culinary family

A **culinary family** holds many things under one name. `sausage` held bratwurst, longaniza,
andouille and lap cheong, which are nineteen different products a shop sells separately.

A **cultivar register** holds one thing under many names. `Riesling` carries 148 names, 116 of
them English, and every one is the same grape. Rhine Riesling, Weisser Riesling, Johannisberg
Riesling, Rajnski Rizling, Ryzlink Rynsky, Klingelberger, Petracine, Rossling. That is the
Vitis International Variety Catalogue synonym list, arriving as Wikidata aliases.

**Both present as a large holder and the member count cannot separate them.** Riesling was
marked as a family from the scan sheet on exactly the signal that found sausage.

### The existing cut structurally cannot reach this

`ingredient_cuts.cultivar_register` already takes 603 rows. Its rule requires the entry to
subclass a Wikidata cultivar class, to have one source, and **to have no variations at all**.
The threshold note explains why the ceiling is zero. At one variation it starts taking real
ingredients such as Altländer Pfannkuchenapfel and Big Jim pepper.

Measured on the kept library:

```
kept rows subclassing a Wikidata cultivar or variety class      571
  with 40 or more English names                                   7
  with 20 to 39                                                    7
  with 10 to 19                                                   17
  with 1 to 9                                                    506
  with none                                                       34
rows the zero-variation ceiling can reach, of the 537 named        0
```

**The cut protects the bottom of the distribution and the problem is at the top.** A register
entry nobody has heard of has no synonyms. A famous one has a hundred, which is precisely why
it reads as a family.

### And the signal does not make the call either

The 14 rows above the 20-English-name scan threshold that subclass a cultivar class carry 34
recipe lines between them. Reading them, they do not split cleanly:

```
Riesling  116 EN   0 lines    a synonym list, no members
Carignan   88 EN   0 lines    a synonym list, no members
Cayetana   68 EN   0 lines    a synonym list, no members
piri piri  52 EN   1 line     a distinct product a cook buys
bell pepper 43 EN  8 lines    color is a real distinction
cayenne    24 EN  24 lines    a distinct product, and the heaviest of the fourteen
```

⚠️ **Riesling and cayenne pepper match the same signal and want opposite answers.** So the
signal identifies the population that needs reading and cannot do the reading. Fourteen rows
is small enough to read by hand, which is the useful outcome rather than a rule.

## 2. The missing set, which extraction cannot reach because there is nothing to reach

The Riesling row holds no members. The set that would have been its members is **absent from
the library entirely**.

Kabinett, Spätlese, Auslese, Beerenauslese, Trockenbeerenauslese and Prädikatswein are the
German ripeness levels. They are printed on bottles, they are what the wine is sold as, and
they are real distinctions. Every one of them sits on **zero rows**.

⚠️ **They are not cut, and that is the part worth knowing.** They are in `join.db` with four
to nine bucket members each, from Wikidata, en.wikipedia and Wiktionary. Q353061 (Kabinett) is
in the loaded food vocabulary. The row builder never made a row for it.

**A term that never became a row is invisible to every downstream tool.** It is not on the cut
sheet, because a cut records what it removed from a row that existed. It is not on the scan
sheet, because that lists holders. Extraction cannot surface it, because extraction reads
rows. Nothing in the pipeline says its name.

```
distinct entries in join.db                    187,605
  became a row                                  11,163
  never became a row                           176,442   94.0%
```

That 94 percent is mostly correct. Most of the join is Wiktionary word senses in languages
nobody will cook in. **The class is the exceptions, and they have to be found by asking about
a term, not by reading the library.**

### The one that is worth 29 recipe lines

```
unanswered recipe lines                         1,735 over 1,365 distinct terms
  the largest single unanswered term            baking soda, 29 lines
```

**`baking soda` is the heaviest unanswered term in the corpus and the library has no row for
sodium bicarbonate at all.** Not under `baking soda`, not under `bicarbonate of soda`, not
under `sodium bicarbonate`, not under `sodium hydrogen carbonate`. The only source that names
it is AGROVOC `c_26825`, which never became a row.

For scale, 29 lines would place it fourth in the corpus behind salt at 52, sugar at 44 and
water at 33, all three of which were hand-authored for exactly this reason.

⚠️ **It is the only term in the top 20 unanswered that is in `join.db`.** The other nineteen
are phrases the parser did not split, such as "garlic cloves, minced" and "sea salt and
freshly ground black pepper". Those are a parsing job. This one is a library job, and no
amount of holder reading reaches it.

## 3. The seedless member, where the concept is real and no seed isolates it

Extraction seeds a new row from the entries that carry its names, so the row arrives with
provenance instead of as a bare string. That needs the member to have an entry somewhere.

Three members read this session do not:

```
sauce verte    named only on Wikidata Q699382, which IS the green sauce row,
               and on en.wikipedia redirect 714128, which is that row's article
Grüne Soße     the same two, and nothing else
teuk trey      named only on en.wikipedia redirect 46482, the Fish sauce article
```

Every available seed is the parent, so seeding drags the whole family onto the child. This is
the parent-in-the-child's-bucket trap with no way out rather than with a workaround.

Measured across the library: **134 of 4,936 English orphan-primary names on kept rows, 2.7
percent**, have no entry outside their parent carrying the name.

### What to do about it depends on what the thin row leaves behind, and that is measurable

An unseeded row carries one name and wins it from the parent under rule 4. The question is how
many spellings of the same concept stay on the parent.

```
sauce verte    0 spellings stay behind         created as a thin row
teuk trey      1 stays, "Cambodian fish sauce" created as a thin row
Grüne Soße     9 stay, including the protected Frankfurter Grüne Soße   NOT created
```

⚠️ **Nine is not a thin row, it is a split concept.** A `Grüne Soße` row that does not carry
`Frankfurter Grüne Soße`, `Grüne Sauce`, `Grie Soß` or `Gruene Sosse` is worse than no row,
because a reader now gets the parent for four spellings and the child for one.

**Count the spellings before writing the row.** Zero or one is a thin row. Nine is a decision
about whether to seed on the parent's article and trim the siblings back out, which nothing in
the pipeline does yet and which would set a precedent for every future extraction.

### Grüne Soße: settled, and the ruling is the useful part

**Decided on 25 August 2026. No row.** Two reasons, and they are separate.

**The row would be wrong on its own terms.** A `Grüne Soße` row carrying one name leaves
`Frankfurter Grüne Soße`, `Frankfurter Grüne Sauce`, `Frankfurter Grie Soß`, `Grüne Sauce`,
`Grüne Sosse`, `Gruene Sosse`, `Gruene sosse`, `Grie Soß` and `Grie soß` on the parent. A
reader then gets the child for one spelling and the parent for nine, including the protected
designation, which is the name that most identifies the thing. **That is a split concept, and
it reads worse than no row at all.**

**And the fix would set a precedent in the wrong place.** Seeding on the parent's article and
trimming the siblings back out is a new pattern. It would apply to every future extraction
where the member has no entry of its own, which is 134 names. ⚠️ **A zero-line term is the
worst possible place to establish a pattern that size.** Nothing about this row tests whether
the pattern is right, because nothing reaches it.

The general rule this leaves: **a seedless member is created only when the spelling count that
stays behind is zero or one.** Above that, record it here and leave the parent whole. Reopen it
when a seedless member turns up that carries recipe lines, because that is the case worth
paying a precedent for.


## 4. The article title that is not a name, and the seven rules that catch it

Some names on a row describe a **topic** rather than name a food. `Are hotdogs sandwiches?`,
`History of pasta`, `List of Mexican cheeses`, `Pancake race`, `Instituto do Vinho do Porto`.

⚠️ **Every mechanical cut before this one keys on a property these do not have.** They are
well-formed English. Not initialisms, not symbols, not dead languages, not translations. The
only thing they share is shape, so the rule has to key on shape.

Population: names on a kept row supplied **only** by an en.wikipedia redirect, 13,223 of them.
Recall was 11 of the 12 hot dog debate titles removed by hand, the miss being `Ketchup on hot
dogs`. Each rule was read in full and shipped only at 100 percent.

```
list_or_superlative   31   List of Mexican cheeses, World's most expensive hot dog
history_of            29   History of pasta, Taco history, Evolutionary history of sharks
event_or_activity     14   Pancake race, Cider festival, Meat eating, Dog eating
debate_or_claim        7   Hot dogs are sandwiches, How chocolate is made
question_mark          2   Are hotdogs sandwiches?
institution            6   Instituto do Vinho do Porto, McIlhenny Company, Big Mac Museum
commercial_venue       7   Port Wine lodges, Kebab restaurant, Bleach (brand)
                     ───
                      96   names, 0 recipe lines
```

### Three rules were rejected or narrowed, and the rejections are the useful part

**`culture or cuisine` was rejected outright at 43 percent.** ⚠️ **`X (cuisine)` is Wikipedia
disambiguating a real name, not marking a topic.** `Bacalao (cuisine)`, `Kielbasa (Polish
cuisine)`, `Mirepoix (cuisine)`, `Bumbu (cuisine)`, `Salsa (Mexican cuisine)` and `Tape
(Indonesian cuisine)` are all real foods. And `Cheese culture` and `Starter culture` are
ingredients someone buys.

**`X in <Country>` was rejected at 91 percent**, which sounds shippable and is not. All six
misses are **regional products the library exists to know**: `Herbs of Provence`, `Red onion of
Tropea`, `Pecorino of Carmasciano`, `Blanquette of South Australia`. Losing four protected
regional foods to catch sixty-four topic titles is the wrong trade at any precision.

**`commercial` was narrowed twice.** The first form keyed on `mix` and took `Cake mix`,
`Seasoning mix`, `Chili mix`, `Herb mix`, `Whipped topping mix` and `Pancake mix`, which are
products on a shelf. The second keyed on bare `brand` and took `Brand flakes`, an en.wikipedia
misspelling redirect for bran flakes, which is a useful match of exactly the kind the
cappuccino misspellings are kept for.

**`institution` was narrowed and it cost three correct catches.** The wider form included
`Foods`, which also took `Raw Foods` and `Live Foods`. So `Birds Eye Foods`, `Birdseye Frozen
Foods` and `Sriracha sauce (Huy Fong Foods)` are left in rather than taken by a rule at 82
percent.

**The pattern: seven narrow rules at 100 percent beat one broad rule at 85.** A rule that is
wrong about one regional cheese costs more than a rule that misses sixty topic titles, because
the topic titles answer nothing and the cheese is the product.

⚠️ On scoring any detector built after a cleanup, see the cleanup-paradox note at the head of
`ingredient_cuts.py`. The article-title rules could be scored only because their twelve
positives were recorded verbatim in `hand_removals.csv` rather than merely deleted.
