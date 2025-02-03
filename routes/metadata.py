from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user
from models import Book, db, Tag, book_tags, ProgressChoice
from tag_manager import TagManager
from utils import get_epub_cover
import os


metadata_blueprint = Blueprint('metadata_routes', __name__)

@metadata_blueprint.route('/book_metadata/<filename>', methods=['GET', 'POST'])
def book_metadata(filename):
    """Get or update book metadata."""
    book = Book.query.filter_by(filename=filename).first()
    if not book:
        return jsonify({'error': 'Book not found'}), 404
    
    if request.method == 'POST':
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required'}), 401

        data = request.get_json()
        book.title = data.get('title', book.title)
        book.author = data.get('author', book.author)
        book.genre = data.get('genre', book.genre)
        try:
            # First, remove all existing tags for this user and book
            db.session.execute(
                book_tags.delete().where(
                    db.and_(
                        book_tags.c.book_id == book.id,
                        book_tags.c.user_id == current_user.id
                    )
                )
            )
            # Create/get tags and commit them
            tag_manager = TagManager(db.session, current_user.id)
            progress_tag = None
            tags_to_add = []
            for tag_name in data.get('tags', []):
                # TODO: Generalise this
                if tag_name in [ProgressChoice.IN_PROGRESS, ProgressChoice.FINISHED]:
                    progress_tag = tag_name
                    continue

                tag = Tag.query.filter_by(
                    name=tag_name,
                    user_id=current_user.id
                ).first()
                
                if not tag:
                    tag = Tag(name=tag_name, user_id=current_user.id)
                    db.session.add(tag)
                    db.session.flush()  # This assigns the ID without committing
                
                tags_to_add.append(tag)
            
            for tag in tags_to_add:
                db.session.execute(
                    book_tags.insert().values(
                        book_id=book.id,
                        tag_id=tag.id,
                        user_id=current_user.id
                    )
                )
            tag_manager.update_from_virtual_tag(book.id, "status", progress_tag)
            db.session.commit()
            return jsonify({'message': 'Metadata updated successfully'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500
    
    # GET request handling
    response = {
        'title': book.title,
        'author': book.author,
        'genre': book.genre,
        'created_at': book.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'tags': [],
        'filename': book.filename,
        'cover': get_epub_cover(
            os.path.join(current_app.config['BOOK_DIR'], book.filename),
            book.cover_path
        )
    }
    
    # Only include tags if user is authenticated
    if current_user.is_authenticated:
        # Get tags specific to this user and book
        tag_manager = TagManager(db.session, current_user.id)
        response['tags'] = tag_manager.get_all_tags(book.id)
    
    return jsonify(response)
