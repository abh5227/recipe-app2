#!/usr/bin/env python3
"""library_loader.py - load a verified entry TOML from Library/sourced/ into the library_* tables.

STRICT BY DESIGN. Every field this module does not know about is an ERROR, not a warning and not a
silently dropped column. The reason is measured rather than theoretical: the per-piece prose model
was adopted, applied to 50 entries, and never written into the operator brief, so six entries drafted
afterwards had to guess the field name and three guessed `body` instead of `text`. A loader that
coerced `body` to `text` would have hidden that drift permanently. A loader that refuses makes the
next drift a build failure on the day it appears. The same argument applies to `alternatives`, which
two entries shipped as a bare string where the other fifteen used a list.

WHAT IT DOES NOT DO. It never writes `ingredients`, and in particular never `ingredients.descr`.
Nine of the 56 entries land on an ingredients row that already carries hand-written prose, and
build_db's seed_content overwrites descr on every run, so sourced prose kept there would be silently
destroyed by the next rebuild. It lives in library_prose_pieces instead, where the rebuild cannot
reach it.

THE DUAL-KEY RECONCILE. Library ids are not durable (migration 030 documents an ordinary commit that
destroyed seven of them), which is why each entry stores a library_canonical snapshot beside its
library_id. The id is tried first and the snapshot is the fallback, never the authority:

    linked           the id is in library_names and the canonical still matches
    canonical_drift  the id resolves, the canonical moved. The id wins, the drift is recorded
    healed           the id is gone, the canonical matched exactly one row, the id is rewritten
    unresolved       the id is gone and the canonical matched zero rows or several
    no_library_id    the entry never carried one (salt, sugar and water)

Name matching uses build_join.norm_name, the catalog's own normalization, so the loader and the
catalog agree on what counts as the same name. It folds case, hyphens and apostrophes and KEEPS
diacritics, which is why 'tomato puree' does not match a live 'tomato purée'. That is drift worth
seeing, not a near-miss worth absorbing.
"""
import argparse
import datetime
import json
import sqlite3
import sys
import tomllib
from pathlib import Path

from build_join import norm_name

BASE_DIR = Path(__file__).resolve().parent
DB = BASE_DIR / "recipes.db"
SOURCED = Path("/Users/andrewhannah/Documents/Local Documents/Food/Library/sourced")

TIER_RANK = {"generated": 0, "curated": 1, "cited": 2}

# Every field this loader accepts, per level. Anything else raises. Keep these in step with
# migration 032 and with the operator brief's shape sections.
ENTRY_FIELDS = {"id", "name", "library_id", "library_canonical", "review_state", "row_diagnostic",
                "claims", "prose", "safety_flags", "forms", "form", "cuisine", "scope_note",
                "possible_parent", "judgements", "siblings"}
CLAIM_FIELDS = {"key", "text", "tier", "state", "checkable", "source_class", "n", "mode",
                "rests_on", "see_also", "cannot_assess", "chain", "discussion"}
FLAG_FIELDS = {"key", "text", "tier", "state", "checkable", "source_class", "n", "mode", "kind",
               "surfaces", "allergen", "hazard", "also", "note", "needs", "needs_reason",
               "rests_on", "chain", "discussion"}
CHAIN_FIELDS = {"source", "url", "mode", "read_depth", "taken", "cannot_assess", "slug"}
DISCUSSION_FIELDS = {"author", "body"}
PROSE_BLOCK_FIELDS = {"slot", "piece"}
PIECE_FIELDS = {"text", "derived_from", "resolved_note", "cut_note"}
JUDGEMENT_CANONICAL = {"id", "kind", "made_by", "decided", "alternatives", "reasoning", "tier",
                       "falsifier", "affects", "needs", "needs_reason", "about"}
JUDGEMENT_DEFERRED = {"key", "about", "author", "body"}
FORM_FIELDS = {"form", "kind", "note"}
SIBLING_FIELDS = {"id", "why_separate"}
DIAGNOSTIC_FIELDS = {"verdict", "detail"}


class LoadError(Exception):
    """A shape this loader does not accept. Never caught inside a load: an entry loads whole or not
    at all, so a partial write is impossible."""


