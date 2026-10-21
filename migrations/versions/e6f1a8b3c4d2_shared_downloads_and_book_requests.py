"""one download queue for books and comics, and book requests

comic_downloads becomes downloads (every existing row a comic), with a link to
the new book_requests table.

Revision ID: e6f1a8b3c4d2
Revises: d5e9f3a7b2c1
Create Date: 2026-10-21

"""
import sqlalchemy as sa
from alembic import op

revision = "e6f1a8b3c4d2"
down_revision = "d5e9f3a7b2c1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "book_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ol_key", sa.String(40), unique=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("author", sa.String(200)),
        sa.Column("year", sa.Integer()),
        sa.Column("cover_url", sa.String(500)),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="SET NULL")),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_book_requests_status", "book_requests", ["status"])

    op.drop_index("ix_comic_downloads_status", "comic_downloads")
    op.drop_index("ix_comic_downloads_issue_id", "comic_downloads")
    op.rename_table("comic_downloads", "downloads")
    with op.batch_alter_table("downloads") as batch:
        batch.add_column(sa.Column("kind", sa.String(10), nullable=False, server_default="comic"))
        batch.add_column(sa.Column("book_request_id", sa.Integer()))
        batch.create_foreign_key("fk_downloads_book_request_id", "book_requests", ["book_request_id"], ["id"], ondelete="SET NULL")
    with op.batch_alter_table("downloads") as batch:
        batch.alter_column("kind", server_default=None)
    op.create_index("ix_downloads_issue_id", "downloads", ["issue_id"])
    op.create_index("ix_downloads_book_request_id", "downloads", ["book_request_id"])
    op.create_index("ix_downloads_status", "downloads", ["status"])


def downgrade():
    op.drop_index("ix_downloads_status", "downloads")
    op.drop_index("ix_downloads_book_request_id", "downloads")
    op.drop_index("ix_downloads_issue_id", "downloads")
    op.execute("DELETE FROM downloads WHERE kind = 'book'")
    with op.batch_alter_table("downloads") as batch:
        batch.drop_constraint("fk_downloads_book_request_id", type_="foreignkey")
        batch.drop_column("book_request_id")
        batch.drop_column("kind")
    op.rename_table("downloads", "comic_downloads")
    op.create_index("ix_comic_downloads_issue_id", "comic_downloads", ["issue_id"])
    op.create_index("ix_comic_downloads_status", "comic_downloads", ["status"])
    op.drop_index("ix_book_requests_status", "book_requests")
    op.drop_table("book_requests")
