#!/usr/bin/env python3
"""plan_ahead_short_rests.py - the short rests v2 never looked at. READ-ONLY, report only.

Round 3 asked whether rests like chocolate-chip-cookies' 5 minute one were missed elsewhere. They
were, in quantity. This scans live for a rest verb carrying a duration of 20 minutes or under, and
records a verdict on EVERY hit rather than a count.

⚠️ THE TALLY IS MISLEADING ON ITS OWN. 62 sentences match. 13 of them are active cooking that the
verb 'rest' or 'sit' happens to sit beside ("cook, undisturbed, for 3 to 4 minutes", "cook the
rest"), and 7 more are yeast blooming inside the prep flow. Reading each one is the only way to
tell, which is why the verdict is stored per row and not derived.

⚠️ NOTHING HERE IS PROPOSED FOR WRITING. The v3 proposals carry only chocolate-chip-cookies' rest,
which was asked for by name. Whether the other genuine rests belong in plan-ahead at all is a
judgement about what the row MEANS: a 5 minute rest on a baking sheet is not something a cook
arranges their day around, and 33 of them would make the plan-ahead row the noisiest thing on the
page. That is Andy's call, and this file is the list to make it from.
"""
import csv
import pathlib
import re
import sqlite3
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
OUT = BASE / "previews" / "plan-ahead-short-rests.csv"
V2 = BASE / "previews" / "plan-ahead-proposals.csv"

REST = re.compile(r"\b(?:rest|let (?:it|them|the \w+) (?:rest|sit|stand)|set aside|stand|sit)\b", re.I)
DUR = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:to|-|–|or)?\s*(\d+(?:\.\d+)?)?\s*"
                 r"(minute|minutes|min|mins|hour|hours|hr|hrs)\b", re.I)

