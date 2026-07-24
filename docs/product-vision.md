# Chef's Choice — Product Vision (recipe-box / multi-user model)

The **source of record** for the product direction decided in planning conversation, written so it
survives across sessions and shapes the rescoping + later stages rather than being re-litigated. The
outcome-data thesis (why ratings/cooks/modifications are the scarce asset) lives in
[OVERVIEW.md](../OVERVIEW.md); this doc records the **multi-user shape** that thesis takes.

## Recipe-box / multi-user model (decided, mostly not-yet-built)

The app is a **social recipe-box**: each user has their OWN recipe box (collection). The used-cookbook
thesis, extended to multi-user — the recipe is the freely-copyable **commodity**; what's YOURS is your
**curated box** plus your **private personal layer** on the recipes in it.

### Core model

- Every recipe belongs to exactly **ONE box** (exactly one owner). `recipes.owner` identifies whose box.
- The **personal layer** (ratings, cooks, per-line edits/additions) is **per-user and private**; you can
  VIEW others' layers (Model A).
- **Copy semantics:** copying someone's recipe **DUPLICATES** it as a NEW recipe owned by YOU (added to
  your box), independent of the original — so you can modify/rate/cook your copy without affecting
  theirs. One recipe, one owner; **copy = duplicate, NOT a shared recipe in multiple boxes** (no join
  table).
- The **ingredient library stays SHARED / app-global** — the `[[key|label]]` linking vocabulary everyone
  draws on. It is NOT boxed or owned.

### Box features (later social/upload stage — needs multiple users live)

- **Pin/favorite** recipes (curate your box).
- **View other people's** boxes/recipes (social/discovery).
- **Copy-into-my-box** (cross-user copy → a new owned recipe). A `copy_recipe` endpoint already exists
  (single-user today); the box model makes it cross-user with `owner = copier`.
- **Recipe upload** (users add their own recipes → owned, in their box).
- No moderation/review.

## Stage boundary — ownership *data model* now, ownership *rules* later

**RESCOPING (now)** — the data model that makes the box possible, nothing more:
- `recipes.owner` (all 298 existing recipes → my box on migration).
- Per-user personal layer: `ratings` PK → `(recipe_id, user_id)`, `cook_log.user_id`, and the change
  layer's `person_id` → `user_id` (zero-data repoint — the change tables are empty).
- All writes scoped to `current_user`.
- Recipes stay **VISIBLE to all** for now: `owner` is a *recorded attribute*, not yet a visibility filter.

**DEFERRED to the upload/social stage** — the ownership **authorization rules**:
- edit/view/delete of others' recipes, list visibility/filtering, pin/favorite, cross-user copy, upload.
- These need **multiple owners live** to design and test correctly. Building them now would mean
  inventing rules against a one-user fiction — so the data model lands first, the rules follow when
  there's real multi-user data to shape them.

## The three-layer product

The whole thing is three layers, each valuable on its own and additive to the last:

1. **Solo core (built).** Your own recipe box + per-user ratings / cooks / edits + scaling and
   ingredient linking. Valuable with **zero friends** — the social layer is **additive, never
   required**. This is the cold-start mitigation: great alone, better together.
2. **Social layer (next stage — what we build next).** A friend graph (below).
3. **Recommendation engine (north-star, later).** Learns your palate from logged data and expands it.

## Social layer (the next stage)

- **Friend graph.** Private-by-default; **mutual connections** ("friends") with people you actually
  know — the early-Facebook model, before the drift to public/algorithmic feeds. The point is
  reconnecting with friends and family over cooking.
- **Sharing — two channels:**
  - **(a) A feed** of friends' shared cooking activity, with **per-event visibility**: a default
    share-setting plus a per-event override (like Facebook's audience control). So you can log *every*
    cook honestly for your own data but only **broadcast** the ones you choose — this resolves the trust
    tension between social sharing and honest logging.
  - **(b) Direct 1:1 sharing** — send a specific recipe / cook / meal to a specific friend (the digital
    "made this, here's the recipe"). Direct share also **doubles as the primary growth mechanism**:
    share-to-a-non-user *is* the invite, threaded through the existing invite-gated signup.
- **Meal photos + people-tagging.** Share a photo of a meal and tag the people you cooked it with/for —
  the social-**occasion** primitive (cooking as a shared human event, not solo logging).
- **Upload.** Users add their own recipes, so boxes are worth sharing. *(Leverages or simplifies the
  existing import pipeline — TBD in a diagnostic.)*
- **Cross-user copy.** Copy a friend's recipe into your box (content-only, clean personal layer —
  already how `copy_recipe` works).

