-- 056_wait_alongside.sql - a wait that happens at the same time as another one.
--
-- ⚠️ A REBUILD, NOT AN ADD COLUMN, AND THAT IS FORCED. SQLite cannot alter a CHECK constraint, and
--    when_kind gains a fourth value. Everything else here is additive, so the table is recreated with
--    the same columns, the same keys and the same indexes, plus one column and three CHECK changes.
--    Live holds 0 recipe_waits rows, so nothing is copied and nothing can be lost in the copy.
--    Nothing references recipe_waits with a foreign key, so the DROP is safe with foreign_keys ON.
--
-- ⚠️ WHY A WAIT NEEDS THIS AT ALL. morning-buns chills the DOUGH overnight at step 5 and the BUTTER
--    BLOCK overnight at step 7, and step 8 opens "The next day". They are one night, not two, and
--    summing both told a cook to set aside 25 hr for a recipe that needs about 17. A wait that
--    overlaps another is real and worth reading, and it is not time to block out twice.
--
-- ⚠️ IT POINTS AT A STEP, NEVER AT A WAIT. write_plan_ahead deletes and reinserts every wait row on
--    every save, so a wait id is not a thing that survives being referenced. The step it overlaps
--    does survive, because a save updates step rows in place (option C), so the overlap is recorded
--    as "the wait that happens at this step" and resolved through the step.
--
-- ⚠️ IT DOES NOT REACH THE TOTAL, AND THAT NEEDED NO CODE. planahead.counts already answers "only an
--    unconditional wait counts", i.e. when_kind = 'always', so a fourth value is excluded by the rule
--    that was already there. The breakdown still lists it, with its qualifier, exactly as an optional
--    wait is listed.
--
-- TWO NEW CHECKS:
--   * a wait cannot run alongside its OWN step, which would say nothing;
--   * the existing when_kind list gains 'alongside' and nothing else.
--
-- ⚠️ A THIRD CHECK WAS WRITTEN AND THEN REMOVED, and the reason is worth keeping. "an 'alongside' wait
--    must name the step it runs alongside" reads as an obvious invariant and CONTRADICTS the foreign
--    key beside it. ON DELETE SET NULL says a pointer at a deleted step becomes null; that CHECK said
--    an alongside row may not hold a null pointer. Both cannot hold once the step is deleted, and the
--    DELETE loses: it fails with a CHECK violation instead of clearing the link.
--
--    That is not hypothetical. write_recipe_rows deletes removed step rows BEFORE write_plan_ahead
--    rewrites the waits, so a cook who deleted a step another wait ran alongside would have got a 500
--    and lost the whole edit. A test caught it.
--
--    So the FK wins, because it is the half that keeps the data safe, and "an alongside wait overlaps
--    something" is enforced where it can be enforced without lying: write_plan_ahead falls back to
--    'always' when there is no usable target, and planahead.counts treats an alongside wait whose step
--    is gone as an ordinary wait that DOES reach the total, since it no longer overlaps anything.

CREATE TABLE recipe_waits_new (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id         TEXT    NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    position          INTEGER NOT NULL,
    kind              TEXT    NOT NULL,
    label             TEXT    NOT NULL,
    min_minutes       INTEGER,
    max_minutes       INTEGER,
    ext_label         TEXT,
    ext_min_minutes   INTEGER,
    ext_max_minutes   INTEGER,
    when_kind         TEXT    NOT NULL DEFAULT 'always',
    when_label        TEXT,
    step_id           INTEGER REFERENCES recipe_steps(id) ON DELETE SET NULL,
    alongside_step_id INTEGER REFERENCES recipe_steps(id) ON DELETE SET NULL,
    CHECK (when_kind IN ('always','optional','only_if','alongside')),
    CHECK (when_kind <> 'only_if' OR when_label IS NOT NULL),
    CHECK (alongside_step_id IS NULL OR alongside_step_id <> step_id),
    CHECK (kind IN ('marinating','chilling','rising','soaking','resting','freezing','brining','other')),
    CHECK (min_minutes IS NULL OR min_minutes >= 0),
    CHECK (max_minutes IS NULL OR min_minutes IS NULL OR max_minutes >= min_minutes),
    CHECK (ext_max_minutes IS NULL OR ext_min_minutes IS NULL OR ext_max_minutes >= ext_min_minutes),
    CHECK (ext_label IS NOT NULL OR (ext_min_minutes IS NULL AND ext_max_minutes IS NULL)),
    UNIQUE (recipe_id, position)
);

INSERT INTO recipe_waits_new (id, recipe_id, position, kind, label, min_minutes, max_minutes,
                              ext_label, ext_min_minutes, ext_max_minutes, when_kind, when_label,
                              step_id)
    SELECT id, recipe_id, position, kind, label, min_minutes, max_minutes,
           ext_label, ext_min_minutes, ext_max_minutes, when_kind, when_label, step_id
    FROM recipe_waits;

DROP TABLE recipe_waits;
ALTER TABLE recipe_waits_new RENAME TO recipe_waits;

CREATE INDEX idx_recipe_waits_recipe ON recipe_waits(recipe_id);
CREATE INDEX idx_recipe_waits_min    ON recipe_waits(min_minutes);
CREATE INDEX idx_recipe_waits_when   ON recipe_waits(when_kind);
