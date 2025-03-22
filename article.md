# Time-Series Data Management with TimescaleDB

## Introduction

Hi everyone! Today I want to talk about time-series data management. We encountered this challenge while working on one of our projects and below I will share our experience with TimescaleBD and highlight it's outstanding features.

## Understanding Time-Series Data: Characteristics and Challenges

Time-series data is simply a sequence of data points collected over time - think of it as measurements or events that have timestamps attached to them. It's append-only (we're mostly adding new data, not changing historical records), naturally ordered by time, and the time element itself is usually crucial for analysis.

Common examples of time-series data include: stock prices over time, weather measurements (temperature, humidity, wind speed), monthly subscriber counts on a website, sensor readings from IoT devices, etc.

We encountered time-series data in a real-world e-commerce project we built. We needed to track how many times product pages were viewed and how often users clicked on them. We also recorded each product's daily position in search results, since merchants paid for premium placements. This created a perfect time-series dataset - every day we collected thousands of new records with timestamps, while the historical data remained unchanged. We used this data to show merchants evidence that higher positions actually led to more visibility and clicks.

### Common Challenges

When working with time-series data, there are several important challenges to consider:

- **Data Volume and Scaling**: High-frequency data collection leads to rapid growth, making traditional databases struggle with performance
- **Complex Aggregations**: Queries like averages, sums, or analyzing changes over time need to be performed efficiently.

This requires specialized approaches for optimal storage and querying. Traditional relational databases can become overwhelmed when dealing with large volumes of time-series data, especially when performing complex time-based aggregations.

### Time-Series Databases

Several specialized database systems exist to address these challenges: InfluxDB, Prometheus, Apache Druid, MongoDB, Amazon Timestream. Each has its strengths and fits different use cases. However, in this article, we'll focus on TimescaleDB.

## TimescaleDB

TimescaleDB is a time-series database built as an extension to PostgreSQL with time-series optimizations. Unlike other solutions that require learning new query languages, TimescaleDB lets you continue using familiar SQL.

### Key Features:

- **Postgres-Based**: Full SQL compatible and supports relational capabilities
- **Hypertables**: Unlike standard PostgreSQL tables that store all data in a single table, hypertables automatically partition your time-series data into chunks based on time intervals. This makes queries faster since they only need to scan relevant time chunks instead of the entire dataset
- **Data Lifecycle Management**: Automatic data handling through features like:
  - Continuous aggregation - pre-calculates common metrics (like daily averages or hourly sums) and keeps them updated automatically, so dashboards and reports run 100-1000x faster without recalculating from raw data each time
  - Data retention policies that automatically remove old data past a certain age
  - [Tiered storage](https://docs.timescale.com/use-timescale/latest/data-tiering/) - automatically moves older, less frequently accessed data to low-cost object storage (built on Amazon S3) while keeping recent data in high-performance storage

Below we'll see TimescaleDB in action with some real-world examples.

## Practical Example: Intel Lab Sensor Data

For our practical example, we're using sensor data from the [Intel Berkeley Research Lab](https://db.csail.mit.edu/labdata/labdata.html). This dataset contains millions of temperature, humidity, light, and voltage readings from 54 sensors deployed throughout the lab over a 2-month period. We chose this dataset because, despite its relatively small size (about 2.3 million readings), it has enough data for demonstrating the performance differences between PostgreSQL and TimescaleDB.

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

Note: Performance results may vary on different hardware configurations, but the overall tendency should remain consistent across systems.

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
- The core of TimescaleDB's advantage is its hypertable architecture. Hypertables automatically partition time-series data into chunks based on time intervals. When querying, TimescaleDB identifies and scans only the relevant chunks instead of the entire dataset reducing I/O operations for time-bounded queries
- The `time_bucket` function is specifically optimized to work with this chunked architecture, making it more efficient than PostgreSQL's `date_trunc`


### Advanced TimescaleDB Features: Continuous Aggregates

Think of continuous aggregates as your personal data assistant that works ahead of time. Instead of forcing your database to recalculate the same aggregations (like daily averages or hourly counts) every time someone views a dashboard, TimescaleDB does this work in advance and keeps it ready to serve instantly. 

Imagine you're tracking temperature data that updates every minute, but your dashboard only needs to show daily averages. Rather than scanning millions of raw data points each time the dashboard loads, continuous aggregates pre-calculates data and store what you need. They automatically update as new data arrives.

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
TimescaleDB also saves you storage costs while maintaining query performance. With our temperature sensor data - 54 sensors taking readings every minute for months, this means we will need extra storage by time.

For newer TimescaleDB versions (v2.18.0+), Hypercore automatically handles the storage management. But for this example, we will take a look a compression policy.

Setting up compression is simple with [compression policies](https://docs.timescale.com/use-timescale/latest/compression/compression-policy/) - just tell TimescaleDB to compress chunks older than a certain age (like 7 days), and it handles everything automatically in the background.

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
- Compression maintains query functionality and reduces the storage costs
- Choose compression settings strategically:
  - `compress_orderby='time'`: Best for time-series data as values typically follow changes over time
  - `compress_segmentby='sensor_id'`: Group data by columns you frequently filter or aggregate on
  - For example, if you often query `SELECT avg(temperature) FROM sensors WHERE sensor_id = 5`, using sensor_id as segmentby will improve query performance

[Learn more about compression settings](https://docs.timescale.com/use-timescale/latest/compression/about-compression/)


## Final Thoughts
Our performance tests demonstrated TimescaleDB's advantages for time-series data management. While traditional PostgreSQL performed better for 
simple queries, TimescaleDB is a good choice in complex time-based operations with performance improvement for aggregation queries.

In our real-world e-commerce project, we successfully implemented TimescaleDB to track product page views, click-through rates, and search position rankings. This gave us the perfect solution for our expanding dataset—every day, we collected thousands of new timestamped records while keeping historical data intact. Using continuous aggregation, we were able to efficiently analyze how premium placements affected visibility and clicks across a 2-3 year period, providing merchants with evidence that higher positions actually increased engagement.

The storage benefits were substantial too. TimescaleDB's compression reduced our storage needs by about 30-40%. This led to real cost savings in our cloud bills. Our analytics platform became more responsive, and our budget healthier. These benefits matter even more when you're dealing with large amounts of time-series data.

If you work with growing time-series data and need complex analysis, TimescaleDB is worth considering. It gives you powerful tools while letting you keep using familiar SQL.

---


https://maddevs.io/writeups/tax-fee-erc-20-token-design/


