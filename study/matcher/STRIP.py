# -*- coding: utf-8 -*-
"""THE TRAILING-CLAUSE STRIPPER UNDER TEST. Not _PREP: _PREP fires on none of the target
   lines. This is a purpose-clause detector, anchored to the END of the line."""
import re
# closed verb lists, stated rather than open-ended, so the rule cannot drift
SERVE_V = (r"serve|garnish|taste|finish|drizzle|sprinkle|dust|top|decorate|coat|brush|"
           r"glaze|dredge|cover|thicken|season|grease|deep[- ]?fry|fry|line|dip|fill")
GERUND  = (r"serving|garnishing|garnish|dusting|sprinkling|greasing|frying|deep[- ]?frying|"
           r"drizzling|topping|brushing|rolling|kneading|dredging|boiling|roasting|"
           r"massaging|coating|dipping|decorating|thickening|finishing|shaping|proofing")
EQUIP   = r"the\s+(?:pan|tin|tray|dish|sheet|mould|mold|bowl|surface|board|work\s+surface)"

TAIL = re.compile(
    r"""(?P<cut>
          \s*[,;(]?\s*
          (?:
              (?:and\s+)?to\s+(?:""" + SERVE_V + r""")\b
            | (?:and\s+)?for\s+(?:""" + GERUND + r"""|""" + EQUIP + r""")\b
            | plus\s+(?:more|extra)\b
            | with\s+\w+(?:\s+\w+)?\s+(?:on|removed|attached|left\s+on|discarded)\b
            | if\s+(?:needed|desired|using|you\b)
            | as\s+needed\b
            | or\s+to\s+taste\b
          )
          .*$
        )""", re.I | re.X)

def strip_tail(text):
    """Strip ONE trailing purpose clause, from its marker to end of line.

    ⚠️ ANCHORED WITH .*$ SO IT ONLY EVER REMOVES A SUFFIX. It cannot take a bite out of
    the middle and rejoin, so it can never fuse two halves of a line into a false phrase.
    ⚠️ 'and' is allowed ONLY immediately before to/for. A bare 'and' is never a marker, so
    'salt and pepper' and 'bone-in and skin-on' are untouchable by construction.
    ⚠️ A marker inside the FIRST 3 characters is ignored, so a line that IS the clause
    ('To serve') is left alone rather than emptied."""
    m = TAIL.search(text or "")
    if not m: return text, ""
    if m.start("cut") < 3: return text, ""
    return text[:m.start("cut")].rstrip(" ,;("), text[m.start("cut"):].strip()
