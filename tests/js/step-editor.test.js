"use strict";
// Round-trip fidelity gate for the Stage 1b-1 [[key|label]] adapter (static/step-editor.js).
// The pair is PURE (text -> ProseMirror JSON doc -> text, no live editor/DOM), so it runs under bare
// `node --test`. The bar: stepTextToDoc then docToStepText must return the ORIGINAL text byte-for-byte
// — for the real linked steps and the edge cases the 1b diagnostic flagged (no-label, label==key,
// whitespace, adjacent links, multi-line, empty, Unicode).
//
// REAL_STEPS are the verbatim recipes.db strings, embedded as \u-escaped literals produced by
// json.dumps (ASCII, so copy-exact — no risk of mis-transcribing sauté / en-dash / ½ ¼ / em-dash).
import { test } from "node:test";
import assert from "node:assert/strict";
import { stepTextToDoc, docToStepText, showLinksAsWords } from "../../static/step-adapter.js";

const roundTrip = (t) => docToStepText(stepTextToDoc(t));

// The 14 REAL linked step strings, verbatim from recipes.db.
const REAL_STEPS = [
  "Spread the [[potato|potatoes]] and [[cauliflower]] on the sheet and toss with 3 tbsp of the oil. Roast in an even layer for 30 minutes, until browned and slightly crisp, tossing once halfway. Set aside to cool.",   // aloo-gobhi #1
  "Meanwhile, warm the remaining 2 tbsp oil in a large sauté pan over medium-high. When it shimmers, add the [[cumin|cumin seeds]] and cook until medium brown, about a minute. Lower to medium and swirl in the [[turmeric]]. Add the [[onion|onion]] and sauté 4–6 minutes, until translucent.",   // aloo-gobhi #2
  "Add the [[asafetida]] (if using), [[chile_powder|red chile powder]] and [[ginger]], and cook another minute.",   // aloo-gobhi #3
  "Stir in the roasted vegetables and any charred bits. Mix gently (don't overmix or the cauliflower falls apart), add the salt, and cook 5–6 minutes more, until tender but not soggy. Off the heat, add the [[lime]] juice; taste and adjust lime and salt.",   // aloo-gobhi #4
  "Garnish with the [[cilantro]].",   // aloo-gobhi #5
  "Wilt the [[spinach]]: heat 2 tsp oil in a large non-stick pan over high heat. Add half the spinach, toss with tongs until semi-wilted (~30 sec), then add the rest and toss until wilted (~1 min). Remove to a bowl.",   // bulgogi-bowls #1
  "Build the bowls: rice topped with the beef, spinach, [[carrot]], [[avocado]], lettuce, the drizzle sauce, [[sesame_seed|sesame seeds]] and [[green_onion|green onion]].",   // bulgogi-bowls #3
  "Grind the [[white_pepper|white peppercorns]] and [[coriander_seed|coriander seeds]] to a powder with a mortar and pestle or spice grinder. Add the [[lemongrass]] and [[garlic]] and pound to a fine paste. Transfer to a bowl and stir in the remaining marinade ingredients until the sugar dissolves.",   // gai-yang #0
  "Combine the [[tamarind]], [[fish_sauce|fish sauce]], [[lime]] juice and [[palm_sugar]]; stir until the sugar dissolves (finely chopped sugar helps).",   // gai-yang #4
  "Stir in the chili flakes and [[shallot|shallots]]. Close to serving, add the [[green_onion|green onion]], [[cilantro]] and toasted rice powder.",   // gai-yang #5
  "Pour over the olive oil, spices, [[lemon]] juice, [[garlic]], 1½ tsp salt and ¼ tsp pepper, and rub into the meat. Add the [[red_onion|red onions]] and toss together well. Cover and marinate in the fridge for 1–3 hours.",   // mussakhan #1
  "Fry the [[pine_nut|pine nuts]] in the oil for a minute or so until golden, then drain on paper towel.",   // mussakhan #4
  "Toast the bread and top with the chicken and onion. Finish with the pine nuts, a dusting of [[sumac]] and chopped [[parsley]], then drizzle over the roasting juices and a little more olive oil.",   // mussakhan #5
  "Mix the [[bread_flour|flour]], [[yeast]] and salt in a large bowl. Add the water and stir with the handle of a wooden spoon until the flour is incorporated. The dough will be wet and sloppy — not kneadable, but not runny. Adjust with a little more water or flour if needed.",   // no-knead-bread #1
];

// Edge cases the diagnostic flagged, each must round-trip byte-identical.
const EDGE_CASES = {
  "no-label form": "stir in the [[garlic]]",
  "label == key (must NOT collapse to [[onion]])": "add the [[onion|onion]]",
  "whitespace around chips": "of [[x|X]] and [[y]] then",
  "adjacent links (no empty text node)": "[[a]][[b]]",
  "multi-line (paragraphs rejoined with \\n)": "line one [[a]]\nline two [[b|B]]",
  "empty string": "",
  "whitespace-only": " ",
  "Unicode runs preserved": "cook 4–6 min, add ½ tsp [[lime]] juice",
  "no links at all": "just plain method text, no links here",
  "link at very start and end": "[[a]] middle [[b|B]]",
};

