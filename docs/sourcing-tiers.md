# Sourcing: tiers, gates, and why CITED means traced

Every fact the app states about an ingredient carries a tier and a set of axes beside it. They record
how the claim was established and what recourse a reader has, not how confident anyone feels. Features
choose what they will trust.

This extends the per-field provenance model sketched for the import pipeline, where AI-baseline fields
carry an "AI-generated, baseline" marker and a needs-sourcing flag. See the field-guide baseline notes
in [ROADMAP.md](../ROADMAP.md).

## The three tiers

**GENERATED.** A model's dated assertion, unverified. Useful as a stub so the library ships with
something in it. Never trusted by a feature where being wrong has a cost.

**CURATED.** A human judgement built on cited facts, or a fact resting on a page that asserts it rather
than on the work that established it. A named blog stating a number is CURATED, not CITED.

**CITED.** Traced to the body that made the measurement, wrote the rule, or recorded the word. **A link
is not a citation.** If the page you read is repeating someone else's finding, the citation is the
finding, and you have not reached it yet.

Facts are promoted on evidence and **never demoted silently.** A demotion is recorded with its reason.

Allergen, food-safety and storage-safety claims split two ways. Asserting that something is absent
requires CITED and fails closed. Flagging that something may be present fails toward the warning and
ships at any tier. The asymmetry is the whole rule and it has its own section below.

## The gates decide the tier

Credibility is not one impression. Splitting it into gates and scores is what stops the same signal
being weighed opposite ways on two different days.

**G1. Did you reach the body that established the claim, or a page repeating it?**
Fail caps the claim at CURATED until traced.

**G2. Is the source reachable now?**
A dead link cannot be checked by anyone, including you. Fail forbids CITED.
⚠️ A 403 to an automated fetcher is **not** a dead page. That is a tooling limit and belongs in
`cannot_assess`, not in this gate.

**G3. Does the source have an interest in the claim being true?**
Fail caps at CURATED **unless the specific figure matches a non-interested external reference.**

### The external-anchor exception, which is the whole point of G3

Two interested sources were weighed opposite ways before this rule existed, and the rule resolves them
prospectively rather than after the fact.

**Tellicherry passed G3.** Retailers selling the pepper at a premium all give the same millimetre
thresholds, and those thresholds match Spices Board grade names, which is an anchor outside the sellers.
⚠️ It still fails **G1**, because every one of those retailers is restating a specification held at
AGMARK or BIS. Passing one gate does not carry a claim. Tellicherry is CURATED.

**The umami figure failed.** A body founded by the MSG manufacturer was the only place the number
appeared in that form. No external anchor existed.

## The scores decide whether to publish, never the tier

| signal | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- |
| **S1 proximity** | anonymous | named author, no citation | named author, cites the primary | the body that measured or regulated it |
| **S2 domain specificity** | general reference | food-general | specific to this ingredient or cuisine | |
| **S3 observed corroboration** | one source | two agreeing | three or more agreeing | three or more agreeing with competing interests |
| **S4 specificity of the claim** | adjective | bare figure | figure with units and conditions | |
| **S5 read depth** | title only | quoted snippet | fetched and read in full | |

**⚠️ S4 is capped at 2 deliberately, and the reason is a recorded error.** Reconstructing how the first
twenty entries were actually judged, the honest answer for Tellicherry was that **"specificity felt like
evidence."** It is not. A precise number from an interested anonymous seller is precise, not credible.
S4 can never lift a claim over a failed gate.

## The axes beside the tier

**STATE.** `settled` or `unresolved`. **`unresolved` is a state, not a fourth tier.** It coexists with
one. A claim can be CURATED and unresolved at the same time, which is the honest description of most
contested figures.

**CHECKABLE.** What recourse a reader has.

- `kitchen` testable by cooking. If Kashmiri chili tastes hot, it is not Kashmiri.
- `label` testable by reading a package. Miso salt percentage, soy sodium, asafoetida compounding.
- `none` no reader can test it. The umami receptor mechanism, market-prevalence claims.

Checkable is **independent of tier**, and the interesting case is the one a tier alone ranks backwards.
**A CURATED checkable claim is safer to ship than a CITED uncheckable one**, because the first fails
loudly in someone's kitchen and the second never fails at all.

**SOURCE CLASS.** `regulator`, `standards_body`, `measurement`, `label`, `expert_prose`,
`encyclopedia`, `retailer`, `inference`. A nutrition panel is a primary measurement of one product,
strong and narrow at once, which CITED alone conflates.

**n.** Sample size where it means anything. Five labels is a sample. One blog is an assertion. Without
`n` the model cannot tell them apart. ⚠️ Scope settles before `n` counts for anything. See **Scope
before sample size**.

**CANNOT_ASSESS.** An explicit list, **because silence reads as a pass.** The recurring entries:

