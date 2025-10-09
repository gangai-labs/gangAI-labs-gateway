FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set working directory to project root
WORKDIR /app

# Copy requirements and install dependencies (at root)
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# Expose port
EXPOSE 8000

# Run the application: cd into src/ to match your local setup
CMD ["sh", "-c", "cd src && exec uvicorn app:app --host 0.0.0.0 --loop uvloop --port 8000 --workers 1 --log-level critical"] 
