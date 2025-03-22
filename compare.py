import psycopg2
import pandas as pd
import re

# Database connection parameters
DB_PARAMS = {
    'host': 'localhost',
    'port': '5432',
    'database': 'intel_lab',
    'user': 'timescale',
    'password': 'password123'
}

# Test queries to compare
COMPARISON_QUERIES = [
    {
        'name': 'Full Range Select',
        'postgres': """
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT * FROM sensor_data_postgres 
            WHERE time >= '2004-02-28 00:58:46.002832+00' 
            AND time <= '2004-04-05 11:02:32.715337+00';
        """,
        'timescale': """
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT * FROM sensor_data_timescale 
            WHERE time >= '2004-02-28 00:58:46.002832+00' 
            AND time <= '2004-04-05 11:02:32.715337+00';
        """
    },
    {
        'name': 'Time-Based Aggregations',
        'postgres': """
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT 
                date_trunc('day', time) as day,
                sensor_id,
                COUNT(*) as readings,
                AVG(temperature) as avg_temp,
                stddev(temperature) as temp_stddev
            FROM sensor_data_postgres
            WHERE time >= '2004-02-28 00:58:46.002832+00' 
            AND time <= '2004-04-05 11:02:32.715337+00'
            GROUP BY day, sensor_id
            HAVING stddev(temperature) > 2
            ORDER BY day, sensor_id;
        """,
        'timescale': """
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT 
                time_bucket('1 day', time) as day,
                sensor_id,
                COUNT(*) as readings,
                AVG(temperature) as avg_temp,
                stddev(temperature) as temp_stddev
            FROM sensor_data_timescale
            WHERE time >= '2004-02-28 00:58:46.002832+00' 
            AND time <= '2004-04-05 11:02:32.715337+00'
            GROUP BY day, sensor_id
            HAVING stddev(temperature) > 2
            ORDER BY day, sensor_id;
        """
    },
    {
        'name': 'Continuous Aggregation',
        'postgres': """
            -- Create a view for PostgreSQL (will be computed on each query)
            DROP VIEW IF EXISTS pg_daily_sensor_stats;
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
            
            -- Time the query against the view
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT * FROM pg_daily_sensor_stats
            WHERE day >= '2004-03-01' AND day <= '2004-03-31'
            ORDER BY day, sensor_id;
        """,
        'timescale': """
            -- Time the query against the continuous aggregate
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT * FROM ts_daily_sensor_stats
            WHERE day >= '2004-03-01' AND day <= '2004-03-31'
            ORDER BY day, sensor_id;
        """,
        'setup': [
            """DROP MATERIALIZED VIEW IF EXISTS ts_daily_sensor_stats;""",
            """CREATE MATERIALIZED VIEW ts_daily_sensor_stats
               WITH (timescaledb.continuous) AS
               SELECT
                   time_bucket('1 day', time) as day,
                   sensor_id,
                   AVG(temperature) as avg_temp,
                   MIN(temperature) as min_temp,
                   MAX(temperature) as max_temp,
                   COUNT(*) as reading_count
               FROM sensor_data_timescale
               GROUP BY day, sensor_id;""",
            """CALL refresh_continuous_aggregate('ts_daily_sensor_stats', NULL, NULL);"""
        ]
    }
]

def analyze_query_plan(plan_output):
    """Analyze the query plan and return key insights."""
    insights = []
    
    # Check scan type
    if 'Seq Scan' in plan_output:
        insights.append("Using Sequential Scan (full table scan)")
    if 'Index Scan' in plan_output:
        insights.append("Using Index Scan (efficient for small result sets)")
    if 'Bitmap Heap Scan' in plan_output:
        insights.append("Using Bitmap Scan (efficient for medium result sets)")
    
    # Check for sorts
    if 'Sort' in plan_output:
        sort_method = 'in memory' if 'Sort Method: quicksort' in plan_output else 'on disk'
        insights.append(f"Performing {sort_method} sort")
    
    # Check for hash operations
    if 'Hash Join' in plan_output:
        insights.append("Using Hash Join")
    if 'Hash Aggregate' in plan_output:
        insights.append("Using Hash Aggregation")
    
    # Check for continuous aggregates
    if 'ts_daily_sensor_stats' in plan_output:
        insights.append("Using pre-computed continuous aggregate")
        
        # Check if it's using the materialized data
        if 'Seq Scan on _timescaledb_internal' in plan_output:
            insights.append("Reading from pre-aggregated chunks (optimized)")
    
    # Check buffer usage
    shared_hits = re.search(r'shared hit blocks: (\d+)', plan_output)
    shared_reads = re.search(r'shared read blocks: (\d+)', plan_output)
    if shared_hits and shared_reads:
        hits = int(shared_hits.group(1))
        reads = int(shared_reads.group(1))
        if hits > 0:
            insights.append(f"Cache hits: {hits} blocks")
        if reads > 0:
            insights.append(f"Disk reads: {reads} blocks")
    
    # Check rows
    rows_pattern = r'actual time=[\d.]+\.\.[\d.]+ rows=(\d+)'
    rows_match = re.search(rows_pattern, plan_output)
    if rows_match:
        insights.append(f"Processed {rows_match.group(1)} rows")
    
    # TimescaleDB specific
    if '_hyper_' in plan_output:
        insights.append("Using TimescaleDB chunks")
        chunk_count = len(re.findall(r'_hyper_\d+_\d+_chunk', plan_output))
        if chunk_count > 0:
            insights.append(f"Accessed {chunk_count} chunks")
    
    return insights

