import concurrent.futures
import time
from datetime import datetime, timedelta
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
from dotenv import load_dotenv


def calculate_indicators(df):
  first_day_close = df['Close'].iloc[0]
  for period_days in [21, 63, 126, 189, 252]:
    period_str = f"{period_days // 21}M"
    return_col = f'Return_{period_str}'
    base_price = df['Close'].shift(period_days)
    base_price.fillna(first_day_close, inplace=True)
    df[return_col] = df['Close'] / base_price - 1

  # 현재 종가 대비 수익률로 계산
  df['Weighted_Return'] = (df['Return_1M'] * 0.4 +
                           df['Return_3M'] * 0.2 +
                           df['Return_6M'] * 0.2 +
                           df['Return_12M'] * 0.2)
  return df


def calculate_relative_strength(df):
  # # Group by the date index to perform calculations on each day's data
  # grouped = df.groupby(df.index)
  #
  # # Define a reusable function for scaling ranks
  # def scale_rank(x):
  #   # Handle groups with one or zero valid entries to avoid division by zero
  #   if x.notna().sum() <= 1:
  #     return pd.Series(1, index=x.index) # Assign a default low score
  #
  #   # This is the core scaling logic
  #   # 1. Get the rank (1, 2, 3, ...)
  #   # 2. Scale it to a 0-1 range: (rank - 1) / (count - 1)
  #   # 3. Scale it to a 0-98 range: * 98
  #   # 4. Shift it to a 1-99 range: + 1
  #   count = x.notna().sum()
  #   scaled_rs = (x.rank(method='average') - 1) / (count - 1) * 98 + 1
  #   return scaled_rs
  #
  # # Apply the scaling function to each return period
  # for period in ["1M", "3M", "6M", "9M", "12M"]:
  #   return_col = f'Return_{period}'
  #   rs_col = f'RS_{period}'
  #   df[rs_col] = grouped[return_col].transform(scale_rank)
  #
  # # Also apply it to the final weighted return
  # df['RS'] = grouped['Weighted_Return'].transform(scale_rank)
  #
  # # Round, fill any remaining NaNs, convert to integer, and clip to the 1-99 range
  # rs_cols = [f'RS_{p}' for p in ["1M", "3M", "6M", "9M", "12M"]] + ['RS']
  # for col in rs_cols:
  #   df[col] = df[col].round().fillna(1).astype(int).clip(1, 99)

  grouped = df.groupby([df.index])
  for period in ["1M", "3M", "6M", "9M", "12M"]:
    return_col = f'Return_{period}'
    rs_col = f'RS_{period}'

    df[rs_col] = grouped[return_col].rank(pct=True) * 98 + 1
    df[rs_col] = df[rs_col].fillna(1).astype(int).clip(1, 99)

  df['RS'] = grouped['Weighted_Return'].rank(pct=True) * 98 + 1
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
    name = row['Name']
    market = row['Market']
    marcap = row['Marcap']

    df = fdr.DataReader(symbol, two_years_ago)
    df = calculate_indicators(df)
    df['Code'] = symbol
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

    today = datetime.today()
    yesterday = today - timedelta(days=1)
    two_years_ago = today.year - 2
    result_file = "rs.csv"
    result_data = parallel_process_stocks(all_stocks, two_years_ago)
    # 오늘 날짜만 필터링
    result_data = result_data[result_data.index.date == today.date()]

    # 오늘 데이터만 기준으로 RS 계산
    result_data = calculate_relative_strength(result_data)

    result_data = filter_common_stocks(result_data)

    print("RS 분포 (전체):", result_data['RS'].dropna().value_counts(bins=10))
    # print("RS 분포 (시장별):", result_data.groupby('Market')['RS'].dropna().value_counts(bins=10))

    result_data.to_csv(result_file, index=False, encoding='utf-8-sig')
    print(f"총 {len(result_data)}개 종목의 오늘자 RS 데이터가 {result_file}에 저장되었습니다.")
  except Exception as e:
    print(f"Error in main execution: {e}")

  finally:
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"총 소요시간: {elapsed_time:.2f}초")