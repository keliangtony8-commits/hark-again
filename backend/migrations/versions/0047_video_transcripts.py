"""读过的视频字幕（v2.03，app/video_transcript.py）：video_transcripts 表，analyze_video 存、search_transcript 查。

Revision ID: 0047
Revises: 0046
"""
from alembic import op
import sqlalchemy as sa

revision = '0047'
down_revision = '0046'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'video_transcripts',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('conversation_id', sa.String(32), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=True),
        sa.Column('platform', sa.String(16), nullable=False),
        sa.Column('video_id', sa.String(32), nullable=False),
        sa.Column('page', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('title', sa.String(200), nullable=False, server_default=''),
        sa.Column('author', sa.String(100), nullable=False, server_default=''),
        sa.Column('duration', sa.Float(), nullable=False, server_default='0'),
        sa.Column('language', sa.String(32), nullable=False, server_default=''),
        sa.Column('language_name', sa.String(64), nullable=False, server_default=''),
        sa.Column('generated', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('available', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('segments', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_video_transcripts_conversation_id', 'video_transcripts', ['conversation_id'])
    op.create_index('ix_video_transcripts_created_at', 'video_transcripts', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_video_transcripts_created_at', 'video_transcripts')
    op.drop_index('ix_video_transcripts_conversation_id', 'video_transcripts')
    op.drop_table('video_transcripts')
