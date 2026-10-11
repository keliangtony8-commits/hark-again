"""report card gist (报告卡的“一眼”：home_cards.headline / gist，老报告按 app/report_gist.py 回填)

Revision ID: 0025
Revises: 0024
"""
from alembic import op
import sqlalchemy as sa

from app.report_gist import gist

revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('home_cards') as b:
        b.add_column(sa.Column('headline', sa.String(120), nullable=True))
        b.add_column(sa.Column('gist', sa.String(240), nullable=True))
    cards = sa.table('home_cards', sa.column('id', sa.String), sa.column('kind', sa.String),
                     sa.column('blocks', sa.JSON), sa.column('headline', sa.String), sa.column('gist', sa.String),
                     sa.column('dismissed', sa.Boolean))
    conn = op.get_bind()
    rows = conn.execute(sa.select(cards.c.id, cards.c.blocks)
                        .where(cards.c.kind == 'report', cards.c.dismissed.is_(False))).all()
    for cid, blocks in rows:
        headline, line = gist(blocks or [])
        if headline or line:
            conn.execute(cards.update().where(cards.c.id == cid).values(headline=headline, gist=line))


def downgrade() -> None:
    with op.batch_alter_table('home_cards') as b:
        b.drop_column('gist')
        b.drop_column('headline')
