# syntax=docker/dockerfile:1
FROM python:3.10-slim

# Set the working directory inside the container
WORKDIR /app

# Copy just the requirements file to leverage Docker cache
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project files
COPY . /app/

# Set production environment variables
ENV FLASK_ENV=production
ENV FLASK_APP=app.py

# Expose the port that the app will run on
EXPOSE 8002

# Run the Flask application using Gunicorn with the correct module reference.
# This tells Gunicorn to call the create_app() factory in app.py.
CMD ["gunicorn", "app:create_app()", "--bind", "0.0.0.0:8002", "--workers", "3", "--timeout", "120", "--worker-class", "sync"]
