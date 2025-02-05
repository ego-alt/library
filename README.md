# EPUB Library Management System

## Overview

This project is an EPUB Library Management System built using Flask, SQLAlchemy, and BeautifulSoup. It allows users to upload, manage, and read EPUB books, extract metadata, and add custom tags. The application provides a web interface for users to interact with their library of books.

![alt text](images/home_page.png)

![alt text](images/metadata_dark.png)

![alt text](images/epub_reader.png)

![alt text](images/epub_reader_dark.png)

## Features

- **Book Management**
  - Upload and process EPUBs, with automatic parsing of metadata.
  - Customize book covers by uploading a new jpg or png.
  - Download books directly from the library.
- **EPUB Reader**
  - Built-in reader with chapter-based navigation.
  - Toggle dark mode, adjust font size, and leverage a dynamic table of contents.
  - Mobile-friendly layout with intuitive controls.
- **Filtering & Search**
  - Filter books by title, author, genre, or tags.
  - Track reading progress with automatic tags for Unread, In Progress, and Finished books.
- **Dark Mode**
  - Toggle between light and dark themes effortlessly.

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/ego-alt/library.git
   cd library
   ```

2. **Build the Docker image**:
   ```bash
   docker build -t epub-library .
   ```

3. **Run the Docker container**:
   ```bash
   docker run -d -p 8002:8002 \
       -v <local_path_to_books>:/mnt/backup/books \
       -v <local_path_to_instance>:/app/instance \
       epub-library
   ```

4. **Alternative (local) setup**

   Ensure you have Python (3.6+) installed and set up a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate   # On Windows use `venv\Scripts\activate`
   pip install -r requirements.txt
   flask run --port=8002
   ```

## Usage

- **Access the application**: Open your web browser and go to `http://127.0.0.1:8002`.
- **User Registration**: Create a new user account to start managing your books.
- **Upload Books**: Click the upload icon to add an EPUB file to the library.
- **Filtering**: Use the sidebar filters to narrow down your book collection by title, author, genre, or tags.
- **Read Books**: Click on a book to read it in the built-in reader.
- **Bookmarking**: Save your reading position for easy access later.

## Commands

The application includes several CLI commands for managing books:

- **Import Books**: Import EPUB files from a specified directory.
  ```bash
  flask import-books --directory /path/to/epub/files
  ```

- **Flush Books**: Remove books from the database that no longer exist in the specified directory.
  ```bash
  flask flush-books --directory /path/to/epub/files
  ```

- **Create User**: Create a new user account.
  ```bash
  flask create-user <username> <password>
  ```
