"""the sourced ingredient library, stage 1 (mirrors migrations/032_library_entries.sql)

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-09-06 23:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, Sequence[str], None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Mirrors migrations/032_library_entries.sql. Read that file for why each shape is what it is.
    # The three decisions worth repeating here:
    #   - claims and safety flags share ONE table with a discriminator, because 6 prose pieces and
    #     1 judgement reference a flag key the same way they reference a claim key. Two tables would
    #     need a polymorphic reference and a two-table loader drops those 7 links.
    #   - judgements hold TWO shapes. 17 canonical, 3 deferred (a decision recorded as NOT made).
    #     Forcing the 3 into the canonical shape would invent a decision nobody made.
    #   - nothing here touches `ingredients`. Sourced prose lands in library_prose_pieces, never in
    #     ingredients.descr, which build_db's seed_content overwrites on every run.
    # library_id is NOT a foreign key to library_names, for migration 030's reason. link_state is
    # how a dangling id gets reported instead.
    op.create_table(
        'library_entries',
        sa.Column('entry_id', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('library_id', sa.Text(), nullable=True),
        sa.Column('library_canonical', sa.Text(), nullable=True),
        sa.Column('library_id_resolved', sa.Text(), nullable=True),
        sa.Column('link_state', sa.Text(), nullable=False),
        sa.Column('link_note', sa.Text(), nullable=True),
        sa.Column('review_state', sa.Text(), nullable=False),
        sa.Column('form', sa.Text(), nullable=True),
        sa.Column('cuisine', sa.Text(), nullable=True),
        sa.Column('scope_note', sa.Text(), nullable=True),
        sa.Column('possible_parent', sa.Text(), nullable=True),
        sa.Column('diagnostic_verdict', sa.Text(), nullable=False),
        sa.Column('diagnostic_detail', sa.Text(), nullable=False),
        sa.Column('source_file', sa.Text(), nullable=False),
        sa.Column('loaded_at', sa.Text(), nullable=False),
        sa.CheckConstraint(
            "link_state IN ('linked','canonical_drift','healed','unresolved','no_library_id')"),
        sa.PrimaryKeyConstraint('entry_id'),
    )
    op.create_index('idx_lib_entries_library_id', 'library_entries', ['library_id_resolved'])
    op.create_index('idx_lib_entries_link_state', 'library_entries', ['link_state'])

    op.create_table(
        'library_assertions',
        sa.Column('entry_id', sa.Text(), nullable=False),
        sa.Column('key', sa.Text(), nullable=False),
        sa.Column('assertion_kind', sa.Text(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('tier', sa.Text(), nullable=False),
        sa.Column('state', sa.Text(), nullable=False),
        sa.Column('checkable', sa.Text(), nullable=False),
        sa.Column('source_class', sa.Text(), nullable=False),
        sa.Column('n', sa.Integer(), nullable=False),
        sa.Column('mode', sa.Text(), nullable=True),
        sa.Column('rests_on', sa.Text(), nullable=True),
        sa.Column('see_also', sa.Text(), nullable=True),
        sa.Column('cannot_assess', sa.Text(), nullable=True),
        sa.Column('flag_kind', sa.Text(), nullable=True),
        sa.Column('surfaces', sa.Integer(), nullable=True),
        sa.Column('allergen', sa.Text(), nullable=True),
        sa.Column('hazard', sa.Text(), nullable=True),
        sa.Column('also', sa.Text(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('needs', sa.Text(), nullable=True),
        sa.Column('needs_reason', sa.Text(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.CheckConstraint("assertion_kind IN ('claim','safety_flag')"),
        sa.CheckConstraint("tier IN ('generated','curated','cited')"),
        sa.CheckConstraint("state IN ('settled','unresolved')"),
        sa.CheckConstraint("assertion_kind = 'safety_flag' OR (flag_kind IS NULL AND surfaces IS NULL"
                           " AND allergen IS NULL AND hazard IS NULL)"),
        sa.CheckConstraint("assertion_kind = 'claim' OR flag_kind IS NOT NULL"),
        sa.ForeignKeyConstraint(['entry_id'], ['library_entries.entry_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('entry_id', 'key'),
    )
    op.create_index('idx_lib_assertions_kind', 'library_assertions', ['assertion_kind'])
    op.create_index('idx_lib_assertions_tier', 'library_assertions', ['tier'])

    # url is nullable: one chain names 'repo: weights.py', an internal file with no URL.
    op.create_table(
        'library_sources',
        sa.Column('source_slug', sa.Text(), nullable=False),
        sa.Column('url', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('source_slug'),
    )

    op.create_table(
        'library_chains',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('entry_id', sa.Text(), nullable=False),
        sa.Column('key', sa.Text(), nullable=False),
        sa.Column('source_slug', sa.Text(), nullable=False),
        sa.Column('mode', sa.Text(), nullable=False),
        sa.Column('read_depth', sa.Text(), nullable=False),
        sa.Column('taken', sa.Text(), nullable=False),
        sa.Column('cannot_assess', sa.Integer(), nullable=True),
        sa.Column('slug', sa.Text(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['source_slug'], ['library_sources.source_slug']),
        sa.ForeignKeyConstraint(['entry_id', 'key'],
                                ['library_assertions.entry_id', 'library_assertions.key'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_lib_chains_assertion', 'library_chains', ['entry_id', 'key'])
    op.create_index('idx_lib_chains_source', 'library_chains', ['source_slug'])

    # derived_tier is STORED, and the loader asserts it recomputes: no derived_from is generated,
    # one key is that key's tier, several is the WEAKEST of them.
    op.create_table(
        'library_prose_pieces',
        sa.Column('entry_id', sa.Text(), nullable=False),
        sa.Column('slot', sa.Text(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('resolved_note', sa.Text(), nullable=True),
        sa.Column('cut_note', sa.Text(), nullable=True),
        sa.Column('derived_tier', sa.Text(), nullable=False),
        sa.CheckConstraint("derived_tier IN ('generated','curated','cited')"),
        sa.ForeignKeyConstraint(['entry_id'], ['library_entries.entry_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('entry_id', 'slot', 'position'),
    )

    op.create_table(
        'library_prose_derived_from',
        sa.Column('entry_id', sa.Text(), nullable=False),
        sa.Column('slot', sa.Text(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('key', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ['entry_id', 'slot', 'position'],
            ['library_prose_pieces.entry_id', 'library_prose_pieces.slot',
             'library_prose_pieces.position'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['entry_id', 'key'],
                                ['library_assertions.entry_id', 'library_assertions.key'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('entry_id', 'slot', 'position', 'key'),
    )

    op.create_table(
        'library_discussions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('entry_id', sa.Text(), nullable=False),
        sa.Column('key', sa.Text(), nullable=False),
        sa.Column('author', sa.Text(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['entry_id', 'key'],
                                ['library_assertions.entry_id', 'library_assertions.key'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_lib_discussions_assertion', 'library_discussions', ['entry_id', 'key'])

    op.create_table(
        'library_judgements',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('entry_id', sa.Text(), nullable=False),
        sa.Column('shape', sa.Text(), nullable=False),
        sa.Column('judgement_id', sa.Text(), nullable=True),
        sa.Column('kind', sa.Text(), nullable=True),
        sa.Column('made_by', sa.Text(), nullable=True),
        sa.Column('decided', sa.Text(), nullable=True),
        sa.Column('alternatives', sa.Text(), nullable=True),
        sa.Column('reasoning', sa.Text(), nullable=True),
        sa.Column('tier', sa.Text(), nullable=True),
        sa.Column('falsifier', sa.Text(), nullable=True),
        sa.Column('affects', sa.Text(), nullable=True),
        sa.Column('needs', sa.Text(), nullable=True),
        sa.Column('needs_reason', sa.Text(), nullable=True),
        sa.Column('judgement_key', sa.Text(), nullable=True),
        sa.Column('about', sa.Text(), nullable=True),
        sa.Column('author', sa.Text(), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.CheckConstraint("shape IN ('canonical','deferred')"),
        sa.CheckConstraint("shape = 'deferred' OR decided IS NOT NULL"),
        sa.CheckConstraint("shape = 'canonical' OR body IS NOT NULL"),
        sa.ForeignKeyConstraint(['entry_id'], ['library_entries.entry_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_lib_judgements_entry', 'library_judgements', ['entry_id'])

    op.create_table(
        'library_forms',
        sa.Column('entry_id', sa.Text(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('form', sa.Text(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['entry_id'], ['library_entries.entry_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('entry_id', 'position'),
    )

    op.create_table(
        'library_siblings',
        sa.Column('entry_id', sa.Text(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('sibling_id', sa.Text(), nullable=False),
        sa.Column('why_separate', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['entry_id'], ['library_entries.entry_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('entry_id', 'position'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('library_siblings')
    op.drop_table('library_forms')
    op.drop_index('idx_lib_judgements_entry', table_name='library_judgements')
    op.drop_table('library_judgements')
    op.drop_index('idx_lib_discussions_assertion', table_name='library_discussions')
    op.drop_table('library_discussions')
    op.drop_table('library_prose_derived_from')
    op.drop_table('library_prose_pieces')
    op.drop_index('idx_lib_chains_source', table_name='library_chains')
    op.drop_index('idx_lib_chains_assertion', table_name='library_chains')
    op.drop_table('library_chains')
    op.drop_table('library_sources')
    op.drop_index('idx_lib_assertions_tier', table_name='library_assertions')
    op.drop_index('idx_lib_assertions_kind', table_name='library_assertions')
    op.drop_table('library_assertions')
    op.drop_index('idx_lib_entries_link_state', table_name='library_entries')
    op.drop_index('idx_lib_entries_library_id', table_name='library_entries')
    op.drop_table('library_entries')