## Governing principle — Connection, not consumption

**First-class, protected like the principles in [SECURITY.md](SECURITY.md).** The feed is for
**connection, not consumption.** We deliberately reject the mechanics that turned Facebook/Instagram
from connection tools into compulsion loops:

- **No notifications** — no manufactured return-pressure.
- **No infinite scroll** — the feed is **bounded** (what your friends actually cooked recently, a finite
  real thing; when you've seen it, you're done — that's a *feature*).
- **No engagement-maximizing algorithmic ranking** — chronological / simple.
- **No loss-aversion mechanics** — no streaks, no guilt.
- **Success = did you reconnect with a friend / find something to cook** — NOT time-on-app or
  scroll-depth.

This is a **counter-positioning** against what those platforms became. It *raises* the bar on
engagement: reasons to return must be **intrinsically valuable** (good recommendations, a genuinely
interesting feed), not manufactured. It must be **protected feature-by-feature** — it's easy to erode
one "just a little ranking to boost engagement" at a time.

## Engagement hooks (the "why open it on a random Tuesday")

- **A — "What should I cook tonight?"** The daily decision ritual, powered by recommendations — the
  highest-frequency cooking-adjacent moment, the home for the recommendation engine, and it strengthens
  as data accumulates. Works **solo, day one**.
- **B — the bounded friends' cooking feed.** The connection engine; anti-scroll per the principle;
  strong at network density.
- **C — cooking achievements** (Xbox-style, **not** Duolingo streaks). Earned/unlockable badges for
  accomplishments + exploration ("cooked 5 different cuisines," "tried a new technique"):
  **reward-for-doing** (celebratory, permanent, invites you forward), never loss-aversion (no "don't
  break the streak"). ⚠️ **Design rule:** achievements reward **variety / exploration / accomplishment**,
  never **volume / frequency** — "cooked 5 cuisines" is good; "cooked 100×" or "30-day streak" is bad
  (that's engagement-farming/compulsion sneaking back in). Achievements for **new cuisines** presage and
  seed the recommendation engine's palate-expansion mission — a day-one, solo-working version of it.

The portfolio spans network density: **A + C work solo / day-one; B is the social engine.**

## Recommendation engine (north-star, later — NOT this stage)

Learns your palate from logged data and recommends **"different but rooted in similar ingredients"**
(e.g. you love doubanjiang Sichuan → try gochujang Korean, sharing the fermented-chili backbone). Two
variants:

- **Ingredient-adjacency** (algorithmic) — the ingredient library + regions/seasons seed the similarity
  model.
- **Friend-proven** (the killer variant, fusing social + reco) — "Sarah's cooked this 8× at 5★, in a
  cuisine you like." Social proof beats an algorithmic guess.

**Dependencies (why it's later):** it needs (1) the social layer live + real multi-user logged data to
fuel it, and (2) a **source of recipes-you-haven't-cooked** to recommend toward — in a private-box world
that's your friends' aggregate boxes, so recommendation diversity depends on network richness. Building
it now (1 user, 298 own-taste-clustered recipes, no network) is building on air. Prototype the
ingredient-adjacency **concept** cheaply on the existing corpus before committing.

## Open strategic gaps (noted, to resolve as we build)

- **Share-to-invite plumbing.** Share to a non-user → link / signup → the shared thing connects to the
  new account; unify with the invite system.
- **Copy trust / attribution.** A friend copying your recipe carries your **edits** (content) but not
  your personal layer; consider attribution ("from Andy's box") and whether the owner is told.
- **A missing forward-looking / planning primitive.** The app is largely **retrospective** (log what you
  cooked); cooking is also **prospective** (what to make this week). A planning/intent primitive ("want
  to make," a queue) is where recommendations land + a natural social prompt — possibly a later addition.