- independence between two agreeing sources
- whether a specialist is respected in their own field
- whether a dead link ever said what it is cited for
- whether a photograph shows what it claims
- plausibility in an unfamiliar cuisine
- whether a retailer's figures describe their own stock or the category
- whether two sources describe the same region
- whether a page was fetched directly, when an agent is blocked but a person is not

## Single-sourcing caps a tier, and never excludes a claim

This rule exists because of a specific failure. One source listed oregano in xawaash, two others omitted
it, and the single source was **discarded** on the reasoning that dried herbs would be unusual in a
toasted Indian Ocean blend. That reasoning is a claim about Somali cooking made by someone who has never
cooked it.

**The rule.** A lone source caps the claim at CURATED and marks it `unresolved`. Excluding it requires a
recorded world-judgement, and **a GENERATED world-judgement is never sufficient to exclude a CURATED
source.** Under this rule the oregano survives as unresolved, which is the honest state.

Two agreeing sources are evidence that two sources agree. Treating that as evidence about the world
requires knowing they sampled different places. Both xawaash primaries were English-language and
Western-facing, so agreement may be one tradition described twice.

## Allergens: absence is an assertion, presence is a warning

⚠️ **THIS RULE REPLACES ONE THAT SUPPRESSED THE WARNING IT EXISTED TO PRODUCE.** The earlier rule read
"allergen, food-safety and storage-safety claims require CITED or stay blank, and fail closed."
Applied to asafoetida it did this. Sources said wheat-flour compounding can reach gluten levels unsafe
for people with celiac disease. Every source was a blog or a retailer, so nothing could reach CITED,
so the whole thing was withheld. A celiac reader got nothing at all, which is the outcome the rule was
written to prevent.

Two different objects were being handled by one rule.

**A claim of ABSENCE is an assertion.** "Contains no gluten" is prose a reader acts on. It requires
CITED and it fails closed. Nothing about that changes.

**A flag of POSSIBLE PRESENCE is a warning.** "Usually cut with wheat flour, check the packet" is not
an assertion about a particular jar. It surfaces at any tier and it says what it rests on.
⚠️ **Uncertainty is the reason to raise a flag, not a reason to suppress one.** A flag saying this is
common, we have not confirmed it, read the label, is more use to a celiac reader than silence.

**The flag stays out of the description.** A description is prose a reader takes as fact, and a
thin-sourced gluten claim does not belong in one. The flag is a separate object with its own tier, its
own sources and its own place on the page.

**⚠️ A CLAIM GETS WRITTEN WHEN A FACT TURNS UP. A FLAG HAS TO BE ASKED FOR.** Allergen exposure was
recorded for the one ingredient where somebody happened to research it and missed on two where nobody
did. Soy sauce is brewed with wheat and doubanjiang is usually made with wheat flour, and neither
carried a flag when the sweep ran. Both carry one now. Treating allergens as claims means they appear
by accident, so every entry gets the allergen question put to it, and `not checked` is a state the
page can show.

In the entry format the flag is a `[[safety_flags]]` block rather than a `[[claims]]` block, with
`kind` set to `possible_presence` or `certain_presence`, and it carries its own tier and its own
chain.

## Scope before sample size

A claim that will not resolve is usually read as thin data. Sometimes it is evidence that the **entry**
is wrong.

Light soy sauce was recorded as unresolved with one measurer and no sample size, and the recommended
fix was to read five bottles. That fix would have made things worse. Japanese usukuchi, Chinese light
soy and Korean guk-ganjang are three different products that all translate to "light soy sauce" in
English, and they differ in sodium. The sources were not in conflict. Each described a different thing
and each was right about the thing it described. Five bottles off one shelf would have averaged three
products into a figure describing none of them, and the average would have carried an `n` of 5 and
looked like a resolution.

**The tell is a measured value where the sources disagree and neither is wrong.** Ordinary thin data
produces one weak source, or two sources that contradict each other on the same object. A scoping
error produces several confident sources that cannot be reconciled, because they are not talking about
the same object.

⚠️ **The rule. Before raising `n` on a contested measurement, check that every source measured the same
product.** Sampling is only meaningful once scope is settled. Raising `n` on a wrongly scoped entry
converts a visible disagreement into an invisible average, which is worse than the disagreement.

Four entries carry several products under one name. Salt was known. Light soy, sesame oil and
peppercorns were found by reading, not by any detector.

## Three source states, not two

Tellicherry exposed a state the tiers did not have a name for.

**Reachable and read.** Normal.

**No source exists.** Substitution ratios, practical fraction steps, pairings and what-to-buy have no
dataset anywhere. Per-entry research forever.

**⚠️ Traceable in principle, not reachable.** The Tellicherry grade specification exists. The Spices
Board of India publishes no grade table and points to BIS, FSSAI and AGMARK, and those specifications
are not openly published. The claim is not unsourced and it is not sourced. **It is CURATED with a named
falsifier**, which is a different thing from a guess, and it should never be promoted on retailer
consensus alone.

