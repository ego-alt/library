"""when each wanted issue and book request was last looked for

Lets the search take the longest-waiting items first, and Downloads say
"Looked 2 h ago".

Revision ID: f2b7c9d1e4a5
Revises: e6f1a8b3c4d2
Create Date: 2026-10-22

"""
import sqlalchemy as sa
from alembic import op

revision = "f2b7c9d1e4a5"
down_revision = "e6f1a8b3c4d2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("comic_issues") as batch:
        batch.add_column(sa.Column("searched_at", sa.DateTime()))
    with op.batch_alter_table("book_requests") as batch:
        batch.add_column(sa.Column("searched_at", sa.DateTime()))


def downgrade():
    with op.batch_alter_table("book_requests") as batch:
        batch.drop_column("searched_at")
    with op.batch_alter_table("comic_issues") as batch:
        batch.drop_column("searched_at")
