import os
import sys
import time
import argparse
from datetime import datetime, timedelta

import pandas as pd
from psycopg2.extras import execute_values

# Add root project path to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rs
from db import engine

def fetch_historical_prices(start_date_str: str, target_date_str: str) -> pd.DataFrame:
    """Fetch historical adjusted close prices from DB."""
    print("1. Fetching historical close prices from local DB...")
    query_prices = f"SELECT date, code, close as adj_close FROM krx_daily_adjusted_stocks WHERE date >= '{start_date_str}' AND date <= '{target_date_str}'"
    return pd.read_sql(query_prices, engine)

def fetch_target_date_metadata(target_date_str: str) -> pd.DataFrame:
    """Fetch metadata for the target date to use in filtering (excluding KONEX)."""
    print("2. Fetching target date metadata for filtering (excluding KONEX)...")
    query_meta = f"SELECT code, name, market, marcap FROM krx_daily_stocks WHERE date = '{target_date_str}' AND market != 'KONEX'"
    df_meta = pd.read_sql(query_meta, engine)
    
    if not df_meta.empty:
        df_meta.rename(columns={'code': 'Code', 'name': 'Name', 'market': 'Market', 'marcap': 'Marcap'}, inplace=True)
        
    return df_meta

def calculate_returns_matrix(df_prices: pd.DataFrame) -> pd.DataFrame:
    """Pivot data and calculate returns across multiple periods."""
    print("3. Pivoting data and calculating returns (Vectorized)...")
    # Pivot to get closing prices matrix
    # Index: date, Columns: code, Values: adj_close
    df_pivot = df_prices.pivot(index='date', columns='code', values='adj_close').sort_index()
    
    # Calculate Returns for all stocks simultaneously (Vectorized)
    first_day_close = df_pivot.iloc[0]
    
    returns = {}
    for period_days, period_str in [(21, '1M'), (63, '3M'), (126, '6M'), (252, '12M')]:
        base_price = df_pivot.shift(period_days).fillna(first_day_close)
        ret = df_pivot / base_price - 1
        returns[period_str] = ret.iloc[-1]  # Only keep the last date's returns
        
    # Create a cross-sectional DataFrame for the target date
    final_df = pd.DataFrame({
        'Code': df_pivot.columns,
        'Return_1M': returns['1M'].values,
        'Return_3M': returns['3M'].values,
        'Return_6M': returns['6M'].values,
        'Return_12M': returns['12M'].values,
    })
    
    return final_df

def prepare_rs_records(final_df: pd.DataFrame, df_meta: pd.DataFrame, target_date_str: str) -> list:
    """Merge metadata, calculate RS scores, and format as list of dictionaries."""
    # Merge metadata
    final_df = pd.merge(final_df, df_meta, on='Code', how='inner')
    
    # Set index to target date for calculate_relative_strength
    final_df['date'] = target_date_str
    final_df.set_index('date', inplace=True)
    
    print("4. Calculating Relative Strength (RS) scores...")
    final_df = rs.calculate_relative_strength(final_df)
    
    print("5. Converting DataFrame to dictionary records...")
    # Fill NaN
    final_df = final_df.fillna(0.0)
    
    # RS 데이터만 추출하여 컬럼명 매핑
    df_rs = final_df[['Code', 'RS', 'RS_1M', 'RS_3M', 'RS_6M', 'RS_12M']].copy()
    df_rs.rename(columns={
        'Code': 'code',
        'RS': 'rs',
        'RS_1M': 'rs_1m',
        'RS_3M': 'rs_3m',
        'RS_6M': 'rs_6m',
        'RS_12M': 'rs_12m'
    }, inplace=True)
    df_rs['date'] = target_date_str
    
    rs_dicts = df_rs.to_dict(orient='records')
    print(f"✅ Successfully calculated RS for {len(rs_dicts)} stocks.")
    
    return rs_dicts

def bulk_insert_rs_data(rs_dicts: list, target_date_str: str):
    """Insert RS data into Supabase using DELETE + bulk execute_values."""
    print("6. Inserting RS data into Supabase Database using DELETE + Bulk INSERT...")
    raw_conn = engine.raw_connection()
    try:
        cursor = raw_conn.cursor()
        
        # 1. DELETE existing data for the target date to ensure 100% data integrity
        cursor.execute(f"DELETE FROM krx_daily_stock_indicators WHERE date = '{target_date_str}'")
        
        # 2. Bulk INSERT using execute_values (Ultra-fast, Raw DB API)
        tuples = [
            (r['date'], r['code'], r['rs'], r['rs_1m'], r['rs_3m'], r['rs_6m'], r['rs_12m'])
            for r in rs_dicts
        ]
        
        query = """
            INSERT INTO krx_daily_stock_indicators (date, code, rs, rs_1m, rs_3m, rs_6m, rs_12m)
            VALUES %s
        """
        
        # Chunking to prevent PgBouncer statement buffer overflow
        chunk_size = 2000
        for i in range(0, len(tuples), chunk_size):
            execute_values(cursor, query, tuples[i:i+chunk_size])
            
        raw_conn.commit()
    except Exception as inner_e:
        raw_conn.rollback()
        raise inner_e
    finally:
        raw_conn.close()

def main():
    parser = argparse.ArgumentParser(description="Calculate KRX Daily Stock RS (Vectorized)")
    parser.add_argument("--date", type=str, help="Target date in YYYYMMDD format. Defaults to today.")
    args = parser.parse_args()

    if args.date:
        target_date = datetime.strptime(args.date, '%Y%m%d')
    else:
        target_date = datetime.today()
        
    target_date_str = target_date.strftime('%Y-%m-%d')
    
    print("=" * 60)
    print(f"🚀 Starting Vectorized RS Data Calculation for {target_date_str}")
    print("=" * 60)

    start_date_str = (target_date - timedelta(days=540)).strftime('%Y-%m-%d')
    
    start_time = time.time()
    
    # 1. DB에서 과거 주가 데이터 가져오기
    df_prices = fetch_historical_prices(start_date_str, target_date_str)
    if df_prices.empty:
        print("❌ No data found in the database. Please run sync_krx_daily_stocks.py first.")
        return

    # 2. 대상일의 메타데이터(시가총액, 시장 등) 가져오기
    df_meta = fetch_target_date_metadata(target_date_str)
    if df_meta.empty:
        print(f"❌ No metadata found for target date {target_date_str}. Date might be a weekend or holiday.")
        return
        
    # 3. 주가 수익률 계산 (Vectorized Matrix)
    final_df = calculate_returns_matrix(df_prices)
    
    # 4. 최종 RS 점수 계산 및 딕셔너리 변환
    rs_dicts = prepare_rs_records(final_df, df_meta, target_date_str)
    
    # 5. DB에 Bulk Insert
    try:
        bulk_insert_rs_data(rs_dicts, target_date_str)
        elapsed = time.time() - start_time
        print(f"\n🎉 RS Update & Database Insert Completed Successfully! (⏱️ {elapsed:.2f} seconds)")
    except Exception as e:
        print(f"\n❌ Failed to insert data into Supabase: {e}")

if __name__ == "__main__":
    main()