## The worked example: eight times

The claim was that kombu and katsuobushi together taste about **eight times** more savory than either
alone. It went into a draft with a source attached and it looked properly sourced. Three things were
wrong, and none is visible from the link.

**The source had an interest.** The Umami Information Center was founded by Ajinomoto, which
manufactures MSG. That is an interested party on whether umami is remarkable.

**The number is the peak of a curve reported as a constant.** The measurement is Yamaguchi 1967,
*Journal of Food Science* 32(4). It published an equation rather than a multiplier, `y = u + γuv`, with
γ for inosinate at 1.218 × 10⁸, and a **bell-shaped** relationship. Synergy peaks at one mixture ratio
and falls away either side, and the figure depends on total concentration. Secondary sources render it
as roughly seven to eight times at equal proportions, then disagree about where the peak sits, some
saying 50:50 and one citing Yamaguchi 1998 for 70:30.

**The pages are dead.** They now return 404.

**What the most-vetted general source does.** Wikipedia's Umami article states the synergy and
**declines to quantify it**, citing Yamaguchi and Ninomiya 2000, *J Nutr* 130(4S):921S-926S. When a
careful tertiary source states a fact but refuses to put a number on it, the refusal is evidence.

**Verdict under the gates.** G2 fails on the dead pages, G3 fails with no external anchor. The claim is
CURATED and unresolved, and the number does not ship. The mechanism survives, because it is CITED and
can be said in ordinary words. The umami receptor holds glutamate in a hinged pocket, and the nucleotide
binds beside it and stabilizes the pocket shut, so the second compound does not add its own signal so
much as make the receptor grip the first one harder. See
[PNAS 2009](https://www.pnas.org/doi/10.1073/pnas.0810174106) and
[FEBS J 2012](https://febs.onlinelibrary.wiley.com/doi/pdfdirect/10.1111/j.1742-4658.2012.08690.x).

**A vague strong claim is worse than a plain small one.**

## Tracing is not only a demotion tool

**It upgraded a fact.** The Shaoxing entry said cooking wine has salt added to dodge liquor licensing,
resting on one food blog. Wikipedia does not support it, and its nearest sentence cites a near-infrared
spectroscopy paper that says nothing about regulation. The actual rule is the US Alcohol and Tobacco Tax
and Trade Bureau's definition of **nonbeverage wine**, which is wine treated with materials such as salt
that render it unfit for beverage use, exempting it from a Certificate of Label Approval. CURATED became
CITED and the wording got more precise.

**It corrected a fact.** The speculoos entry described the biscuit as brown sugar with cinnamon, clove
and nutmeg. That is Dutch **speculaas**. Wikipedia states that modern Belgian **speculoos** omits the
traditional spices in favor of caramelized sugar. The entry had the two backwards, and the source that
let the error survive had softened "omits the spices" into "lower cinnamon."

## The defects cluster in the opening sentence

Ten entries were swept for facts that read as a warning to a reader who does not know the ingredient.
A sensory or appearance fact overlaps with how spoilage presents, the reader is left asking whether the
jar has gone off, and nothing in the sentence answers.

**All three confirmed cases sat in the opening sentence**, where the ingredient is being identified.
Asafoetida's "cut with flour" reads as being sold filler. Doubanjiang's darkening reads as oxidation.
Black pepper's "unripe" reads as picked wrong. Each states a fact that is the specification for the
product, and each left the reader to work out whether it was a fault.

That is not a coincidence. The opening sentence is where a novice has the least context and where the
entry is most compressed, so **the opening sentence gets checked on its own** rather than the
description being scanned evenly.

**Ground beef is the model to match.** "Beef put through a grinder, which moves everything that was on
the surface into the middle." The alarming fact and the reason it matters are one clause apart, and the
temperature that follows from it lands in the next sentence.

⚠️ **The sharper form, and black pepper supplies it.** Garbled is a grading word meaning cleaned and
sieve-graded. It sounds like damage. The entry glosses it correctly, and that gloss sits in a chain
note. It is safe today only because it has never reached a reader. **A word that sounds like damage is
safe while it stays in the apparatus, and it has to carry its gloss the moment it reaches prose.**

This is the mechanism rule rather than an exception to the rule against explaining a fun fact. The test
is which question the sentence leaves behind. A fact that leaves "but why?" or "is that bad?" earns its
consequence. A fact that already implies its own instruction does not.

## The rule this produces

Read the article, then read what the article cites, then cite that. Record both. Report every case where
they disagree, where the citation does not support the claim, where the reference is dead, or where a
source cites Wikipedia back. Those cases are the reason for doing it. A clean trace tells you little. A
broken one tells you the number was never load-bearing.
