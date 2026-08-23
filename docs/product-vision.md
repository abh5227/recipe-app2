# Chef's Choice — Product Vision (recipe-box / multi-user model)

The **source of record** for the product direction decided in planning conversation, written so it
survives across sessions and shapes the rescoping + later stages rather than being re-litigated. The
outcome-data thesis (why ratings/cooks/modifications are the scarce asset) lives in
[OVERVIEW.md](../OVERVIEW.md); this doc records the **multi-user shape** that thesis takes.

## What this is really about (the north-star feeling)

Every principle below serves one feeling. Before the model, before the mechanics, this is the thing
they protect:

> There is a man in Kansas City who starts the meat at three in the morning for a meal at four in the
> afternoon. He tends a fire that does not need watching. He keeps a promise to people who do not know
> he is awake. When they eat, he says nothing about the thirteen hours; he eats his own plate standing
> up. **Dave did not tell them.**
>
> *"I would like it recorded somewhere, by someone. In case I was called upon to do this alone, I wrote
> down: oak. A man does not hand his fire to a stranger — this is an adoption. I have bought a black
> iron drum. I do not yet know anyone here well enough to feed. **I am starting the fire anyway.**"*

**The recipe is nothing; the CARE is everything.** The app records the *caring* — ratings, cook-history,
annotations, the residue of someone tending a fire before anyone arrives — **not** the food. This is the
used-cookbook thesis felt rather than argued.

**Why Dave is the anchor** — every enshrined principle is a way of protecting this:

- **Record the care, NEVER farm it.** *"Dave did not tell them."* No likes, no counts, no notifications,
  no scoreboard — each rejected mechanic is the refusal to make Dave announce he was awake at 3am. The
  moment care becomes performance it stops being Dave and becomes **content**. ⭐ **THE TEST for any
  feature:** *"Is this Dave — or is this the thing that would make Dave tell everyone?"*
- **You hand your fire to known people.** *"A man does not hand his fire to a stranger — this is an
  adoption."* The friend graph is private, mutual, earned — an adoption, not an audience to impress.
- **Growth over perfection.** *"In case I was called upon to do this alone, I wrote down: oak."* The
  beginner learning badly and earnestly is welcome; post the embarrassing cooks. Dave's silence about
  the thirteen hours was a kindness, not a highlight reel.
- ⭐ **Start the fire anyway** — the cold-start answer. *"I do not yet know anyone here well enough to
  feed. I am starting the fire anyway."* The solo core is **not** a consolation for having no friends
  yet; it is **Dave at 3am**. The app is great alone because **tending the fire is the point** — watched
  or not.

Everything that follows — **connection-not-consumption, no-counts, failure-acceptance, private-mutual
friends** — exists to keep this feeling intact. **When a decision is unclear, check it against Dave.**

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

### Comments — connection, never engagement machinery

The feed supports **COMMENTS** (conversation between friends) but deliberately rejects the engagement
apparatus that comments usually drag in:

- **COMMENTS YES** (words — a friend saying "how'd you get that char?" is the reconnection the app
  exists for). **LIKES/REACTIONS NEVER** (a like is a one-tap validation **metric** that produces a
  count/scoreboard — pure consumption-farming, adds nothing to connection). Words connect; taps/counts
  farm engagement. This **"comments yes, likes never"** line IS the concrete test of
  connection-not-consumption.
- **No comment-count as a displayed metric** — you see the conversation itself; no "12 comments" vanity
  number.
- ⭐ **NO NOTIFICATIONS OF ANY KIND** — not push, not email, not even an in-app badge that pulls. A
  friend's comment is seen ONLY by opening the app and looking. The app NEVER reaches out or summons the
  user. People return because the thing is valuable, not because it nagged them. (This is the strongest
  expression of the principle: remove every mechanism by which the app could pull you back.)
- **Friends-only** — comment on friends' posts, bounded to your real network, private (consistent with
  private-by-default).
