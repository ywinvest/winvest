import concurrent.futures
import time
from datetime import datetime, timedelta
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
from dotenv import load_dotenv


def calculate_indicators(df):
  """개별 종목의 보조지표를 계산합니다."""
  # 최초 상장일의 종가
  first_day_close = df['Close'].iloc[0]

  for period_days in [20, 60, 120, 240]:
    # period_days에 따른 컬럼 이름 설정 (1M, 3M, 6M, 12M)
    period_str = f"{period_days // 20}M" if period_days < 240 else "12M"
    return_col = f'Return_{period_str}'

    # period_days 이전의 종가 데이터 (과거 데이터가 없으면 NaN)
    base_price = df['Close'].shift(period_days)

    # NaN 값을 최초 상장일 종가로 채워서 기준 가격 설정
    # 이렇게 하면 과거 데이터가 있는 날은 과거 종가를, 없는 날은 최초 상장일 종가를 사용
    base_price.fillna(first_day_close, inplace=True)

    # 수익률 계산
    df[return_col] = df['Close'] / base_price - 1

  # df['Return_1M'] = df['Close'] / df['Close'].shift(20) - 1
  # df['Return_3M'] = df['Close'] / df['Close'].shift(60) - 1
  # df['Return_6M'] = df['Close'] / df['Close'].shift(120) - 1
  # df['Return_12M'] = df['Close'] / df['Close'].shift(240) - 1
  df['Weighted_Return'] = (df['Return_3M'] * 0.5 +
                           df['Return_6M'] * 0.3 +
                           df['Return_12M'] * 0.2)
  return df


def calculate_relative_strength(df):
  """전체 종목에 대한 상대강도를 계산합니다. (KOSDAQ GLOBAL은 KOSDAQ과 합쳐서 계산)"""
  # KOSDAQ GLOBAL을 KOSDAQ으로 변경하여 합쳐서 계산
  df['Market_Group'] = df['Market'].replace('KOSDAQ GLOBAL', 'KOSDAQ')

  for period in ["1M", "3M", "6M", "12M"]:
    return_col = f'Return_{period}'
    rs_col = f'RS_{period}'

    df[rs_col] = df.groupby('Market_Group')[return_col].rank(pct=True) * 98 + 1
    df[rs_col] = df[rs_col].fillna(1).astype(int).clip(1, 99)

  df['RS'] = df.groupby('Market_Group')['Weighted_Return'].rank(pct=True) * 98 + 1
  df['RS'] = df['RS'].fillna(1).astype(int).clip(1, 99)

  # Market_Group 컬럼 제거 (원본 Market 컬럼 유지)
  df = df.drop('Market_Group', axis=1)

  return df

def filter_common_stocks(df):
  """분석에서 제외할 종목(스팩, 우선주 등)을 필터링합니다."""
  exclude_pattern = r'스팩'
  return df[(~df['Name'].str.contains(exclude_pattern, na=False, regex=True))
            & (~df['Code'].str.endswith(("5", "7", "9", "K", "L", "M", "N", "O"))) # 우선주, 일부 ETN/ETF 등 제외
            & (df['Code'] != '0030R0')
            # & (df['Marcap'] >= 200_000_000_000)
    # & (df['Name'].str.contains("나무기술", na=False, regex=True))
            ]
def process_stock(row, two_years_ago):
  """개별 종목의 시세 데이터를 가져와 보조지표를 계산합니다."""
  try:
    symbol = row['Code']
    name = row['Name']
    market = row['Market']
    marcap = row['Marcap']

    df = fdr.DataReader(symbol, two_years_ago)
    df = calculate_indicators(df)
    df['Name'] = name
    df['Market'] = market
    df['Marcap'] = marcap

    return df
  except Exception as e:
    print(f"Error processing {symbol}: {e}")
    return None

def parallel_process_stocks(all_stocks, two_years_ago):
  """여러 종목의 데이터 처리를 병렬로 수행합니다."""
  process_func = partial(process_stock, two_years_ago=two_years_ago)
  results = []

  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(process_func, row) for _, row in all_stocks.iterrows()]
    for future in concurrent.futures.as_completed(futures):
      result = future.result()
      if result is not None:
        results.append(result)

  return pd.concat(results) if results else pd.DataFrame()

if __name__ == "__main__":
  start_time = time.time()

  # .env 파일 로드
  load_dotenv()

  try:
    all_stocks = pd.concat([
      fdr.StockListing('KOSPI'),
      fdr.StockListing('KOSDAQ'),
    ], ignore_index=True)

    all_stocks = filter_common_stocks(all_stocks)

    # 날짜 설정
    today = datetime.today()
    yesterday = datetime.today() - timedelta(days=1) # yesterdate는 2025-07-13 (일요일)이 됨

    two_years_ago = today.year - 2

    result_file = "rs.csv"

    # 병렬 처리로 데이터 분석
    result_data = parallel_process_stocks(all_stocks, two_years_ago)
    result_data = calculate_relative_strength(result_data)

    result_data = result_data[result_data.index.date == yesterday.date()]

    result_data.to_csv(result_file, index=False, encoding='utf-8-sig')

    print(f"총 {len(result_data)}개 종목의 최신 RS 데이터가 {result_file}에 저장되었습니다.")

  except Exception as e:
    print(f"Error in main execution: {e}")

  finally:
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"총 소요시간: {elapsed_time:.2f}초")