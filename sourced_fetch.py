# -*- coding: utf-8 -*-
"""Fetch Wikipedia lead text, the scientific name and a licence-checked Commons image.

⚠️ THE BRIDGE IS THE NAME, NEVER P279. Our catalog rows are Wikidata's culinary-sense items and the
   articles live on the species items. Following subclass edges lands on the parent category, which
   puts Vegetable on onion and Fruit on tomato. That looks like a success and is not one. Every
   attachment here comes from a sitelink or from the row's own name, and match_basis records which.

⚠️ image_license IS A GATE. A file with no readable free licence is stored with a NULL and must not
   render. Commons licences vary per file and a filename grants nothing.
"""
import collections, json, re, sqlite3, sys, time, urllib.parse, urllib.request

UA = "ChefsChoice-library/0.1 (personal recipe app; contact andyhannah2014@gmail.com)"
PAUSE = 0.12                       # courtesy delay between calls
# ⚠️ NO TITLE HEURISTIC. Matching a two-word title called 'Wheat flour' and 'House cricket'
# binomials. The scientific name comes from Wikidata P225 on the ARTICLE'S OWN item, which is
# authoritative, and the parenthetical below is only the fallback when the item states none. The
# parenthetical must close on the binomial so a comma-separated common-name list is rejected.
# ⚠️ THE LEADING \s IS LOAD-BEARING. Without it "Kàsù(Boki language)" in the alligator pepper
# lead parsed as a binomial. A real binomial gloss is written with a space before the paren.
BINOMIAL = re.compile(r"(?:^|\s)\(\s*([A-Z][a-z]{2,}\s+[a-z][a-z\-]{2,})\s*(?:\)|var\.|subsp\.)")

def api(url, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read())
        except Exception as e:
            if k == tries - 1:
                print(f"   ! giving up on a call: {type(e).__name__}", flush=True)
                return {}
            time.sleep(1.5 * (k + 1))
    return {}

def chunks(xs, n):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield xs[i:i + n]

def usable_image(code, short, restrictions):
    """⚠️ Conservative on purpose. No code, or a non-commercial or no-derivatives term, or any
    restriction, means the file stays dark. GFDL alone has no machine code and is not accepted."""
    if restrictions:
        return None
    c = (code or "").lower()
    s = (short or "")
    if not c:
        return None
    if "nc" in c.split("-") or "nd" in c.split("-"):
        return None
    if c.startswith("cc-") or c.startswith("pd") or "public" in c:
        # ⚠️ NEVER RETURN AN EMPTY STRING. '' is not NULL, so it would pass the render gate while
        #    naming no licence at all. Fall back to the machine code, and refuse if both are blank.
        label = (s or "").strip() or c.strip()
        return label or None
    return None

def strip_html(t):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t or "")).strip()

