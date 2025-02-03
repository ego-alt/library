from flask import Blueprint, current_app, jsonify, request, render_template
from flask_login import current_user
from models import Book, db, Bookmark, ProgressChoice, Tag
import os
from utils import get_epub_cover


index_blueprint = Blueprint('index_routes', __name__)

def get_covers(offset=0, limit=10, filters=None):
    query = Book.query
    conditions = []

    if filters:
        # Apply text filters for title, author, and genre
        for attr, column in (("title", Book.title), ("author", Book.author), ("genre", Book.genre)):
            if value := filters.get(attr):
                for word in value.split():
                    query = query.filter(column.ilike(f'%{word}%'))

        # Apply tag filters if provided
        if (tags := filters.get('tags')):
            if not current_user.is_authenticated:
                return conditions

            user_id = current_user.id
            tag_words = [tag.strip() for tag in tags.split(',') if tag.strip()]
            unread_tag = ProgressChoice.UNREAD.value in tag_words
            progress_tags = [tag for tag in tag_words if tag in (ProgressChoice.IN_PROGRESS, ProgressChoice.FINISHED)]
            other_tags = [tag for tag in tag_words if tag in progress_tags]

            if unread_tag:
                conditions.append(
                    db.or_(
                        Bookmark.id.is_(None),
                        db.and_(Bookmark.status == ProgressChoice.UNREAD, Bookmark.user_id == user_id)
                    )
                )
            if progress_tags:
                conditions.append(
                    db.and_(Bookmark.status.in_(progress_tags), Bookmark.user_id == user_id)
                )
            if other_tags:
                conditions.append(
                    db.and_(Tag.name.in_(other_tags), Tag.user_id == user_id)
                )

    if  current_user.is_authenticated:
        query = query.outerjoin(Book.bookmarks).outerjoin(Book.tags)
        if conditions:
            query = query.filter(db.or_(*conditions))
        query = query.order_by(Bookmark.last_read.desc(), Book.created_at.desc())
    else:
        query = query.order_by(Book.created_at.desc())

    return [
        {
            "filename": book.filename,
            "cover": get_epub_cover(
                os.path.join(current_app.config['BOOK_DIR'], book.filename),
                book.cover_path
            )
        }
        for book in query.offset(offset).limit(limit).all()
    ]


@index_blueprint.route('/')
def index():
    """Render the initial page with the first batch of book covers."""
    images = get_covers(0, 10)
    return render_template('index.html', images=images)


@index_blueprint.route('/load_more/<int:offset>', methods=['GET'])
def load_more(offset):
    filters = {
        'title': request.args.get('title'),
        'author': request.args.get('author'),
        'genre': request.args.get('genre'),
        'tags': request.args.get('tags')
    }
    # Remove empty filters
    filters = {k: v for k, v in filters.items() if v}
    images = get_covers(offset, 10, filters)
    return jsonify(images)


@index_blueprint.route('/download/<filename>')
def download(filename):
    """Serve the EPUB file for download."""
    return send_from_directory(current_app.config['BOOK_DIR'], filename, as_attachment=True)
