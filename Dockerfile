# syntax=docker/dockerfile:1
# Use an official Python runtime as the base image
FROM python:3.10-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file to the container
COPY requirements.txt /app/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project files
COPY . /app/

# Expose the port the app will run on
EXPOSE 8002

# Command to run Flask server by default (can be overridden by Docker Compose)
CMD [ "python3", "-m" , "flask", "run", "--host=0.0.0.0", "--port=8002"]
