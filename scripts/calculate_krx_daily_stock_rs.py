import os
import sys
import time
import argparse
from datetime import datetime, timedelta

import pandas as pd

# Add root project path to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rs
from models import KrxDailyStockRS
from db import engine
from sqlmodel import Session
from sqlalchemy import insert

def chunked_iterable(iterable, size):
    """Yield successive chunks from iterable."""
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]

def filter_common_stocks(df):
    """시가총액 2000억 이상, 스팩/우선주 등 제외"""
    exclude_pattern = r'스팩'
    return df[(~df['Name'].str.contains(exclude_pattern, na=False, regex=True))
              & (~df['Code'].str.endswith(("5", "7", "9", "K", "L", "M", "N", "O"))) 
              & (df['Marcap'] >= 200_000_000_000)
              ]

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
    
    print("1. Fetching historical close prices from local DB...")
    start_time = time.time()
    
    query_prices = f"SELECT date, code, close FROM krx_daily_stock WHERE date >= '{start_date_str}' AND date <= '{target_date_str}'"
    df_prices = pd.read_sql(query_prices, engine)
    
    if df_prices.empty:
        print("❌ No data found in the database. Please run update_krx_daily_stock.py first.")
        return

    print("2. Fetching target date metadata for filtering...")
    query_meta = f"SELECT code, name, market, marcap FROM krx_daily_stock WHERE date = '{target_date_str}'"
    df_meta = pd.read_sql(query_meta, engine)
    
    if df_meta.empty:
        print(f"❌ No metadata found for target date {target_date_str}. Date might be a weekend or holiday.")
        return
        
    df_meta.rename(columns={'code': 'Code', 'name': 'Name', 'market': 'Market', 'marcap': 'Marcap'}, inplace=True)
    
    print("3. Pivoting data and calculating returns (Vectorized)...")
    # 2. Pivot to get closing prices matrix
    # Index: date, Columns: code, Values: close
    df_pivot = df_prices.pivot(index='date', columns='code', values='close').sort_index()
    
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
    
    # Merge metadata
    final_df = pd.merge(final_df, df_meta, on='Code', how='inner')
    
    # Apply filter_common_stocks
    final_df = filter_common_stocks(final_df)
    
    # Set index to target date for calculate_relative_strength
    final_df['date'] = target_date_str
    final_df.set_index('date', inplace=True)
    
    print("4. Calculating Relative Strength (RS) scores...")
    final_df = rs.calculate_relative_strength(final_df)
    
    # 3. DataFrame을 Dictionary 리스트로 변환 (Vectorized)
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

    # 4. Turso DB에 벌크 인서트 (Chunk 적용)
    print("6. Inserting RS data into Turso Database in chunks...")
    try:
        chunk_size = 100
        total_chunks = (len(rs_dicts) + chunk_size - 1) // chunk_size
        
        with Session(engine) as session:
            for i, chunk in enumerate(chunked_iterable(rs_dicts, chunk_size)):
                session.execute(insert(KrxDailyStockRS).values(chunk))
            session.commit()
                
        elapsed = time.time() - start_time
        print(f"\n🎉 RS Update & Database Insert Completed Successfully! (⏱️ {elapsed:.2f} seconds)")
        
    except Exception as e:
        print(f"\n❌ Failed to insert data into Turso: {e}")

if __name__ == "__main__":
    main()
