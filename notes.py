"""notes.py - the shared notes brain: split, classify, step references, and the derived column.

ONE RULE SET, EVERY CALLER. The corpus pass, the importer, the save path and the read path all come
here, so a note imported tomorrow is split the way the corpus was moved. This is the same
arrangement planahead.py has for waits, and the same rule the heading repair and the importer were
joined under.

⚠️ THE SPLIT AND THE KIND TABLE ARE NOT RESTATED HERE. `paragraphs` is the Python side of
static/note-blocks.js::noteParagraphs and `kind_of` delegates to import_cleanup.note_kind, which
reads static/note-kinds.json, the same file Vite inlines for the client. A second copy of either
would be exactly the drift the corpus repair and the importer were joined to avoid.

⚠️ ONE PARAGRAPH IS ONE NOTE, AND A SINGLE NEWLINE DOES NOT SPLIT. Measured over the 95 recipes that
carry notes: 82 of the newline runs are a blank line and 19 are a single newline inside a paragraph
(a list, a label on its own line above its text). Splitting on every newline would turn 8 notes into
30 fragments.
"""
import re

from import_cleanup import NOTE_KINDS, note_kind          # the one table, the one classifier

DEFAULT_KIND = NOTE_KINDS[0]["kind"]                      # "notes"
KIND_HEADERS = {k["kind"]: k["header"] for k in NOTE_KINDS}

_PARAGRAPH = re.compile(r"\n\s*\n")

# ⚠️ THE MENTION PATTERN IS DELIBERATELY NARROW. It matches a step named by NUMBER and nothing else.
#    Measured over the 177 corpus paragraphs: 2 name a step by number, 0 say "the step above", "see
#    step" or "the first step". A pattern that guessed at prose would find phrases nobody meant as a
#    reference, and every hit here becomes a link on the page.
STEP_MENTION = re.compile(r"\bsteps?\s+(\d+)\b", re.IGNORECASE)


def paragraphs(text):
    """Stored notes text -> the paragraphs it holds. The Python side of noteParagraphs."""
    return [p.strip() for p in _PARAGRAPH.split(str(text or "")) if p.strip()]


def kind_of(para):
    """A paragraph -> the kind its leading label names, or the default when it has no listed label.

    ⚠️ AN UNLISTED LABEL IS NOT A KIND AND ITS TEXT IS NOT TOUCHED. 27 of the 177 corpus paragraphs
    lead with a label the table does not know ("Blind Bake", "Tomato Bouillon", "Borlotti"), against
    23 that lead with one it does. They stay whole and sit under Notes, which is what the display
    already does."""
    return note_kind(para) or DEFAULT_KIND


def scan_step_mentions(text):
    """Every "step N" in a note -> [{ref_index, match_text, number, start, end}].

    ref_index is the ordinal of the mention WITHIN this note, which is what a stored reference is
    keyed on. Keying on a character offset would break on the first word inserted before it; keying
    on the number alone would break on a note that names two steps."""
    out = []
    for i, m in enumerate(STEP_MENTION.finditer(str(text or ""))):
        out.append({"ref_index": i, "match_text": m.group(0),
                    "number": int(m.group(1)), "start": m.start(), "end": m.end()})
    return out


def step_numbers(steps):
    """{step id: the number the page prints}, with None for a heading.

    ⚠️ THE SAME COUNT THE PAGE SHOWS, which is real steps only. Mirrors planahead.resolve_steps
    rather than re-deriving it, because a note and a wait pointing at the same step must print the
    same number."""
    def get(st, key):
        try:
            return st[key]
        except (TypeError, KeyError, IndexError):
            return getattr(st, key, None)

    by_id, number = {}, 0
    for st in steps:
        heading = get(st, "is_heading")
        if not heading:
            number += 1
        by_id[get(st, "id")] = None if heading else number
    return by_id


def resolve(notes, steps):
    """Fill each note's step_no / step_ok and resolve its step references, in place.

    ⚠️ STORING A POINTER AND PRINTING IT ARE DIFFERENT QUESTIONS, and this answers the second. A note
    pointing at a step that has since become a HEADING keeps its step_id and comes back with
    step_no None, so the page renders it without a link rather than with a wrong number. Exactly the
    rule waits follow, for the same reason."""
    by_id = step_numbers(steps)
    for n in notes:
        sid = n.get("step_id")
        n["step_no"] = by_id.get(sid) if sid else None
        n["step_ok"] = True if sid is None else (by_id.get(sid) is not None)
        # Each stored reference gains the CURRENT number of the step it names. A reference whose
        # step became a heading, or was deleted, resolves to None and renders as plain text.
        for ref in (n.get("refs") or []):
            ref["step_no"] = by_id.get(ref.get("step_id")) if ref.get("step_id") else None
    return notes


def _field(row, name):
    """One field off a dict OR an ORM row, absent reading as None.

    ⚠️ .get, NOT [name]. Every caller of derived_text hands it a different shape: an ORM row, a
    mapping read off the table, and a PLAN row built by a pass, and the plan rows carry no title at
    all. Subscripting raised KeyError on ten of them."""
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def derived_text(rows, separator="\n\n"):
    """The note rows -> the text recipes.notes holds while the column is retired but not dropped.

    ⚠️ THE COLUMN IS A DERIVED COPY NOW, NOT THE SOURCE. It stays written so the previous deploy can
    still serve a recipe during the window, and a later migration drops it. Rebuilding it from the
    rows rather than editing it in place is what keeps the two from disagreeing.

    ⚠️ A TITLE IS PUT BACK ON THE FRONT, BECAUSE THE TITLES ROUND TOOK IT OUT OF THE TEXT. The pass
    leaves recipes.notes alone, so it still holds the whole paragraph, and _sync_notes_column
    rebuilds that column on EVERY note write. Reading only `text` therefore made one unrelated note
    edit on any of the 21 touched recipes silently drop the title words from the copy the previous
    deploy serves: brioche-bread's column would have lost "Flour" and "Kneading by hand"."""
    out = []
    for r in rows:
        text = (_field(r, "text") or "").strip()
        title = (_field(r, "title") or "").strip()
        out.append(f"{title}. {text}" if title else text)
    return separator.join(out)