# (recipe_id, step_position, minutes) -> (verdict, kind, when_kind, when_label, note)
# Every hit was read. NOT-A-WAIT means the duration belongs to another verb.
VERDICTS = {
    ("agedashi-tofu", 8, 3): ("not-a-wait", "", "", "", "'sit' is the oil depth; the 3-4 min is heating the oil"),
    ("apple-pie", 3, 5): ("rest", "resting", "always", "", "dough comes back to room temperature"),
    ("basic-dal", 1, 5): ("rest", "resting", "always", "", "covered off the heat"),
    ("basic-dal", 1, 10): ("not-a-wait", "", "", "", "the 10 min is pressure-cooking in the Instant Pot alternative"),
    ("black-pepper-chicken", 0, 10): ("already", "", "", "", "v2 carries this step as a marinade"),
    ("brioche-bread", 0, 5): ("bloom", "resting", "always", "", "yeast proofing until foamy, inside the prep flow"),
    ("brioche-cinnamon-rolls", 0, 5): ("bloom", "resting", "always", "", "yeast proofing until foamy"),
    ("brown-butter-brownie-cookies", 4, 6): ("not-a-wait", "", "", "", "whipping on high speed for 6 min"),
    ("bulgogi-bowls", 1, 1): ("not-a-wait", "", "", "", "tossing until wilted"),
    ("cantonese-pan-fried-noodles", 7, 1): ("not-a-wait", "", "", "", "tossing in the pan"),
    ("caramelized-onion-dal", 0, 10): ("rest", "resting", "always", "", "off the heat"),
    ("cauliflower-soup", 4, 20): ("rest", "resting", "always", "", "the soup stands 20 min"),
    ("chicken-and-broccoli-with-brown-sauce", 1, 10): ("already", "", "", "", "v2 carries this step as a marinade"),
    ("chicken-asparagus-stir-fry", 0, 15): ("already", "", "", "", "v2 carries this as a 15-30 min marinade"),
    ("chicken-shawarma", 3, 5): ("rest", "resting", "always", "", "meat rests after cooking"),
    ("chicken-shawarma-with-garlic-sauce-and-greens", 4, 10): ("rest", "resting", "always", "", ""),
    ("chocolate-chip-cookies", 22, 5): ("already", "", "", "", "ADDED to v3 by name"),
    ("country-ham-croquettes-with-parsley-salad", 2, 2): ("rest", "resting", "always", "", "milk infuses off the heat"),
    ("flatbreads-with-za-atar-mana-eesh", 8, 3): ("not-a-wait", "", "", "", "'the rest' means the remainder, and the 3 min is baking"),
    ("gai-yang-2", 4, 3): ("rest", "resting", "always", "", "meat rests before serving"),
    ("garlic-ginger-chicken-with-cilantro-and-mint", 4, 10): ("rest", "resting", "always", "", "covered off the heat"),
    ("garlic-rice", 4, 10): ("rest", "resting", "always", "", "rice rests with the lid on"),
    ("hummus-2", 1, 10): ("rest", "resting", "always", "", "'ideally 10 minutes or longer', so open-ended"),
    ("jamaican-jerk-fish", 4, 2): ("rest", "resting", "always", "", "on a rack to keep the crust crisp"),
    ("jamaican-rice-and-peas-beans", 4, 15): ("rest", "resting", "always", "", "off the heat with the lid on"),
    ("kfc-spicy-chicken-rice-bowl", 2, 15): ("rest", "resting", "optional", "", "'If possible' — the flour coating moistens"),
    ("khaliat-nahal-honeycomb-bread", 3, 5): ("bloom", "resting", "always", "", "yeast proofing"),
    ("lotus-root-and-jammy-tomatoes", 1, 10): ("rest", "resting", "always", "", "off the heat"),
    ("malted-brownie-biscotti", 1, 2): ("not-a-wait", "", "", "", "beating butter and sugar"),
    ("meat-lasagna", 21, 5): ("rest", "resting", "always", "", "stands 5 to 10 min before cutting"),
    ("mejadra", 10, 10): ("rest", "resting", "always", "", "residual liquid absorbs"),
    ("mexican-rice", 3, 5): ("rest", "resting", "always", "", "off the heat before fluffing"),
    ("milky-tea-tres-leches", 4, 3): ("not-a-wait", "", "", "", "whipping eggs and sugar"),
    ("mocha-chocolate-chunk-cookies", 8, 10): ("rest", "resting", "only_if", "the dough is too sticky", "conditional"),
    ("nandos-portuguese-chicken-and-rice", 1, 15): ("rest", "resting", "always", "", "rests 10 min after steaming"),
    ("nandos-portuguese-chicken-and-rice", 8, 10): ("rest", "resting", "always", "", "off the stove, lid on"),
    ("new-york-style-bagel", 5, 10): ("rest", "resting", "always", "", "dough rests after punching down"),
    ("new-york-style-bagel", 11, 20): ("rest", "resting", "always", "", "shaped bagels rest under a towel"),
    ("new-york-style-bagel", 12, 1): ("not-a-wait", "", "", "", "boiling the bagels"),
    ("orange-peel-fish", 4, 10): ("not-a-wait", "", "", "", "baking in a pouch"),
    ("pan-fried-cabbage-with-bacon-and-green-onions", 6, 3): ("not-a-wait", "", "", "", "cooking undisturbed"),
    ("pepperoni-rolls", 1, 5): ("bloom", "resting", "always", "", "yeast proofing until foamy"),
    ("pepperoni-rolls", 18, 10): ("rest", "resting", "always", "", "rolls rest covered"),
    ("pita-bread", 1, 5): ("bloom", "resting", "always", "", "yeast proofing until foamy"),
    ("prego-rolls-steak-and-piri-piri-sandwiches", 1, 10): ("rest", "resting", "always", "", "steak rests before slicing"),
    ("priya-s-dal", 2, 15): ("rest", "resting", "always", "", "off the heat"),
    ("pumpkin-spice-sandwich-cookies-with-brown-butter-cream-cheese-frosting", 10, 10): ("rest", "resting", "always", "", "butter softens the cream cheese"),
    ("quick-easy-hainanese-chicken-rice-khao-mun-gai", 8, 5): ("rest", "resting", "always", "", "'at least 5 minutes', so open-ended"),
    ("red-wine-braised-short-ribs", 2, 15): ("rest", "resting", "always", "", "meat comes to room temperature after salting"),
    ("shrimp-scampi", 7, 5): ("not-a-wait", "", "", "", "the 5 min is simmering the wine"),
    ("spiced-fish-pilaf-with-caramelized-onions-sayadieh", 5, 10): ("rest", "resting", "always", "", "off the heat"),
    ("syrian-style-lentils-with-chard", 1, 5): ("rest", "resting", "always", "", "lentils absorb the salt off the heat"),
    ("the-best-new-york-style-bagel", 5, 10): ("rest", "resting", "always", "", "dough rests before dividing"),
    ("the-best-new-york-style-bagel", 6, 10): ("rest", "resting", "always", "", "shaped dough rests"),
    ("turkish-simit", 0, 5): ("bloom", "resting", "always", "", "yeast proofing until frothy"),
    ("vanilla-mug-cake", 2, 1): ("rest", "resting", "always", "", "rests in the microwave"),
    ("vietnamese-coffee-bundt-cake", 7, 3): ("not-a-wait", "", "", "", "beating egg whites to soft peaks"),
    ("warm-buttered-hummus", 1, 5): ("rest", "resting", "always", "", "chickpeas absorb the salt off the heat"),
    ("za-atar-bread", 0, 5): ("bloom", "resting", "always", "", "yeast proofing until foamy"),
    ("za-atar-bread", 6, 20): ("rise", "rising", "always", "", "⚠️ A REAL RISE v2 MISSED, 20 to 30 min, not a short rest at all"),
    ("zanzibar-pilau-rice-pilaf", 3, 10): ("rest", "resting", "always", "", "'at least 10 minutes', so open-ended"),
}

