FROM python:3.9-slim

WORKDIR /app

# Install required packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the data processing script
COPY process_intel_data.py .

# Create a directory for the data
RUN mkdir /data

CMD ["python", "process_intel_data.py"]