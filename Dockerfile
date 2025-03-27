FROM python:3.9-slim

WORKDIR /app

# Install git and clean up in one layer to keep the image small
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create a directory for git operations
RUN mkdir -p /tmp/git_operations

# Set environment variables with defaults
ENV COMPILES_DIR=/data/compiles \
    TEMP_DIR_BASE=/tmp/git_operations \
    GITIGNORE_TEMPLATE=/app/gitignore.template

CMD ["python", "main.py"]