def _strict(where, got, allowed):
    extra = set(got) - allowed
    if extra:
        raise LoadError(f"{where}: unknown field(s) {sorted(extra)}. "
                        f"Allowed here: {sorted(allowed)}. "
                        f"If this field is real, add it to migration 032 and to this loader.")


def _require(where, got, required):
    missing = required - set(got)
    if missing:
        raise LoadError(f"{where}: missing required field(s) {sorted(missing)}")


def derive_tier(derived_from, tier_by_key, where):
    """No derived_from is generated, one key is that key's tier, several is the WEAKEST of them.
    A key that names nothing in this entry is an error rather than a skipped link."""
    if not derived_from:
        return "generated"
    tiers = []
    for k in derived_from:
        if k not in tier_by_key:
            raise LoadError(f"{where}: derived_from names {k!r}, which is neither a claim key nor a "
                            f"safety_flag key in this entry")
        tiers.append(tier_by_key[k])
    return min(tiers, key=lambda t: TIER_RANK[t])


def reconcile(conn, library_id, library_canonical):
    """The dual-key reconcile. Returns (link_state, resolved_id, note)."""
    if not library_id:
        return "no_library_id", None, "the entry carries no library_id"
    row = conn.execute("SELECT canonical FROM library_names WHERE library_id = ?",
                       (library_id,)).fetchone()
    if row:
        live = row[0]
        if library_canonical and norm_name(live) != norm_name(library_canonical):
            return ("canonical_drift", library_id,
                    f"id resolves, canonical moved: stored {library_canonical!r}, live {live!r}")
        return "linked", library_id, None
    # The id is gone. Fall back to the snapshot, and only accept an unambiguous match.
    if not library_canonical:
        return "unresolved", None, f"library_id {library_id!r} is not in library_names, and the " \
                                   f"entry carries no canonical to heal from"
    target = norm_name(library_canonical)
    hits = [r[0] for r in conn.execute("SELECT library_id, canonical FROM library_names")
            if norm_name(r[1]) == target]
    if len(hits) == 1:
        return "healed", hits[0], f"library_id {library_id!r} is gone. Healed to {hits[0]!r} by " \
                                  f"canonical {library_canonical!r}"
    return "unresolved", None, (f"library_id {library_id!r} is gone and canonical "
                                f"{library_canonical!r} matched {len(hits)} rows")