def run(db, limit=None):
    t0 = time.time()
    conn = sqlite3.connect(db)
    rows = list(conn.execute("SELECT library_id, canonical FROM library_names"))
    if limit: rows = rows[:limit]
    canon = dict(rows)
    qids = [i for i, _ in rows if i.startswith("Q") and i[1:].isdigit()]
    print(f"catalog rows {len(rows):,}, of which Q-ids {len(qids):,}", flush=True)

    # ---- stage A: sitelinks, the authoritative bridge where one exists -------------------
    title_of, basis = {}, {}
    for n, batch in enumerate(chunks(qids, 50), 1):
        d = api("https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props=sitelinks"
                "&sitefilter=enwiki&ids=" + "|".join(batch))
        for q, ent in (d.get("entities") or {}).items():
            t = ((ent.get("sitelinks") or {}).get("enwiki") or {}).get("title")
            if t: title_of[q] = t; basis[q] = "sitelink"
        if n % 20 == 0: print(f"   sitelinks {n*50:,}/{len(qids):,}  found {len(title_of):,}", flush=True)
        time.sleep(PAUSE)
    print(f"A. sitelinks: {len(title_of):,} of {len(qids):,} Q-ids carry an enwiki article", flush=True)

    # ---- stage B: the NAME bridge for everything else ------------------------------------
    need = [i for i, _ in rows if i not in title_of]
    print(f"B. resolving {len(need):,} rows by name", flush=True)
    rejected = collections.Counter()
    for n, batch in enumerate(chunks(need, 50), 1):
        names = [canon[i] for i in batch]
        d = api("https://en.wikipedia.org/w/api.php?action=query&format=json&redirects=1"
                "&prop=pageprops&ppprop=wikibase_item|disambiguation&titles="
                + urllib.parse.quote("|".join(names)))
        q = d.get("query") or {}
        norm = {x["from"]: x["to"] for x in q.get("normalized", [])}
        redir = {x["from"]: x["to"] for x in q.get("redirects", [])}
        pages = {p.get("title"): p for p in (q.get("pages") or {}).values()}
        for lid, nm in zip(batch, names):
            t = redir.get(norm.get(nm, nm), norm.get(nm, nm))
            pg = pages.get(t)
            if not pg or "missing" in pg: rejected["no article"] += 1; continue
            if "disambiguation" in (pg.get("pageprops") or {}): rejected["a disambiguation page"] += 1; continue
            came_via_redirect = norm.get(nm, nm) in redir
            title_of[lid] = t
            basis[lid] = "redirect" if came_via_redirect else "title"
        if n % 20 == 0: print(f"   names {n*50:,}/{len(need):,}  total titles {len(title_of):,}", flush=True)
        time.sleep(PAUSE)
    print(f"B. after the name bridge: {len(title_of):,} rows have a title. rejected {dict(rejected)}", flush=True)

    # ---- stage C: the lead text, batched 20 at a time ------------------------------------
    want = sorted({t for t in title_of.values()})
    print(f"C. fetching lead text for {len(want):,} distinct articles", flush=True)
    lead, revid = {}, {}
    for n, batch in enumerate(chunks(want, 20), 1):
        d = api("https://en.wikipedia.org/w/api.php?action=query&format=json&redirects=1"
                "&prop=extracts|revisions&exintro=1&explaintext=1&exlimit=20&rvprop=ids&titles="
                + urllib.parse.quote("|".join(batch)))
        for p in ((d.get("query") or {}).get("pages") or {}).values():
            t = p.get("title")
            if p.get("extract"): lead[t] = p["extract"]
            rv = (p.get("revisions") or [{}])[0]
            if rv.get("revid"): revid[t] = rv["revid"]
        if n % 25 == 0: print(f"   extracts {n*20:,}/{len(want):,}  got {len(lead):,}", flush=True)
        time.sleep(PAUSE)
    print(f"C. lead text for {len(lead):,} articles ({time.time()-t0:.0f}s so far)", flush=True)

    # ---- stage C2: the scientific name, from P225 on the ARTICLE'S item ------------------
    print(f"C2. reading the article items for a taxon name", flush=True)
    art_q = {}
    for n, batch in enumerate(chunks(want, 50), 1):
        d = api("https://en.wikipedia.org/w/api.php?action=query&format=json&prop=pageprops"
                "&ppprop=wikibase_item&titles=" + urllib.parse.quote("|".join(batch)))
        for p_ in ((d.get("query") or {}).get("pages") or {}).values():
            q = (p_.get("pageprops") or {}).get("wikibase_item")
            if q and p_.get("title"): art_q[p_["title"]] = q
        time.sleep(PAUSE)
    taxon = {}
    inv = collections.defaultdict(list)
    for t_, q in art_q.items(): inv[q].append(t_)
    for n, batch in enumerate(chunks(sorted(inv), 50), 1):
        d = api("https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props=claims"
                "&ids=" + "|".join(batch))
        for q, ent in (d.get("entities") or {}).items():
            for st in ((ent.get("claims") or {}).get("P225") or []):
                v = (((st.get("mainsnak") or {}).get("datavalue") or {}).get("value"))
                if isinstance(v, str):
                    for t_ in inv.get(q, []): taxon[t_] = v
                    break
        time.sleep(PAUSE)
    print(f"C2. P225 taxon name on {len(taxon):,} of {len(want):,} articles", flush=True)

    # ---- stage D: P18 from the LOCAL wikidata claims, then Commons licences --------------
    src = sqlite3.connect("file:sources.db?mode=ro", uri=True)
    p18 = {}
    for q, raw in src.execute("SELECT entry_id, raw FROM wikidata_entry"):
        if q not in canon: continue
        try: cl = (json.loads(raw).get("claims") or {})
        except Exception: continue
        for st in cl.get("P18") or []:
            v = (((st.get("mainsnak") or {}).get("datavalue") or {}).get("value"))
            if isinstance(v, str): p18[q] = v; break
    src.close()
    files = sorted({v for v in p18.values()})
    print(f"D. P18 filenames held locally: {len(p18):,} rows, {len(files):,} distinct files", flush=True)
    lic = {}
    for n, batch in enumerate(chunks(files, 50), 1):
        d = api("https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo"
                "&iiprop=url|extmetadata|mime&iiurlwidth=640&titles="
                + urllib.parse.quote("|".join("File:" + f for f in batch)))
        for p in ((d.get("query") or {}).get("pages") or {}).values():
            ii = (p.get("imageinfo") or [{}])[0]; em = ii.get("extmetadata") or {}
            g = lambda k: (em.get(k) or {}).get("value")
            ok = usable_image(g("License"), g("LicenseShortName"), g("Restrictions"))
            fn = (p.get("title") or "")[5:]
            lic[fn] = {"license": ok, "url": ii.get("thumburl") if ok else None,
                       "attribution": strip_html(g("Artist")) if ok else None}
        if n % 20 == 0: print(f"   commons {n*50:,}/{len(files):,}", flush=True)
        time.sleep(PAUSE)
    ok_n = sum(1 for v in lic.values() if v["license"])
    print(f"D. licences read for {len(lic):,} files, usable {ok_n:,}", flush=True)

    # ---- write ---------------------------------------------------------------------------
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    wrote = 0
    conn.execute("BEGIN")
    for lid, _ in rows:
        t = title_of.get(lid)
        if not t: continue
        txt = lead.get(t)
        sci = taxon.get(t)
        if not sci and txt:
            m = BINOMIAL.search(txt[:300])
            if m: sci = m.group(1)
        f = p18.get(lid); L = lic.get(f or "", {})
        conn.execute(
            "INSERT OR REPLACE INTO library_sourced_content (library_id,source,source_title,source_url,"
            "source_revision,match_basis,sourced_description,scientific_name,license,attribution,"
            "sourced_image,image_url,image_license,image_attribution,fetched_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (lid, "wikipedia", t, "https://en.wikipedia.org/wiki/" + urllib.parse.quote(t.replace(" ", "_")),
             revid.get(t), basis[lid], txt, sci, "CC-BY-SA-4.0",
             "Wikipedia contributors. Text available under the Creative Commons Attribution-ShareAlike 4.0 License.",
             f, L.get("url"), L.get("license"), L.get("attribution"), now))
        wrote += 1
    conn.commit(); conn.close()
    print(f"WROTE {wrote:,} rows in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    run(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None)
