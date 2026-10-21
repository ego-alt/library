"""settings for the whole app, not just comics: rename comic_settings

Revision ID: d5e9f3a7b2c1
Revises: c4d8e1f2a9b6
Create Date: 2026-10-21

"""
from alembic import op

revision = "d5e9f3a7b2c1"
down_revision = "c4d8e1f2a9b6"
branch_labels = None
depends_on = None


def upgrade():
    op.rename_table("comic_settings", "settings")


def downgrade():
    op.rename_table("settings", "comic_settings")
