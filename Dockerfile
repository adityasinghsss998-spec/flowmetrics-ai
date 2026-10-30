# Use official lightweight Python 3.13 Linux image as the base environment
FROM python:3.13-slim

# Set the working directory inside the container where all code and files will live
WORKDIR /app

# Copy the requirements file into the container first (leveraging Docker layer caching so dependencies aren't reinstalled on code edits)
COPY requirements.txt .

# Install Python dependencies without caching the installation wheels to keep image size small
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the application source code directory into the container
COPY src/ ./src/

# Document that the container listens on port 3006 at runtime
EXPOSE 3006

# Start the FastAPI application with Uvicorn on 0.0.0.0 and port $PORT (default 3006).
# Running with exactly ONE worker ensures the background hourly scan and RabbitMQ listener run once, not duplicated.
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-3006}"]

