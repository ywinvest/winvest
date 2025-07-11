import concurrent.futures
import time
from datetime import datetime
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
from dotenv import load_dotenv


def calculate_indicators(df):
  """개별 종목의 보조지표를 계산합니다."""
  df['Return_1M'] = df['Close'] / df['Close'].shift(20) - 1
  df['Return_3M'] = df['Close'] / df['Close'].shift(60) - 1
  df['Return_6M'] = df['Close'] / df['Close'].shift(120) - 1
  df['Return_12M'] = df['Close'] / df['Close'].shift(240) - 1
  df['Weighted_Return'] = (df['Return_3M'] * 0.5 +
                           df['Return_6M'] * 0.3 +
                           df['Return_12M'] * 0.2)
  return df


def calculate_relative_strength(df):
  """전체 종목에 대한 상대강도를 계산합니다."""
  for period in ["1M", "3M", "6M", "12M"]:
    return_col = f'Return_{period}'
    rs_col = f'RS_{period}'

    df[rs_col] = df.groupby('Market')[return_col].rank(pct=True) * 98 + 1
    df[rs_col] = df[rs_col].fillna(1).astype(int).clip(1, 99)

  df['RS'] = df.groupby('Market')['Weighted_Return'].rank(pct=True) * 98 + 1
  df['RS'] = df['RS'].fillna(1).astype(int).clip(1, 99)

  return df

def filter_common_stocks(df):
  """분석에서 제외할 종목(스팩, 우선주 등)을 필터링합니다."""
  exclude_pattern = r'스팩'
  return df[(~df['Name'].str.contains(exclude_pattern, na=False, regex=True))
            & (~df['Code'].str.endswith(("5", "7", "9", "K", "L", "M", "N", "O"))) # 우선주, 일부 ETN/ETF 등 제외
            & (df['Code'] != '0030R0')
            & (df['Marcap'] >= 200_000_000_000)
    # & (df['Name'].str.contains("나무기술", na=False, regex=True))
            ]
def process_stock(row, two_years_ago):
  """개별 종목의 시세 데이터를 가져와 보조지표를 계산합니다."""
  try:
    symbol = row['Code']

    df = fdr.DataReader(symbol, two_years_ago)
    df = calculate_indicators(df)

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
    ], ignore_index=True)

    all_stocks = filter_common_stocks(all_stocks)

    # 날짜 설정
    today = datetime.today()
    two_years_ago = today.year - 2

    result_file = "rs.csv"

    # 병렬 처리로 데이터 분석
    result_data = parallel_process_stocks(all_stocks, two_years_ago)
    result_data = calculate_relative_strength(result_data)

    # <<<--- 변경된 부분 시작 --->>>
    # 데이터프레임의 인덱스(날짜)를 'Date' 컬럼으로 변환
    result_data.reset_index(inplace=True)

    # 가장 최신 날짜(오늘 또는 최근 거래일)를 찾음
    latest_date = result_data['Date'].max()

    # 최신 날짜에 해당하는 데이터만 필터링
    latest_data = result_data[result_data['Date'] == latest_date].copy()
    # <<<--- 변경된 부분 끝 --->>>

    # 필터링된 최신 데이터만 CSV 파일로 저장
    latest_data.to_csv(result_file, index=False, encoding='utf-8-sig')

    print(f"총 {len(latest_data)}개 종목의 최신 RS 데이터가 {result_file}에 저장되었습니다.")

  except Exception as e:
    print(f"Error in main execution: {e}")

  finally:
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"총 소요시간: {elapsed_time:.2f}초")