def extract_times_and_analyze(explain_output):
    """Extract timing information and analyze the query plan."""
    planning_time = None
    execution_time = None
    
    for line in explain_output.split('\n'):
        if 'Planning Time' in line:
            planning_time = float(line.split(':')[1].strip().split(' ')[0])
        elif 'Execution Time' in line:
            execution_time = float(line.split(':')[1].strip().split(' ')[0])
    
    insights = analyze_query_plan(explain_output)
    
    return planning_time, execution_time, insights

def get_table_size(cur, table_name):
    """Get the size of a table or materialized view in MB"""
    cur.execute(f"""
        SELECT pg_size_pretty(pg_total_relation_size('{table_name}')) as size,
               pg_total_relation_size('{table_name}') as bytes
        FROM pg_class
        WHERE relname = '{table_name}';
    """)
    return cur.fetchone()[1] / (1024 * 1024)  # Convert bytes to MB

def get_continuous_aggregate_size(cur, view_name):
    """Get the size of a continuous aggregate's materialized data in bytes"""
    try:
        # Get the materialization table details
        cur.execute("""
            SELECT materialization_hypertable_schema, materialization_hypertable_name
            FROM timescaledb_information.continuous_aggregates 
            WHERE view_name = %s;
        """, (view_name,))
        result = cur.fetchone()
        
        if result is None:
            print(f"Warning: No materialization table found for view {view_name}")
            return 0
            
        schema, table = result
        
        # Get the size
        size_query = f"SELECT pg_total_relation_size('{schema}.{table}')"
        cur.execute(size_query)
        size_result = cur.fetchone()
        
        if size_result is None:
            print(f"Warning: Could not get size for {schema}.{table}")
            return 0
            
        return size_result[0]
        
    except Exception as e:
        print(f"Error in get_continuous_aggregate_size: {e}")
        return 0

def run_comparison():
    results = []
    conn = None
    
    try:
        # Initial connection for setup queries that need AUTOCOMMIT
        if any('setup' in q for q in COMPARISON_QUERIES):
            setup_conn = psycopg2.connect(**DB_PARAMS)
            setup_conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            setup_cur = setup_conn.cursor()
            
            for query in COMPARISON_QUERIES:
                if 'setup' in query:
                    for setup_query in query['setup']:
                        print(f"Debug: Executing setup query")
                        setup_cur.execute(setup_query)
            
            setup_conn.close()

        # Main connection for performance testing
        conn = psycopg2.connect(**DB_PARAMS)
        
        for query in COMPARISON_QUERIES:
            cur = conn.cursor()
            
            # Get storage sizes for continuous aggregation comparison
            if query['name'] == 'Continuous Aggregation':
                try:
                    # Get raw table size
                    cur.execute("SELECT pg_total_relation_size('sensor_data_timescale')")
                    raw_result = cur.fetchone()
                    raw_size = raw_result[0] if raw_result else 0
                    
                    # Get aggregate size
                    agg_size = get_continuous_aggregate_size(cur, 'ts_daily_sensor_stats')
                    
                    storage_info = {
                        'raw_size': raw_size,
                        'agg_size': agg_size,
                        'size_ratio': (agg_size / raw_size * 100) if raw_size > 0 else 0
                    }
                except Exception as e:
                    print(f"Error in storage size calculation: {e}")
                    storage_info = {
                        'raw_size': 0,
                        'agg_size': 0,
                        'size_ratio': 0
                    }
            
            # Run PostgreSQL query
            cur.execute(query['postgres'])
            pg_output = '\n'.join([row[0] for row in cur.fetchall()])
            pg_planning, pg_execution, pg_insights = extract_times_and_analyze(pg_output)
            
            # Run TimescaleDB query
            cur.execute(query['timescale'])
            ts_output = '\n'.join([row[0] for row in cur.fetchall()])
            ts_planning, ts_execution, ts_insights = extract_times_and_analyze(ts_output)
            
            result = {
                'Query': query['name'],
                'PG Planning (ms)': pg_planning,
                'PG Execution (ms)': pg_execution,
                'PG Insights': '\n'.join(pg_insights),
                'TS Planning (ms)': ts_planning,
                'TS Execution (ms)': ts_execution,
                'TS Insights': '\n'.join(ts_insights),
                'Faster Engine': 'TimescaleDB' if ts_execution < pg_execution else 'PostgreSQL',
                'Speed Difference (ms)': abs(ts_execution - pg_execution)
            }
            
            # Add storage information for continuous aggregation
            if query['name'] == 'Continuous Aggregation':
                result['Storage Info'] = storage_info
            
            results.append(result)
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if conn:
            conn.close()
    
    return results