- **Delete your own comments;** the post owner can remove comments on their post (light,
  it's-your-post moderation).

The point: comments are the **conversation** (connection); everything that would turn them into an
engagement loop (likes, counts, notifications) is rejected. Built this way, commenting **fulfills** "I
want my friends to really connect" rather than eroding it.

### No counts anywhere — a community, not a leaderboard

**NO DISPLAYED COUNTS OF ANYTHING.** No follower/friend count ("N friends"), no post/share count, no
like count, no comment count — nothing tallied, anywhere. This is the same family as **no-likes**:
counting anything is the **first inch** of the scoreboard / competition dynamic the principle rejects,
and it erodes exactly one "harmless little number" at a time. A community, not a leaderboard.

- The feed is **bounded/finite by simply ENDING** — the last post is the last, and it just stops.
  **NEVER** by announcing a tally ("that's all 12 posts"). Finitude is expressed by *running out*, not
  by *counting*.
- Applies to every surface: friends list, profile, feed, comments. You see the **things themselves**
  (the friends, the posts, the conversation) — never a number summarizing them.

### Failure-acceptance — growth over performance (foundational)

Cooking is **mostly failure + iteration** — the truth the highlight-reel platforms hide. Chef's Choice
**welcomes the embarrassing cook**: posting a flop is normal, safe, and encouraged. This is the
**deepest form of connection-over-performance** (you connect over the real thing, not a curated
performance), and it also **lowers the posting barrier** (if only triumphs are postable, most people
post nothing). We grow together; we don't perform a highlight reel.

- **Expressed as light-touch CULTURE, not heavy MECHANICS.** The warmth lives in **copy + tone** — share
  prompts, the empty state, onboarding gently invite the *real* story (including the failures). It does
  **NOT** become a "flops feature" or "failure badges": a dedicated failure-mechanic would just create a
  **new** performance pressure (performing relatability / competitive humility) — the very thing we're
  escaping. Keep it culture, not a gameable feature.
- **Backed by growth-oriented achievements** (see below) — perseverance/iteration as *one* rewarded
  category, never a flop-counter.

## Engagement hooks (the "why open it on a random Tuesday")

- **A — "What should I cook tonight?"** The daily decision ritual, powered by recommendations — the
  highest-frequency cooking-adjacent moment, the home for the recommendation engine, and it strengthens
  as data accumulates. Works **solo, day one**.
- **B — the bounded friends' cooking feed.** The connection engine; anti-scroll per the principle;
  strong at network density.
- **C. Cooking achievements.** Hidden until earned. You never see a list and work toward it. You cook a
  Thai curry, then a Vietnamese soup, then something Cambodian, and the app tells you afterwards that
  you have cooked across Southeast Asia. You did not aim at it. You find out that you did it. That is
  what separates this from a points system. ⚠️ **Design rule:** achievements reward **range**, never
  **repetition**. "Cooked 5 cuisines" is good. "Cooked 100 times" and "30-day streak" are bad, because
  that is engagement farming coming back in. Nothing counts down and nothing can be lost, so there is
  no "don't break the streak." The cuisine achievements seed the recommendation engine's
  palate-expansion mission and give it a version that works on day one, for one person, alone.

The portfolio spans network density: **A + C work solo / day-one; B is the social engine.**

### Achievements: hidden until earned, private, awarded for range

**Hidden until earned.** There is no checklist and nothing to aim at. The app reads what you have
already cooked, finds a pattern in it, and tells you about the pattern afterwards. This is the part
that defines the feature. A visible list turns cooking into task completion. A hidden one turns it
into something you find out about yourself.

**The purpose is educational, and it works sideways.** Cooking one dish teaches you an ingredient.
That ingredient turns up in a cuisine you have not tried. The achievement is the app noticing a
pattern in what you already cooked and pointing at what sits next to it. Someone learns what galangal
is by cooking with it, and that changes what they order in a restaurant a year later. The knowledge is
the reward. The achievement is how you notice you have it.

**Private.** Nobody else sees them. Nothing is ranked, nothing is compared, and there is no score.
Private means private from other people. It does not mean hidden from the person who earned it. Once
you earn one it sits on your own profile page and you can go and look at it whenever you want.

Hook C is broad by design. It rewards across several categories:

- **EXPLORATION and variety.** New cuisines, techniques, ingredients. These tie to the recommendation
  engine and seed hook A's palate-expansion mission.
- **GROWTH and perseverance.** Trying, iterating, cooking through difficulty. This is the
  **failure-acceptance category** made concrete. It marks the attempt and the iteration, not a
  flawless result.
- **ACCOMPLISHMENT.** Genuine milestones worth marking.

All three sit under one rule. Reward **range**, never **repetition**. "Cooked 5 cuisines" is good.
"Cooked 100 times" and "30-day streak" are bad, because that is compulsion farming sneaking back.
Growth is one type among several, the exploration ones sit alongside it, and the whole system stays
light-touch. Achievements live on the chef **PROFILE**, a place you *visit*, and **NOT** as a surround
widget or an always-on dashboard metric. Surfacing a score everywhere would rebuild the scoreboard the
no-counts principle rejects.

### The moat — where the differentiation lives

The differentiator is NOT the feature list (friend graph, feed, upload, copy, achievements are table
stakes — anyone can build them). It's that hooks A and B are GENUINELY GOOD:

- **A** ("what should I cook tonight" / recommendations) is good only if the recommendations are good —
  which is a **CULINARY-EXPERTISE** problem as much as an algorithm one (knowing WHY dishes are
  ingredient-adjacent — e.g. the fermented-chili backbone linking doubanjiang & gochujang — is culinary
  knowledge, not collaborative filtering). This is domain expertise encoded into the ingredient-adjacency
  model (the ingredient library + regions/seasons is the start of that encoded knowledge).
- **B** (the feed) is good only if it fosters **CONNECTION not consumption** — a product-TASTE +
  RESTRAINT problem, not an engineering one. The hard part isn't building a feed; it's keeping it
  bounded/un-addictive/connection-focused against every industry instinct to do the opposite.

**IMPLICATION for effort allocation:** build the table-stakes social plumbing (friend graph, upload, feed
mechanics, copy, achievements) SOLIDLY but WITHOUT gold-plating — it's the foundation, not the moat.
Reserve the deep thought for A's recommendation quality and B's connection-discipline. Guard against
drift into over-engineering the plumbing instead of investing in the moat.

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
  *(Resolved by the grounding pass: it already exists latently — see sub-stage 3 below.)*

## Social-layer build plan (finalized — sub-stage by sub-stage, diagnostic-first each)

The concrete build sequence for the social layer, decided after a read-only grounding pass against the
real schema + data. Each sub-stage is its own diagnostic-first stage (read-only diagnostic → build with
STOP-for-review → reconcile + commit + CI), dual-source where it touches schema. Ordered cheap-and-
foundational first; the one expensive, risk-concentrated piece (photos) is built LAST and isolated.

1. **FRIEND GRAPH.** A `friendships` join table (`requester_id`, `addressee_id`, `status`
   pending/accepted, timestamps, composite PK), with request → accept → list. Cheap and foundational —
   everything social needs "who are my friends" first. Clean `users` base needs nothing added; reuses the
   established reference-FK / composite-PK idiom. Dual-source (migration + Alembic).

2. **FEED + DELIBERATE SHARE.** ⚠️ **KEY DECISION: the feed is DELIBERATE, not automatic.** Logging
   (`cook_log` / `ratings`) stays **ALWAYS-PRIVATE** — your honest record, for you + your data. **Sharing
   is a separate opt-in act** (you share a cook you're proud of / a recipe / later a meal photo). A share
   creates a **feed POST** in a small `shared_posts` table (references the shared thing, a share-timestamp,
   and an optional caption). The feed = friends' deliberately-shared posts, **chronological by share-time,
   bounded**. This is better than the grounding-pass alternatives on two counts: it **kills the cook_log
   recency wrinkle by construction** (share-time IS feed-time — no conflation with the backdatable
   `cooked_on`), and it is **connection-aligned by design** (curated proud moments, not an auto-broadcast
   firehose — the *connection-not-consumption* principle built in, not bolted on). Explicitly **NOT** the
   grounding-pass's "derive-from-cook_log + visibility flag" (that was the auto-broadcast model we
   **rejected**); **NOT** an auto `activity_events` table. A deliberate-share table is **smaller** (only
   shared things) and **correct**.

3. **WANT-TO-MAKE QUEUE + SHARING.** Promote the latent **"To Make"** category tag (**133 real rows — no
   cold start**) to a structured queue: the forward-looking / planning primitive (Gap-3 above — which, it
   turns out, already exists in the data). It's where hook-A recommendations **land**, and a natural
   **prospective** social post ("Andy wants to make X"). PLUS the sharing mechanics: **direct 1:1 recipe
   share** + **share-as-invite** (extend `invites` with `shared_recipe_id` + **auto-friend on consume** —
   `created_by` already records the sharer). *(Cross-user copy is already done — `copy_recipe` is
   owner-agnostic + content-only.)*

4. **MANUAL ADD-RECIPE FORM.** `create_recipe` already does per-user structured upload server-side (sets
   `owner=current_user`, full ingredient/step validation) — this sub-stage is **just the client form**.
   Cheap.

5. **MEAL PHOTOS + PEOPLE-TAGGING.** **EXPENSIVE + risk-concentrated** — the **ONLY** untrusted-binary-
   input surface (no file-upload endpoint exists anywhere in the backend today). Needs a real **multipart
   upload endpoint** + a `meal_photos` table + a `meal_photo_tags` join. Built **LAST**, **ISOLATED**,
   with real [SECURITY.md](SECURITY.md) care: size limits, content-type sniffing, filename sanitation,
   decompression-bomb guards, path safety. `process_photo()` (`scripts/backfill_photos.py`) is the
   image-processing head-start; the request wrapper + storage + hardening are **net-new**.

**Guards to fold in when the visibility filter lands** (deferred with the ownership rules, not this
sequence): filter `source='test'` recipes OUT of boxes/feeds; the owner-based read filter is what converts
the *recorded* `owner` into an actual **box** (no data migration — a read-side filter only).

**Durability — the moat's culinary-knowledge seed already exists in the schema.** Hook A / the later
recommendation engine won't start from nothing: `ingredients.pairs` is **36/36 hand-authored adjacency
text**, plus **44 regions / 102 ingredient-region links / 65 seasons** — a real head start for the
ingredient-adjacency model (the "culinary knowledge, not collaborative filtering" the moat names).

### Build state (where the sequence stands)

The repo is the continuity record; this is where the social sequence actually stands:

- **Sub-stage 1 — friend graph:** ✅ **COMMITTED.** `friendships` table + request/accept/list/unfriend
  endpoints, dual-source (migration + Alembic).
- **Sub-stage 2a — deliberate-share feed BACKEND:** ✅ **COMMITTED.** `shared_posts` table +
  create/delete-share + `GET /api/feed`, dual-source.
- **Comments BACKEND:** ✅ **COMMITTED.** `comments` table + add/delete endpoints + comments embedded
  in the feed serializer (batched), friends-only authz, dual-source.
- **Sub-stage 2b — the CLIENT (the composed feed page):** ⏳ **NEXT / in progress.** Build the composed
  feed page **to the locked design spec** (see *The social feed — composed page design* in
  [design-decisions.md](design-decisions.md); §§ layout, color, type, post, comments, avatar), wired to
  the **existing** endpoints — `GET /api/feed`, `POST`/`DELETE /api/shares`,
  `POST /api/posts/<id>/comments`, `DELETE /api/comments/<id>`. Kalam bundled self-hosted; **placeholder
  avatar** (simple hat/initials — the characterful hand-drawn hat is a dedicated later task); the
  **real-now surround** = left nav + Your Friends (from the friend graph) + honest **`SOON`** slots for
  Profile / Want-to-make / Cook-it-again. **OPEN decision:** In-Season is either a small seasons-data
  endpoint (the data exists) **or** a `SOON` slot — decide at build time. Responsive. **MANDATORY manual
  browser click-through before commit** (it's UI). The 2b design was iterated across **~8 preview
  rounds**; the spec is the **LOCKED result** — a new chat should **build to it, not re-derive it**.
- **After 2b** (per the plan above): want-to-make queue + sharing (direct 1:1 + share-as-invite) →
  manual add-recipe form → meal-photos + tagging (expensive / security-focused / **last**).