def load_entry(conn, path, replace=False):
    """Load ONE entry. Raises LoadError on any shape surprise, before writing anything."""
    path = Path(path)
    doc = tomllib.load(open(path, "rb"))
    _strict(f"{path.name} top level", doc, ENTRY_FIELDS)
    _require(f"{path.name} top level", doc,
             {"id", "name", "review_state", "row_diagnostic", "claims", "prose"})
    eid = doc["id"]

    diag = doc["row_diagnostic"]
    _strict(f"{path.name} [row_diagnostic]", diag, DIAGNOSTIC_FIELDS)
    _require(f"{path.name} [row_diagnostic]", diag, DIAGNOSTIC_FIELDS)

    # --- validate every assertion before any write ---
    assertions, tier_by_key = [], {}
    for kind, field, allowed in (("claim", "claims", CLAIM_FIELDS),
                                 ("safety_flag", "safety_flags", FLAG_FIELDS)):
        for pos, a in enumerate(doc.get(field, [])):
            where = f"{path.name} [[{field}]] #{pos} ({a.get('key')!r})"
            _strict(where, a, allowed)
            _require(where, a, {"key", "text", "tier", "state", "checkable", "source_class", "n"})
            if kind == "safety_flag":
                _require(where, a, {"kind", "surfaces"})
            if a["key"] in tier_by_key:
                raise LoadError(f"{where}: duplicate key {a['key']!r} in this entry")
            tier_by_key[a["key"]] = a["tier"]
            for cpos, ch in enumerate(a.get("chain", [])):
                _strict(f"{where} chain #{cpos}", ch, CHAIN_FIELDS)
                _require(f"{where} chain #{cpos}", ch, {"source", "mode", "read_depth", "taken"})
            for dpos, d in enumerate(a.get("discussion", [])):
                _strict(f"{where} discussion #{dpos}", d, DISCUSSION_FIELDS)
                _require(f"{where} discussion #{dpos}", d, DISCUSSION_FIELDS)
            assertions.append((kind, pos, a))

    for bpos, blk in enumerate(doc["prose"]):
        _strict(f"{path.name} [[prose]] #{bpos}", blk, PROSE_BLOCK_FIELDS)
        _require(f"{path.name} [[prose]] #{bpos}", blk, PROSE_BLOCK_FIELDS)
        for ppos, p in enumerate(blk["piece"]):
            where = f"{path.name} [[prose.piece]] #{ppos}"
            _strict(where, p, PIECE_FIELDS)
            _require(where, p, {"text", "derived_from"})

    judgements = []
    for jpos, j in enumerate(doc.get("judgements", [])):
        where = f"{path.name} [[judgements]] #{jpos}"
        if "id" in j:
            _strict(where, j, JUDGEMENT_CANONICAL)
            _require(where, j, {"id", "decided", "reasoning"})
            if not isinstance(j.get("alternatives", []), list):
                raise LoadError(f"{where}: alternatives must be a LIST, got "
                                f"{type(j['alternatives']).__name__}")
            judgements.append(("canonical", jpos, j))
        else:
            _strict(where, j, JUDGEMENT_DEFERRED)
            _require(where, j, {"key", "author", "body"})
            judgements.append(("deferred", jpos, j))

    for fpos, f in enumerate(doc.get("forms", [])):
        _strict(f"{path.name} [[forms]] #{fpos}", f, FORM_FIELDS)
        _require(f"{path.name} [[forms]] #{fpos}", f, {"form", "kind"})
    for spos, s in enumerate(doc.get("siblings", [])):
        _strict(f"{path.name} [[siblings]] #{spos}", s, SIBLING_FIELDS)
        _require(f"{path.name} [[siblings]] #{spos}", s, {"id"})

    # --- reconcile, then write. One transaction: the entry lands whole or not at all. ---
    state, resolved, note = reconcile(conn, doc.get("library_id"), doc.get("library_canonical"))

    if replace:
        conn.execute("DELETE FROM library_entries WHERE entry_id = ?", (eid,))
    elif conn.execute("SELECT 1 FROM library_entries WHERE entry_id = ?", (eid,)).fetchone():
        raise LoadError(f"{eid} is already loaded. Pass replace=True to reload it.")

    conn.execute(
        """INSERT INTO library_entries (entry_id, name, library_id, library_canonical,
               library_id_resolved, link_state, link_note, review_state, form, cuisine, scope_note,
               possible_parent, diagnostic_verdict, diagnostic_detail, source_file, loaded_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (eid, doc["name"], doc.get("library_id"), doc.get("library_canonical"), resolved, state,
         note, doc["review_state"], doc.get("form"), doc.get("cuisine"), doc.get("scope_note"),
         doc.get("possible_parent"), diag["verdict"], diag["detail"], path.name,
         datetime.datetime.now().isoformat(timespec="seconds")))

    for kind, pos, a in assertions:
        conn.execute(
            """INSERT INTO library_assertions (entry_id, key, assertion_kind, text, tier, state,
                   checkable, source_class, n, mode, rests_on, see_also, cannot_assess, flag_kind,
                   surfaces, allergen, hazard, also, note, needs, needs_reason, position)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (eid, a["key"], kind, a["text"], a["tier"], a["state"], a["checkable"],
             a["source_class"], a["n"], a.get("mode"), a.get("rests_on"), a.get("see_also"),
             json.dumps(a["cannot_assess"]) if "cannot_assess" in a else None,
             a.get("kind"), int(a["surfaces"]) if "surfaces" in a else None, a.get("allergen"),
             a.get("hazard"), a.get("also"), a.get("note"), a.get("needs"), a.get("needs_reason"),
             pos))
        for cpos, ch in enumerate(a.get("chain", [])):
            conn.execute("INSERT OR IGNORE INTO library_sources (source_slug, url) VALUES (?,?)",
                         (ch["source"], ch.get("url")))
            conn.execute(
                """INSERT INTO library_chains (entry_id, key, source_slug, mode, read_depth, taken,
                       cannot_assess, slug, position) VALUES (?,?,?,?,?,?,?,?,?)""",
                (eid, a["key"], ch["source"], ch["mode"], ch["read_depth"], ch["taken"],
                 int(ch["cannot_assess"]) if "cannot_assess" in ch else None, ch.get("slug"), cpos))
        for dpos, d in enumerate(a.get("discussion", [])):
            conn.execute(
                """INSERT INTO library_discussions (entry_id, key, author, body, position)
                   VALUES (?,?,?,?,?)""", (eid, a["key"], d["author"], d["body"], dpos))

    for blk in doc["prose"]:
        slot = blk["slot"]
        for ppos, p in enumerate(blk["piece"]):
            tier = derive_tier(p["derived_from"], tier_by_key,
                              f"{path.name} [[prose.piece]] #{ppos}")
            conn.execute(
                """INSERT INTO library_prose_pieces (entry_id, slot, position, text, resolved_note,
                       cut_note, derived_tier) VALUES (?,?,?,?,?,?,?)""",
                (eid, slot, ppos, p["text"], p.get("resolved_note"), p.get("cut_note"), tier))
            for k in p["derived_from"]:
                conn.execute(
                    """INSERT INTO library_prose_derived_from (entry_id, slot, position, key)
                       VALUES (?,?,?,?)""", (eid, slot, ppos, k))

    for shape, jpos, j in judgements:
        conn.execute(
            """INSERT INTO library_judgements (entry_id, shape, judgement_id, kind, made_by,
                   decided, alternatives, reasoning, tier, falsifier, affects, needs, needs_reason,
                   judgement_key, about, author, body, position)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (eid, shape, j.get("id"), j.get("kind"), j.get("made_by"), j.get("decided"),
             json.dumps(j["alternatives"]) if "alternatives" in j else None, j.get("reasoning"),
             j.get("tier"), j.get("falsifier"),
             json.dumps(j["affects"]) if "affects" in j else None, j.get("needs"),
             j.get("needs_reason"), j.get("key"), j.get("about"), j.get("author"), j.get("body"),
             jpos))

    for fpos, f in enumerate(doc.get("forms", [])):
        conn.execute(
            """INSERT INTO library_forms (entry_id, position, form, kind, note)
               VALUES (?,?,?,?,?)""", (eid, fpos, f["form"], f["kind"], f.get("note")))
    for spos, s in enumerate(doc.get("siblings", [])):
        conn.execute(
            """INSERT INTO library_siblings (entry_id, position, sibling_id, why_separate)
               VALUES (?,?,?,?)""", (eid, spos, s["id"], s.get("why_separate")))

    return {"entry_id": eid, "link_state": state, "resolved": resolved, "note": note,
            "claims": sum(1 for k, _, _ in assertions if k == "claim"),
            "flags": sum(1 for k, _, _ in assertions if k == "safety_flag"),
            "chains": sum(len(a.get("chain", [])) for _, _, a in assertions),
            "discussions": sum(len(a.get("discussion", [])) for _, _, a in assertions),
            "pieces": sum(len(b["piece"]) for b in doc["prose"]),
            "judgements": len(judgements), "forms": len(doc.get("forms", [])),
            "siblings": len(doc.get("siblings", []))}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("entries", nargs="+", help="entry ids or .toml paths")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        for e in args.entries:
            p = Path(e) if e.endswith(".toml") else SOURCED / f"{e}.toml"
            if not p.exists():
                raise LoadError(f"no such entry file: {p}")
            r = load_entry(conn, p, replace=args.replace)
            print(f"loaded {r['entry_id']:20} link_state={r['link_state']:15} "
                  f"claims={r['claims']} flags={r['flags']} chains={r['chains']} "
                  f"disc={r['discussions']} pieces={r['pieces']} judg={r['judgements']} "
                  f"forms={r['forms']}")
            if r["note"]:
                print(f"    note: {r['note']}")
        conn.commit()
    except Exception:
        conn.rollback()
        print("ROLLED BACK - nothing was written.", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
