"""drop books.genre: tags do its job

Genre was one shared free-text field per book, and was never filled in
(empty on every book in October 2026); readers' own tags (Biography, Crime,
Noir) are what's used for it. Dropping it leaves one way to say what a book is.

Revision ID: a9c3e5f7b2d4
Revises: f2b7c9d1e4a5
Create Date: 2026-10-25

"""
import sqlalchemy as sa
from alembic import op

revision = "a9c3e5f7b2d4"
down_revision = "f2b7c9d1e4a5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("books") as batch:
        batch.drop_column("genre")


def downgrade():
    with op.batch_alter_table("books") as batch:
        batch.add_column(sa.Column("genre", sa.String(length=100)))
