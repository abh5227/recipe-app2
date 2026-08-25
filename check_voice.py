#!/usr/bin/env python3
"""check_voice.py: the mechanical half of the voice rules, over the TOML entry files.

    python3.13 check_voice.py                     -> preview/entries-v3/*.toml
    python3.13 check_voice.py preview/categories-v1

WHAT IT CHECKS. Only the rules CLAUDE.md calls the ones that actually get checked: em
dashes, semicolons, US spelling, no Latin, and ranges written out in full. Everything else
in the voice section is a judgement and no script should pretend otherwise.

⚠️ WHY THE EXCLUSIONS EXIST, AND THEY ARE THE WHOLE POINT OF THIS FILE.
A first pass over 134 entries reported exactly one violation:

    coriandrum-sativum.toml   source = "eriksson-2012-flavour-1-22"

That is a citation key. Eriksson et al. 2012 is published in FLAVOUR, a BMC journal,
volume 1 article 22. The word is the journal's name. "Fixing" it would have broken the
reference behind the cilantro-soap claim and left the entry citing nothing. The rule the
checker was enforcing is about the words this project writes, and a citation key is not
one of them.

The same reasoning covers the other excluded keys. `form` holds names copied VERBATIM from
a source, and build_library.py's header states that no name is invented anywhere in this
pipeline, so 'Bourbon vanilla flavouring' is data rather than prose.

TWO SEVERITIES, because a quoted name inside a sentence is neither clean nor a violation.
A bare match in prose is a VIOLATION. A match inside quotes is QUOTED and printed
separately, because entries quote source names in their diagnostics on purpose.
"""
import glob, os, re, sys, tomllib

# ⚠️ VERBATIM-SOURCE KEYS. Their values are copied from a source or name a record, so the
#    voice rules do not apply to them. See the module docstring for the case that set this.
SKIP_KEYS = {"source", "form", "id", "wikidata", "key", "flag", "slot", "tier", "state",
             "checkable", "source_class", "mode", "read_depth", "derived_from",
             "review_state", "cannot_assess", "see_also", "kind", "n", "added"}

# ⚠️ labellED WITH TWO Ls, and the first draft wrote `labell?ed`, which matched the
#    AMERICAN spelling and reported 11 correct words as violations. A checker that flags
#    the right answer is worse than no checker.
# ⚠️ SUFFIXES ON THE -our STEMS, and the first draft closed them with \b so 'flavouring'
#    and 'savoury' and 'colouring' all passed. The stems take \w* and the rest are spelled
#    out, because 'greyhound' is not a misspelling and \w* on every word would say it was.
BRITISH = re.compile(
    r"\b(?:(?:colour|flavour|savour|behaviour|honour|labour|rumour|vapour|odour)\w*|"
    r"labelled|labelling|centimetres?|kilometres?|litres?|"
    r"organis(?:e|ed|ing|ation)|recognis(?:e|ed|ing)|analys(?:e|ed|ing)|"
    r"defence|offence|grey|greyish|practis(?:e|ed|ing)|licence|mould\w*|smoulder\w*|"
    r"caramelis(?:e|ed|ing|ation)|sulphur\w*|aluminium|ageing|storeys?|tyres?|"
    r"ploughs?|draughts?|coeliacs?)\b", re.I)
LATIN = re.compile(r"(?<![a-z])(i\.e\.|e\.g\.|vs\.|etc\.|cf\.|N\.B\.|a fortiori|ad hoc)", re.I)
# ⚠️ A RANGE COUNTS UP. `n°88-1204` is a French decree number and the first draft called
#    it a range, so the pattern now requires the second number to be the larger one and
#    refuses anything introduced by a number sign.
RANGE = re.compile(r"(?<![\w-])(\d+)\s?[-–]\s?(\d+)(?![\w-])")
NUMBERED = re.compile(r"(n°|№|no\.|#|article|décret|decree)\s*\S{0,12}$", re.I)


def ranges(text):
    for m in RANGE.finditer(text):
        if NUMBERED.search(text[:m.start()]):
            continue
        if int(m.group(2)) <= int(m.group(1)):
            continue                              # counts down, so it is an identifier
        yield m.start()
QUOTED = re.compile(r"['\"“”‘’][^'\"“”‘’]{0,80}?['\"“”‘’]")

CHECKS = (("em dash", lambda s: [m.start() for m in re.finditer(r"[—–]", s)]),
          ("semicolon", lambda s: [m.start() for m in re.finditer(r";", s)]),
          ("British spelling", lambda s: [m.start() for m in BRITISH.finditer(s)]),
          ("Latin", lambda s: [m.start() for m in LATIN.finditer(s)]),
          ("range not written out", lambda s: list(ranges(s))))


def strings(node, path=()):
    """Every checkable string, with the key path that reached it. Skips SKIP_KEYS."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in SKIP_KEYS:
                continue
            yield from strings(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from strings(v, path + (str(i),))
    elif isinstance(node, str):
        yield ".".join(path), node


def inside_quotes(text, pos):
    return any(m.start() < pos < m.end() for m in QUOTED.finditer(text))


def check(path):
    """(violations, quoted) for one file. A quoted hit is a source name, not our prose."""
    with open(path, "rb") as fh:
        doc = tomllib.load(fh)
    violations, quoted = [], []
    for key, text in strings(doc):
        for name, find in CHECKS:
            for pos in find(text):
                bucket = quoted if inside_quotes(text, pos) else violations
                bucket.append((key, name, text[max(0, pos - 38):pos + 38].replace("\n", " ")))
    return violations, quoted


def main(argv):
    targets = argv[1:] or ["preview/entries-v3"]
    files = []
    for t in targets:
        files += sorted(glob.glob(os.path.join(t, "*.toml")) if os.path.isdir(t) else glob.glob(t))
    n_v = n_q = 0
    for path in files:
        v, q = check(path)
        n_v += len(v)
        n_q += len(q)
        for key, name, snip in v:
            print(f"VIOLATION  {os.path.basename(path):34s} {name:22s} {key:28s} ...{snip}...")
        for key, name, snip in q:
            print(f"  quoted   {os.path.basename(path):34s} {name:22s} {key:28s} ...{snip}...")
    print(f"\n{len(files)} files   {n_v} violation(s)   {n_q} quoted, check by eye")
    print(f"skipped keys: {', '.join(sorted(SKIP_KEYS))}")
    return 1 if n_v else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
