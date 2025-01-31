from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# Junction table for book tags
book_tags = db.Table('book_tags',
    db.Column('book_id', db.Integer, db.ForeignKey('books.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(20), nullable=False, default='standard')  # 'admin', 'standard'
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Add these methods
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # Relationships
    bookmarks = db.relationship('Bookmark', back_populates='user', cascade='all, delete-orphan')
    uploaded_books = db.relationship('Book', back_populates='uploaded_by_user')
    tags = db.relationship('Tag', back_populates='user', cascade='all, delete-orphan')


class Book(db.Model):
    __tablename__ = 'books'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(255), unique=True, nullable=False)
    cover_path = db.Column(db.String(255))  # Path to stored cover image
    genre = db.Column(db.String(100))
    access_level = db.Column(db.String(20), nullable=False, default='standard')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # Relationships
    tags = db.relationship('Tag', secondary=book_tags, backref=db.backref('books', lazy='dynamic'))
    bookmarks = db.relationship('Bookmark', back_populates='book', cascade='all, delete-orphan')
    uploaded_by_user = db.relationship('User', back_populates='uploaded_books')


class Tag(db.Model):
    __tablename__ = 'tags'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Add user relationship
    user = db.relationship('User', back_populates='tags')
    
    # Make name unique per user
    __table_args__ = (
        db.UniqueConstraint('name', 'user_id', name='unique_tag_per_user'),
    )


class Bookmark(db.Model):
    __tablename__ = 'bookmarks'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    chapter_index = db.Column(db.Integer, default=0)
    position = db.Column(db.Float, default=0)  # Percentage through chapter
    last_read = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', back_populates='bookmarks')
    book = db.relationship('Book', back_populates='bookmarks')
    
    # Ensure each user can only have one bookmark per book
    __table_args__ = (
        db.UniqueConstraint('user_id', 'book_id', name='unique_user_book_bookmark'),
    ) 