test("round-trip is byte-identical for all 14 real linked steps", () => {
  REAL_STEPS.forEach((t, i) => {
    assert.equal(roundTrip(t), t, `real step #${i} did not round-trip byte-identically`);
  });
});

test("round-trip is byte-identical for the flagged edge cases", () => {
  for (const [name, t] of Object.entries(EDGE_CASES)) {
    assert.equal(roundTrip(t), t, `edge case failed: ${name}`);
  }
});

test("no-label [[key]] parses to label: null (not defaulted to the key)", () => {
  const doc = stepTextToDoc("[[garlic]]");
  const node = doc.content[0].content[0];
  assert.equal(node.type, "ingredientLink");
  assert.equal(node.attrs.id, "garlic");
  assert.equal(node.attrs.label, null);
});

test("[[key|label]] parses to the exact label, even when label == key", () => {
  const doc = stepTextToDoc("add the [[onion|onion]]");
  // paragraph content: [ text "add the ", ingredientLink ]
  const link = doc.content[0].content[1];
  assert.equal(link.type, "ingredientLink");
  assert.equal(link.attrs.id, "onion");
  assert.equal(link.attrs.label, "onion");
});

test("adjacent links produce no zero-length text node", () => {
  const inline = stepTextToDoc("[[a]][[b]]").content[0].content;
  assert.equal(inline.length, 2);
  assert.ok(inline.every((n) => n.type === "ingredientLink"), "expected only ingredientLink nodes");
});

test("a plain [[key|label]] serializes back to the same text", () => {
  assert.equal(docToStepText(stepTextToDoc("[[pine_nut|pine nuts]]")), "[[pine_nut|pine nuts]]");
});


// ---- showLinksAsWords: a heading's display text (review fix 2) --------------------------------
// The third function in this module, and it is here because it reads the SAME grammar. A heading is
// escaped and never linkified, so a step converted to a heading by the row menu would print its
// brackets. The stored text keeps the markup and every heading renderer runs it through this, which
// is what makes the conversion reversible — see the note in step-adapter.js.

test("every one of the 14 real linked steps loses its brackets and keeps its words", () => {
  for (const t of REAL_STEPS) {
    const shown = showLinksAsWords(t);
    assert.ok(!shown.includes("[["), `brackets survived: ${shown.slice(0, 60)}`);
    assert.ok(!shown.includes("]]"), `brackets survived: ${shown.slice(0, 60)}`);
    // the label (or the key) is what is left behind, so the sentence still reads
    for (const m of t.matchAll(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g)) {
      assert.ok(shown.includes((m[2] || m[1]).trim()),
        `lost the words of ${m[0]} in: ${shown.slice(0, 60)}`);
    }
  }
});

test("a no-label link shows its key and a labelled one shows its label", () => {
  assert.equal(showLinksAsWords("Wilt the [[spinach]]"), "Wilt the spinach");
  assert.equal(showLinksAsWords("the [[chile_powder|red chile powder]]"), "the red chile powder");
  assert.equal(showLinksAsWords("[[pine_nut|pine nuts]] and [[lemon]]"), "pine nuts and lemon");
});

test("text with no markup is returned verbatim, and null is safe", () => {
  assert.equal(showLinksAsWords("To Boil and Bake the Bagels"), "To Boil and Bake the Bagels");
  assert.equal(showLinksAsWords(""), "");
  assert.equal(showLinksAsWords(null), "");
  assert.equal(showLinksAsWords(undefined), "");
});

test("it is a DISPLAY transform: the stored text still round-trips to itself", () => {
  // The whole reason this is lossless. The display never feeds the store.
  for (const t of REAL_STEPS) assert.equal(roundTrip(t), t);
});

test("an unclosed bracket is left exactly as it is rather than half-eaten", () => {
  assert.equal(showLinksAsWords("Pour the batter in (it'll be thick [[garlic"),
               "Pour the batter in (it'll be thick [[garlic");
});

test("it reads the grammar linkify reads, including the cases linkify reads loosely", () => {
  // ⚠️ NOT A SEPARATE OPINION ABOUT WHAT A LINK IS. "a [[ and a ]]" has no key anyone meant, and
  // linkify makes a button out of it; this makes the same words out of it. Agreeing with linkify
  // matters more than either answer, because a heading and a step show the same stored text and a
  // second reading of the grammar is how two readers of one rule drift apart.
  const linkify = (t) => String(t).replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,
    (_, k, l) => (l || k).trim());
  for (const t of ["a [[ and a ]]", "[[x]][[y]]", "[[a|b]] [[c]]", "no markup at all"])
    assert.equal(showLinksAsWords(t), linkify(t));
});
