import os
import time
import concurrent.futures
from datetime import datetime
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
import pandas_ta as ta
from flask import Flask, render_template, request

# --------------------------------------------------------------------------
# 제공된 스크립트의 핵심 로직 (데이터 생성용)
# --------------------------------------------------------------------------

def calculate_indicators(df):
  """주가 데이터에 보조 지표를 계산하여 추가하는 함수"""
  first_day_close = df['Close'].iloc[0]
  for period_days in [21, 63, 126]: # 1M, 3M, 6M
    period_str = f"{period_days // 21}M"
    return_col = f'Return_{period_str}'
    base_price = df['Close'].shift(period_days)
    base_price.fillna(first_day_close, inplace=True)
    df[return_col] = df['Close'] / base_price - 1

  df['Weighted_Return'] = (df['Return_1M'] * 0.4 +
                           df['Return_3M'] * 0.3 +
                           df['Return_6M'] * 0.2)
  return df

def calculate_relative_strength(df):
  """전체 종목 데이터프레임에 대해 상대 강도(RS)를 계산하는 함수"""
  # 날짜별로 그룹화
  grouped = df.groupby(df.index)

  # 기간별 RS 계산
  for period in ["1M", "3M", "6M"]:
    return_col = f'Return_{period}'
    rs_col = f'RS_{period}'
    df[rs_col] = grouped[return_col].rank(pct=True) * 98 + 1
    df[rs_col] = df[rs_col].fillna(1).astype(int).clip(1, 99)

  # 가중 RS 계산
  df['RS'] = grouped['Weighted_Return'].rank(pct=True) * 98 + 1
  df['RS'] = df['RS'].fillna(1).astype(int).clip(1, 99)
  return df

def process_stock(row, start_date):
  """개별 종목 데이터를 가져오고 지표를 계산하는 함수"""
  try:
    symbol = row['Code']
    df = fdr.DataReader(symbol, start_date)
    if len(df) < 126: # 최소 6개월 데이터가 없으면 건너뛰기
      return None

    df = calculate_indicators(df)
    df['Code'] = symbol
    df['Name'] = row['Name']
    df['Marcap'] = row['Marcap']
    return df
  except Exception as e:
    print(f"Error processing {row['Code']} ({row['Name']}): {e}")
    return None

def parallel_process_stocks(all_stocks, start_date):
  """멀티스레딩을 사용하여 여러 종목을 병렬로 처리하는 함수"""
  process_func = partial(process_stock, start_date=start_date)
  results = []
  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(process_func, row) for _, row in all_stocks.iterrows()]
    for future in concurrent.futures.as_completed(futures):
      result = future.result()
      if result is not None:
        results.append(result)
  return pd.concat(results) if results else pd.DataFrame()


# --------------------------------------------------------------------------
# Flask 애플리케이션 설정
# --------------------------------------------------------------------------

app = Flask(__name__)
DATA_FILE = 'rs_data.csv'
STOCKS_PER_PAGE = 20

@app.template_filter('format_marcap')
def format_market_cap(marcap):
  """시가총액을 조 또는 억 단위로 포맷팅하는 필터"""
  if pd.isna(marcap):
    return "N/A"
  marcap = float(marcap)
  if marcap >= 1e12:  # 1조 이상
    return f"{marcap / 1e12:.1f}조"
  else:
    return f"{marcap / 1e8:.0f}억"

@app.cli.command("generate-data")
def generate_data_command():
  """CLI 명령어: RS 데이터를 계산하고 CSV 파일로 저장"""
  print("Starting data generation...")
  start_time = time.time()

  try:
    all_stocks = pd.concat([
      fdr.StockListing('KOSPI'),
      fdr.StockListing('KOSDAQ')
    ], ignore_index=True)

    # 스팩, 우선주 등 제외
    all_stocks = all_stocks[
      ~all_stocks['Name'].str.contains('스팩', na=False) &
      ~all_stocks['Code'].str.endswith(("5", "7", "9", "K", "L", "M", "N", "O"))
      ]

    start_date = (datetime.now() - pd.DateOffset(years=2)).strftime('%Y-%m-%d')

    # 데이터 처리
    result_data = parallel_process_stocks(all_stocks, start_date)
    if result_data.empty:
      print("No data processed.")
      return

    result_data = calculate_relative_strength(result_data)

    # 가장 최신 날짜의 데이터만 선택
    latest_date = result_data.index.max()
    latest_data = result_data.loc[latest_date].copy()

    # 필요한 컬럼만 선택 및 데이터 타입 정리
    final_cols = ['Name', 'Code', 'RS', 'RS_1M', 'RS_3M', 'RS_6M', 'Marcap']
    latest_data = latest_data[final_cols]
    latest_data = latest_data.dropna(subset=['RS']).astype({'RS': int, 'RS_1M': int, 'RS_3M': int, 'RS_6M': int})

    # 파일로 저장
    latest_data.to_csv(DATA_FILE, index=False)

    end_time = time.time()
    print(f"Data successfully generated and saved to {DATA_FILE}")
    print(f"Total time: {end_time - start_time:.2f} seconds")

  except Exception as e:
    print(f"An error occurred during data generation: {e}")


@app.route('/')
def index():
  if not os.path.exists(DATA_FILE):
    return "Data file not found. Please run 'flask generate-data' command in your terminal first.", 500

  df = pd.read_csv(DATA_FILE)

  # 1. 검색 (필터링)
  query = request.args.get('query', '')
  if query:
    df = df[
      df['Name'].str.contains(query, case=False, na=False) |
      df['Code'].str.contains(query, case=False, na=False)
      ].copy()

  # 2. 정렬
  sort_by = request.args.get('sort_by', 'RS')
  sort_order = request.args.get('sort_order', 'desc')
  if sort_by in df.columns:
    df = df.sort_values(
        by=sort_by,
        ascending=(sort_order == 'asc')
    ).reset_index(drop=True)

  # 3. 페이지네이션
  page = request.args.get('page', 1, type=int)
  total_stocks = len(df)
  total_pages = (total_stocks + STOCKS_PER_PAGE - 1) // STOCKS_PER_PAGE
  start = (page - 1) * STOCKS_PER_PAGE
  end = start + STOCKS_PER_PAGE
  paginated_df = df.iloc[start:end]

  # 페이지네이션 네비게이션을 위한 로직
  # 예: 현재 페이지가 5일때, 3, 4, [5], 6, 7 을 보여줌
  start_page = max(1, page - 2)
  end_page = min(total_pages, page + 2)
  if page < 3:
    end_page = min(total_pages, 5)
  if page > total_pages - 2:
    start_page = max(1, total_pages - 4)


  return render_template(
      'index.html',
      stocks=paginated_df.to_dict(orient='records'),
      page=page,
      total_pages=total_pages,
      start_page=start_page,
      end_page=end_page,
      query=query,
      sort_by=sort_by,
      sort_order=sort_order,
      total_stocks=total_stocks
  )

if __name__ == '__main__':
  app.run(debug=True)