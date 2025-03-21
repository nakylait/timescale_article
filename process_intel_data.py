import os
import pandas as pd
from sqlalchemy import create_engine
from datetime import datetime
import time

# Database connection settings from environment variables
DB_PARAMS = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'port': os.environ.get('DB_PORT', '5432'),
    'database': os.environ.get('DB_NAME', 'intel_lab'),
    'user': os.environ.get('DB_USER', 'timescale'),
    'password': os.environ.get('DB_PASSWORD', 'password123')
}

def wait_for_db():
    while True:
        try:
            engine = create_engine(
                f"postgresql://{DB_PARAMS['user']}:{DB_PARAMS['password']}@{DB_PARAMS['host']}:{DB_PARAMS['port']}/{DB_PARAMS['database']}"
            )
            engine.connect()
            print("Database connection successful!")
            return engine
        except Exception as e:
            print("Waiting for database...", e)
            time.sleep(5)

def process_intel_data(filename):
    data = []
    with open(filename, 'r') as f:
        for line in f:
            if line.startswith('date'):
                continue
            
            parts = line.strip().split()
            try:
                date = parts[0]
                time_str = parts[1]
                moteid = int(parts[3])
                temperature = float(parts[4])
                humidity = float(parts[5])
                light = float(parts[6])
                voltage = float(parts[7])
                
                timestamp = datetime.strptime(f"{date} {time_str}", "%Y-%m-%d %H:%M:%S.%f")
                
                # Skip physically impossible temperature values (outside -40°C to 100°C range)
                # These are likely sensor errors or data corruption
                if temperature < -40 or temperature > 100:
                    continue
                    
                # Skip invalid humidity readings (humidity must be between 0-100%)
                # Values outside this range indicate sensor malfunction
                if humidity < 0 or humidity > 100:
                    continue
                
                data.append({
                    'time': timestamp,
                    'sensor_id': moteid,
                    'temperature': temperature,
                    'humidity': humidity,
                    'light': light,
                    'voltage': voltage
                })
                
            except (ValueError, IndexError):
                continue
            
            if len(data) >= 100000:
                yield pd.DataFrame(data)
                data = []
    
    if data:
        yield pd.DataFrame(data)

def main():
    print("Waiting for database to be ready...")
    engine = wait_for_db()
    
    data_file = '/data/data.txt'
    
    # Wait for data file to be available
    while not os.path.exists(data_file):
        print(f"Waiting for data file at {data_file}")
        time.sleep(5)

    print("Starting data import...")
    for i, chunk in enumerate(process_intel_data(data_file)):
        print(f"Processing chunk {i+1}")
        # Insert into TimescaleDB table
        chunk.to_sql('sensor_data_timescale', engine, if_exists='append', index=False, method='multi')
        # Insert into regular PostgreSQL table
        chunk.to_sql('sensor_data_postgres', engine, if_exists='append', index=False, method='multi')
        print(f"Loaded {len(chunk)} rows into both tables")

if __name__ == "__main__":
    main()
