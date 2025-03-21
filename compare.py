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
        'name': 'Daily Aggregation',
        'postgres': """
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT 
                date_trunc('day', time) as day,
                sensor_id,
                COUNT(*) as readings,
                AVG(temperature) as avg_temp
            FROM sensor_data_postgres
            WHERE time >= '2004-02-28 00:58:46.002832+00' 
            AND time <= '2004-04-05 11:02:32.715337+00'
            GROUP BY day, sensor_id
            ORDER BY day, sensor_id;
        """,
        'timescale': """
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT 
                time_bucket('1 day', time) as day,
                sensor_id,
                COUNT(*) as readings,
                AVG(temperature) as avg_temp
            FROM sensor_data_timescale
            WHERE time >= '2004-02-28 00:58:46.002832+00' 
            AND time <= '2004-04-05 11:02:32.715337+00'
            GROUP BY day, sensor_id
            ORDER BY day, sensor_id;
        """
    },
    {
        'name': 'Hourly Stats with Temperature Variations',
        'postgres': """
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT 
                date_trunc('hour', time) as hour,
                sensor_id,
                COUNT(*) as readings,
                AVG(temperature) as avg_temp,
                stddev(temperature) as temp_stddev
            FROM sensor_data_postgres
            WHERE time >= '2004-02-28 00:58:46.002832+00' 
            AND time <= '2004-04-05 11:02:32.715337+00'
            GROUP BY hour, sensor_id
            HAVING stddev(temperature) > 2
            ORDER BY hour, sensor_id;
        """,
        'timescale': """
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT 
                time_bucket('1 hour', time) as hour,
                sensor_id,
                COUNT(*) as readings,
                AVG(temperature) as avg_temp,
                stddev(temperature) as temp_stddev
            FROM sensor_data_timescale
            WHERE time >= '2004-02-28 00:58:46.002832+00' 
            AND time <= '2004-04-05 11:02:32.715337+00'
            GROUP BY hour, sensor_id
            HAVING stddev(temperature) > 2
            ORDER BY hour, sensor_id;
        """
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

def run_comparison():
    results = []
    
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()
        
        for query in COMPARISON_QUERIES:
            # Run PostgreSQL query
            cur.execute(query['postgres'])
            pg_output = '\n'.join([row[0] for row in cur.fetchall()])
            pg_planning, pg_execution, pg_insights = extract_times_and_analyze(pg_output)
            
            # Run TimescaleDB query
            cur.execute(query['timescale'])
            ts_output = '\n'.join([row[0] for row in cur.fetchall()])
            ts_planning, ts_execution, ts_insights = extract_times_and_analyze(ts_output)
            
            results.append({
                'Query': query['name'],
                'PG Planning (ms)': pg_planning,
                'PG Execution (ms)': pg_execution,
                'PG Insights': '\n'.join(pg_insights),
                'TS Planning (ms)': ts_planning,
                'TS Execution (ms)': ts_execution,
                'TS Insights': '\n'.join(ts_insights),
                'Faster Engine': 'TimescaleDB' if ts_execution < pg_execution else 'PostgreSQL',
                'Speed Difference (ms)': abs(ts_execution - pg_execution)
            })
            
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
    
    avg_planning_diff = (df['TS Planning (ms)'] - df['PG Planning (ms)']).mean()
    avg_execution_diff = (df['TS Execution (ms)'] - df['PG Execution (ms)']).mean()
    print(f"Average planning time difference (TimescaleDB - PostgreSQL): {avg_planning_diff:.3f} ms")
    print(f"Average execution time difference (TimescaleDB - PostgreSQL): {avg_execution_diff:.3f} ms")

if __name__ == "__main__":
    main()
