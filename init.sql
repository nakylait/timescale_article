-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Create the regular PostgreSQL table
CREATE TABLE sensor_data_postgres (
    time        TIMESTAMPTZ NOT NULL,
    epoch       INTEGER,
    sensor_id   INTEGER NOT NULL,
    temperature DOUBLE PRECISION,
    humidity    DOUBLE PRECISION,
    light       DOUBLE PRECISION,
    voltage     DOUBLE PRECISION
);

-- Create regular PostgreSQL indexes
CREATE INDEX idx_sensor_data_postgres_time ON sensor_data_postgres(time);
CREATE INDEX idx_sensor_data_postgres_sensor_id ON sensor_data_postgres(sensor_id);
CREATE INDEX idx_sensor_data_postgres_epoch ON sensor_data_postgres(epoch);

-- Create the TimescaleDB table
CREATE TABLE sensor_data_timescale (
    time        TIMESTAMPTZ NOT NULL,
    epoch       INTEGER,
    sensor_id   INTEGER NOT NULL,
    temperature DOUBLE PRECISION,
    humidity    DOUBLE PRECISION,
    light       DOUBLE PRECISION,
    voltage     DOUBLE PRECISION
);

-- Convert to hypertable
SELECT create_hypertable('sensor_data_timescale', 'time');

-- Create TimescaleDB indexes (though TimescaleDB automatically creates some indexes)
CREATE INDEX idx_sensor_data_timescale_sensor_id ON sensor_data_timescale(sensor_id);
CREATE INDEX idx_sensor_data_timescale_epoch ON sensor_data_timescale(epoch);