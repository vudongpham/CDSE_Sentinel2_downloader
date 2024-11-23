# Use a lightweight Python image
FROM python:3.11-slim

# Install Python dependencies
RUN pip install --no-cache-dir 'geopandas[all]'

# Set the working directory
WORKDIR /app

# Copy the Python script into the container
COPY search.py .
COPY download.py .

# Copy the entrypoint script into the container
COPY entrypoint.sh .

# Make the entrypoint script executable
RUN chmod +x entrypoint.sh

# Set the entrypoint to the shell script
ENTRYPOINT ["./entrypoint.sh"]

# Default arguments (if any) to pass to the script
CMD []