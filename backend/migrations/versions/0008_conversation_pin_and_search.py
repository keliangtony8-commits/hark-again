"""conversation pin + message search text

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pinned', sa.Boolean(), server_default=sa.false(), nullable=False))
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('search_text', sa.Text(), server_default='', nullable=False))

    # 回填已有消息的搜索文本
    from app.blocks import blocks_to_text
    bind = op.get_bind()
    messages = sa.table('messages', sa.column('id', sa.String), sa.column('blocks', sa.JSON),
                        sa.column('search_text', sa.Text))
    for mid, blocks in bind.execute(sa.select(messages.c.id, messages.c.blocks)).all():
        bind.execute(messages.update().where(messages.c.id == mid)
                     .values(search_text=blocks_to_text(blocks or [])))


def downgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('search_text')
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_column('pinned')
