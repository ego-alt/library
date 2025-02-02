# EPUB Library Management System

## Overview

This project is an EPUB Library Management System built using Flask, SQLAlchemy, and BeautifulSoup. It allows users to upload, manage, and read EPUB books, extract metadata, and add custom tags. The application provides a web interface for users to interact with their library of books.

![alt text](images/library_home_page.png)

![alt text](images/library_reader.png)

## Features

- **Book Management**: Users can upload EPUB files, which are processed to extract metadata and cover images.
- **Bookmarking**: The application automatically saves the reading position in each book for user convenience.
- **Search and Filter**: Users can search for books by title, author, genre, and tags.
- **Responsive Design**: The web interface is designed to be user-friendly and responsive.

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
   docker run -d -p 8002:8002 -v <local_path_to_books>:/mnt/backup/books epub-library
   ```

## Usage

- **Access the application**: Open your web browser and go to `http://127.0.0.1:8002`.
- **User Registration**: Create a new user account to start managing your books.
- **Upload Books**: Use the provided interface to upload EPUB files.
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