def main():
    print("Running performance comparison...")
    results = run_comparison()
    
    # Convert results to pandas DataFrame
    df = pd.DataFrame(results)
    
    # Print detailed results for each query
    for _, row in df.iterrows():
        print("\n" + "="*80)
        print(f"\nQuery: {row['Query']}")
        
        # Print storage information for continuous aggregation
        if row['Query'] == 'Continuous Aggregation' and 'Storage Info' in row:
            print("\nStorage Information:")
            print(f"  Raw data size: {row['Storage Info']['raw_size'] / 1024:.1f} kB")
            print(f"  Aggregate size: {row['Storage Info']['agg_size'] / 1024:.1f} kB")
            print(f"  Size ratio: {row['Storage Info']['size_ratio']:.1f}%")
        
        print(f"\nPostgreSQL:")
        print(f"  Planning time: {row['PG Planning (ms)']:.3f} ms")
        print(f"  Execution time: {row['PG Execution (ms)']:.3f} ms")
        print("  Insights:")
        for insight in row['PG Insights'].split('\n'):
            print(f"    - {insight}")
        
        print(f"\nTimescaleDB:")
        print(f"  Planning time: {row['TS Planning (ms)']:.3f} ms")
        print(f"  Execution time: {row['TS Execution (ms)']:.3f} ms")
        print("  Insights:")
        for insight in row['TS Insights'].split('\n'):
            print(f"    - {insight}")
        
        print(f"\nWinner: {row['Faster Engine']} (by {row['Speed Difference (ms)']:.3f} ms)")
    
    # Print summary
    print("\n" + "="*80)
    print("\nOverall Summary:")
    print(f"Total queries compared: {len(results)}")
    pg_wins = sum(1 for r in results if r['Faster Engine'] == 'PostgreSQL')
    ts_wins = sum(1 for r in results if r['Faster Engine'] == 'TimescaleDB')
    print(f"PostgreSQL faster: {pg_wins} queries")
    print(f"TimescaleDB faster: {ts_wins} queries")
    
    # Add continuous aggregation performance info
    cont_agg_result = next((r for r in results if r['Query'] == 'Continuous Aggregation'), None)
    if cont_agg_result:
        speedup = cont_agg_result['PG Execution (ms)'] / cont_agg_result['TS Execution (ms)']
        print(f"\nContinuous Aggregation Performance:")
        print(f"  PostgreSQL view: {cont_agg_result['PG Execution (ms)']:.3f} ms")
        print(f"  TimescaleDB continuous aggregate: {cont_agg_result['TS Execution (ms)']:.3f} ms")
        print(f"  Speedup factor: {speedup:.1f}x faster with TimescaleDB")
        print("  Note: In real-world scenarios, the difference would be even more dramatic with larger datasets")
    
    avg_planning_diff = (df['TS Planning (ms)'] - df['PG Planning (ms)']).mean()
    avg_execution_diff = (df['TS Execution (ms)'] - df['PG Execution (ms)']).mean()
    print(f"\nAverage planning time difference (TimescaleDB - PostgreSQL): {avg_planning_diff:.3f} ms")
    print(f"Average execution time difference (TimescaleDB - PostgreSQL): {avg_execution_diff:.3f} ms")

if __name__ == "__main__":
    main()
