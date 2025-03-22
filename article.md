# Time-Series Data Management with TimescaleDB

## Introduction

Hi everyone! Today I want to talk about time-series data management. I encountered this challenge while working on one of our projects and wanted to share my experience and highlight features that can be particularly useful and advantageous compared to traditional databases.

## Understanding Time-Series Data: Characteristics and Challenges

Let's start with the basics and break down what time-series data actually is. Time-series data is a sequence of data points indexed in time order and has properties that differentiate it from other types of data: append-only data (new data is continuously added and not altered), naturally ordered (chronological sequence), time-centric (primary attribute for analysis).

Common examples of time-series data include: stock prices over time, weather measurements (temperature, humidity, wind speed), monthly subscriber counts on a website, sensor readings from IoT devices, etc.

### Common Challenges

When working with time-series data, there are several important challenges to consider:

- **Data Volume and Scaling**: High-frequency data collection leads to rapid growth, making traditional databases struggle with performance
- **Complex Aggregations**: Queries like averages, sums, or analyzing patterns over time need to be performed efficiently.

These characteristics and challenges require specialized approaches for optimal storage and querying. Traditional relational databases can become overwhelmed when dealing with large volumes of time-series data, especially when performing complex time-based aggregations.

### Time-Series Databases

Several specialized database systems exist to address these challenges: InfluxDB, Prometheus, Apache Druid, MongoDB, Amazon Timestream. Each has its strengths and fits different use cases. However, in this article, we'll focus on TimescaleDB.

## TimescaleDB

TimescaleDB is a time-series database built as an extension to PostgreSQL with time-series optimizations. Unlike other solutions that require learning new query languages, TimescaleDB lets you continue using familiar SQL.

### Key Features:

- **Postgres-Based**: Full SQL compatible and supports relational capabilities
- **Hypertables**: Automatically partitions the time-series data into chunks for optimal performance
- **Hypercore**: Smart storage engine that writes new data quickly and automatically reorganizes older data for faster analysis and better storage efficiency
- **Data Lifecycle Management**: Automatic data handling like continuous aggregation, data retention (deleting old data)

## Practical Example: Intel Lab Sensor Data