FIELDS = ["recipe_id", "step_position", "minutes", "verdict", "kind", "when_kind", "when_label",
          "note", "sentence"]


def main():
    c = sqlite3.connect(f"file:{BASE / 'recipes.db'}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    out, unseen = [], []
    for r in c.execute("select id from recipes order by id"):
        for s in c.execute("select position, text from recipe_steps where recipe_id=? "
                           "order by position", (r["id"],)):
            t = re.sub(r"<[^>]+>", " ", s["text"] or "")
            for sent in re.split(r"(?<=[.!?])\s+|\n", t):
                if not REST.search(sent):
                    continue
                m = DUR.search(sent)
                if not m:
                    continue
                unit = m.group(3).lower()
                mins = int(float(m.group(1)) * (60 if unit.startswith(("hour", "hr")) else 1))
                if mins > 20:
                    continue
                key = (r["id"], s["position"], mins)
                v = VERDICTS.get(key)
                if v is None:
                    unseen.append(key)
                    v = ("UNREAD", "", "", "", "")
                out.append(dict(recipe_id=r["id"], step_position=s["position"], minutes=mins,
                                verdict=v[0], kind=v[1], when_kind=v[2], when_label=v[3],
                                note=v[4], sentence=" ".join(sent.split())[:200]))
    with OUT.open("w", newline="\n") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    import collections
    print(f"wrote {OUT.name}: {len(out)} rows over "
          f"{len(set(r['recipe_id'] for r in out))} recipes")
    for k, n in collections.Counter(r["verdict"] for r in out).most_common():
        print(f"  {k:12s} {n}")
    # ⚠️ A HIT WITH NO VERDICT MEANS THE SCAN FOUND SOMETHING NOBODY READ. Never silent.
    if unseen:
        print(f"\n⚠️ {len(unseen)} UNREAD hits: {unseen}")
    return out


if __name__ == "__main__":
    main()
