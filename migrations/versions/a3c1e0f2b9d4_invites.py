"""invites

Revision ID: a3c1e0f2b9d4
Revises: 7db19999eb26
Create Date: 2026-09-25

"""
import sqlalchemy as sa
from alembic import op

revision = 'a3c1e0f2b9d4'
down_revision = '7db19999eb26'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'invites',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=254), nullable=False),
        sa.Column('display_name', sa.String(length=120), nullable=False),
        sa.Column('ui_lang', sa.String(length=2), nullable=False),
        sa.Column('space_id', sa.Integer(), nullable=True),
        sa.Column('grants_webmaster', sa.Boolean(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('invited_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['space_id'], ['maker_spaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invited_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    with op.batch_alter_table('invites') as batch:
        batch.create_index('ix_invites_email', ['email'], unique=False)


def downgrade():
    with op.batch_alter_table('invites') as batch:
        batch.drop_index('ix_invites_email')
    op.drop_table('invites')