For practical example we are using sensor data from the [Intel Berkeley Research Lab] (https://db.csail.mit.edu/labdata/labdata.html). This dataset contains millions of temperature, humidity, light, and voltage readings from 54 sensors deployed throughout the lab between February 28th and April 5th, 2004. We chose this dataset because its relatively small size (about 2.3 million readings) but fits for demonstration of the performance differences between PostgreSQL and TimescaleDB

### Setting Up Our Environment

First, we created two tables to compare performance:
1. A regular PostgreSQL table (`sensor_data_postgres`)
2. A TimescaleDB hypertable (`sensor_data_timescale`)

Both tables have identical schemas and indexes:

```sql
-- Regular PostgreSQL table
CREATE TABLE sensor_data_postgres (
    time        TIMESTAMPTZ NOT NULL,
    epoch       INTEGER,
    sensor_id   INTEGER NOT NULL,
    temperature DOUBLE PRECISION,
    humidity    DOUBLE PRECISION,
    light       DOUBLE PRECISION,
    voltage     DOUBLE PRECISION
);

-- TimescaleDB table
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
```

### Performance Comparison

All performance tests were run on:
- MacBook Air (M1, 2020)
- Apple M1 chip
- 16 GB RAM
- PostgreSQL 14.17 (64-bit)
- TimescaleDB 2.19.0

Note: Performance results may vary on different hardware configurations, but the overall performance patterns should remain consistent across systems.

We loaded 1,841,828 rows and ran identical queries on both tables. Let's look at each query type and its results:

1. **Full Range Select**: Basic retrieval of all data within a time range

```sql
SELECT * FROM sensor_data_postgres 
WHERE time >= '2004-02-28 00:58:46' 
AND time <= '2004-04-05 11:02:32';

-- Same query for TimescaleDB table
```

**Results:**
- PostgreSQL: 226.5 ms
- TimescaleDB: 317.7 ms
- Performance: PostgreSQL is 40% faster

**Insights:**
- For basic SELECT queries, PostgreSQL performs better
- TimescaleDB's overhead for chunk management affects simple query performance
- This type of query is less common in time-series applications

2. **Time-Based Aggregations**: Grouping and analyzing data by time intervals

```sql
-- PostgreSQL (Daily aggregation)
SELECT 
    date_trunc('day', time) as day,
    sensor_id,
    COUNT(*) as readings,
    AVG(temperature) as avg_temp,
    stddev(temperature) as temp_stddev
FROM sensor_data_postgres
WHERE time >= '2004-02-28' AND time <= '2004-04-05'
GROUP BY day, sensor_id
HAVING stddev(temperature) > 2
ORDER BY day, sensor_id;

-- TimescaleDB (using time_bucket)
SELECT 
    time_bucket('1 day', time) as day,
    sensor_id,
    COUNT(*) as readings,
    AVG(temperature) as avg_temp,
    stddev(temperature) as temp_stddev
FROM sensor_data_timescale
WHERE time >= '2004-02-28' AND time <= '2004-04-05'
GROUP BY day, sensor_id
HAVING stddev(temperature) > 2
ORDER BY day, sensor_id;
```

**Results:**
- PostgreSQL: 443.2 ms
- TimescaleDB: 170.9 ms
- Performance: TimescaleDB is 61% faster

**Insights:**
- TimescaleDB significantly outperforms PostgreSQL for aggregation queries
- The `time_bucket` function is more efficient than `date_trunc`
- TimescaleDB's memory efficiency becomes more important with complex aggregations

### Advanced TimescaleDB Features: Continuous Aggregates

One of TimescaleDB's most powerful features is continuous aggregates. It pre-computes and automatically maintains aggregated views of the time-series data by improving query performance for common analytical operations.

Let's compare a regular PostgreSQL view with a TimescaleDB continuous aggregate:

1. **PostgreSQL View vs TimescaleDB Continuous Aggregate**

```sql
-- Regular PostgreSQL view (computed on every query)
CREATE VIEW pg_daily_sensor_stats AS
SELECT
    date_trunc('day', time) as day,
    sensor_id,
    AVG(temperature) as avg_temp,
    MIN(temperature) as min_temp,
    MAX(temperature) as max_temp,
    COUNT(*) as reading_count
FROM sensor_data_postgres
GROUP BY day, sensor_id;

-- TimescaleDB continuous aggregate (materialized and automatically refreshed)
CREATE MATERIALIZED VIEW ts_daily_sensor_stats
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) as day,
    sensor_id,
    AVG(temperature) as avg_temp,
    MIN(temperature) as min_temp,
    MAX(temperature) as max_temp,
    COUNT(*) as reading_count
FROM sensor_data_timescale
GROUP BY day, sensor_id;

-- Set up automatic refresh policy
SELECT add_continuous_aggregate_policy('ts_daily_sensor_stats',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');
```

2. **Querying the Aggregates**

```sql
-- Query against PostgreSQL view (computed on demand)
SELECT * FROM pg_daily_sensor_stats
WHERE day >= '2004-03-01' AND day <= '2004-03-31'
ORDER BY day, sensor_id;

-- Query against TimescaleDB continuous aggregate (pre-computed)
SELECT * FROM ts_daily_sensor_stats
WHERE day >= '2004-03-01' AND day <= '2004-03-31'
ORDER BY day, sensor_id;
```

**Results when querying a month of data:**
- PostgreSQL view: 424.0 ms (computed on every query)
- TimescaleDB continuous aggregate: 0.433 ms (pre-computed)
- Performance: TimescaleDB is 979x faster

### Storage Optimization:
TimescaleDB can automatically compress the data and save a lot of memory.
It's new [Hypercore](https://docs.timescale.com/use-timescale/latest/hypercore/) automatically optimizes data storage - new data goes to fast-access storage, then moves to compressed storage (>90% reduction) as it ages, it is available after v2.18.0 API. But for demonstration, we will use old chunking methods.

Both PostgreSQL and TimescaleDB tables start at similar sizes (around 209 MB) with our test dataset:

```sql
-- Check regular PostgreSQL table size
SELECT pg_total_relation_size('sensor_data_postgres')/1024/1024 as size_mb;
-- PostgreSQL size: 209 MB

-- Check hypertable size before compression
SELECT hypertable_size('sensor_data_timescale')/1024/1024 as size_mb;
-- TimescaleDB size before compression: 208 MB

-- Enable compression on table
ALTER TABLE sensor_data_timescale SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'sensor_id',
    timescaledb.compress_orderby = 'time'
);

-- Create compression policy (compress chunks older than 7 days)
SELECT add_compression_policy('sensor_data_timescale', INTERVAL '7 days');

-- Check hypertable size after compression
SELECT hypertable_size('sensor_data_timescale')/1024/1024 as size_mb;
-- TimescaleDB size after compression: 35 MB (83% reduction)
```

**Insights:**
- Native compression provides significant storage savings (83% reduction)
- Compression maintains query functionality while dramatically reducing storage costs
- Choose compression settings strategically:
  - `compress_orderby='time'`: Best for time-series data as values typically follow changes over time
  - `compress_segmentby='sensor_id'`: Group data by columns you frequently filter or aggregate on
  - For example, if you often query `SELECT avg(temperature) FROM sensors WHERE sensor_id = 5`, using sensor_id as segmentby will improve query performance
- Compression works best when chunks have enough data (default batch size is 1000 rows)
- Automatic compression policies keep storage optimization hands-free

[Learn more about compression settings](https://docs.timescale.com/use-timescale/latest/compression/about-compression/)


## Final Thoughts
Our performance tests demonstrated TimescaleDB's significant advantages for time-series data management. While traditional PostgreSQL performed better for simple queries, TimescaleDB is a good choice in complex time-based operations with performance improvement for aggregation queries.

In my experience, we successfully used TimescaleDB for tracking webpage analytics, collecting views and clicks data. Using continuous aggregation, we were able to efficiently analyze and display page statistics across a 2-3 year range. This reduced the memory consumption by 30-40%, leading to substantial cost reductions in cloud infrastructure spending. When dealing with large-scale time-series data, these savings can significantly impact your operational budget.

---


https://maddevs.io/writeups/tax-fee-erc-20-token-design/


