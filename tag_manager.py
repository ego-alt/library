from dataclasses import dataclass
from flask import jsonify
from models import Bookmark, Tag, BookProgressChoice, book_tags, db
import logging


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEFAULT_ATTRIBUTES = {
    "status": BookProgressChoice.UNREAD.value
}

@dataclass
class VirtualTag:
    id: int
    name: str
    user_id: int


class TagManager:
    def __init__(self, db_session, user_id):
        self.db_session = db_session
        self.user_id = user_id

    def create_virtual_tags(self, book_id: int) -> list[VirtualTag]:
        """Creates virtual tags for the given book and user."""
        bookmark = self.db_session.query(Bookmark).filter_by(book_id=book_id, user_id=self.user_id).first()
        if not bookmark:
            return []

        return [
            VirtualTag(
                id=bookmark.id,
                name=getattr(bookmark, attribute),
                user_id=self.user_id,
            )
            for attribute, default_value in DEFAULT_ATTRIBUTES.items()
            if getattr(bookmark, attribute) != default_value
        ]

    def get_user_tags(self, book_id: int) -> list[Tag]:
        """Gets all user tags for the given book."""
        return self.db_session.query(Tag.name).join(
            book_tags,
            db.and_(
                book_tags.c.tag_id == Tag.id,
                book_tags.c.book_id == book_id,
                book_tags.c.user_id == self.user_id
            )
        ).all()

    def get_all_tags(self, book_id: int) -> list[str]:
        """Gets all tags for the given book and user."""
        virtual_tags = self.create_virtual_tags(book_id)
        user_tags = self.get_user_tags(book_id)
        
        virtual_tags = [tag.name for tag in virtual_tags]
        user_tags = [tag.name for tag in user_tags]
        return virtual_tags + user_tags

    def update_from_virtual_tag(self, book_id: int, field: str, value: str | None):
        """Updates the attribute of the bookmark."""
        bookmark = self.db_session.query(Bookmark).filter_by(book_id=book_id, user_id=self.user_id).first()
        if bookmark is None and value is None:
            return False

        if value is None:
            value = DEFAULT_ATTRIBUTES[field]

        if bookmark is None:
            bookmark = Bookmark(user_id=self.user_id, book_id=book_id, **{field: value})
            logging.info(f"Updating bookmark {bookmark} with field {field} and value {value}")
            self.db_session.add(bookmark)
        else:
            setattr(bookmark, field, value)

        return True        
