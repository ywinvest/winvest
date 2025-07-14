import concurrent.futures
import time
from datetime import datetime, timedelta
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
from dotenv import load_dotenv


def calculate_indicators(df):
  first_day_close = df['Close'].iloc[0]
  for period_days in [21, 63, 126, 252]:
    period_str = f"{period_days // 21}M" if period_days < 252 else "12M"
    return_col = f'Return_{period_str}'
    base_price = df['Close'].shift(period_days)
    base_price.fillna(first_day_close, inplace=True)
    df[return_col] = df['Close'] / base_price - 1
  # """실제 달력 기준(1, 3, 6, 12개월)으로 수익률 보조지표를 계산합니다."""
  # # 인덱스를 DatetimeIndex로 변환하고 정렬 (merge_asof를 위해 필수)
  # df.index = pd.to_datetime(df.index)
  # df.sort_index(inplace=True)
  #
  # # 기준 가격 조회를 위한 DataFrame 준비
  # base_prices_df = df[['Close']].rename(columns={'Close': 'Base_Price'})
  # first_day_close = df['Close'].iloc[0]
  #
  # # 기간 설정 (개월)
  # periods = {1: '1M', 3: '3M', 6: '6M', 12: '12M'}
  #
  # # 각 기간에 대해 루프 실행
  # for period_months, period_str in periods.items():
  #   return_col = f'Return_{period_str}'
  #
  #   # 조회할 기준 날짜(target_date) 계산
  #   lookup_df = pd.DataFrame(index=df.index)
  #   lookup_df['target_date'] = lookup_df.index - pd.DateOffset(months=period_months)
  #
  #   # merge_asof를 사용하여 각 target_date에 대한 기준 가격 찾기
  #   # direction='backward'는 target_date와 같거나 그 이전의 가장 최근 날짜를 찾음
  #   merged = pd.merge_asof(
  #       left=lookup_df,
  #       right=base_prices_df,
  #       left_on='target_date',
  #       right_index=True,
  #       direction='backward'
  #   )
  #   # 인덱스를 원래 DataFrame과 맞춤
  #   merged.index = df.index
  #   base_price = merged['Base_Price']
  #
  #   # 조회 기간 이전이라 데이터가 없는 경우(NaN), 첫날 종가로 대체
  #   base_price.fillna(first_day_close, inplace=True)
  #
  #   # 수익률 계산
  #   df[return_col] = df['Close'] / base_price - 1

  df['Weighted_Return'] = (df['Return_1M'] * 0.4 +
                           df['Return_3M'] * 0.3 +
                           df['Return_6M'] * 0.2 +
                           df['Return_12M'] * 0.1)
  return df


def calculate_relative_strength(df):
  # KOSDAQ GLOBAL → KOSDAQ 병합
  # df['Market_Group'] = df['Market'].replace('KOSDAQ GLOBAL', 'KOSDAQ')

  grouped = df.groupby([df.index])
  for period in ["1M", "3M", "6M", "12M"]:
    return_col = f'Return_{period}'
    rs_col = f'RS_{period}'

    df[rs_col] = grouped[return_col].rank(pct=True) * 98 + 1
    df[rs_col] = df[rs_col].fillna(1).astype(int).clip(1, 99)

  df['RS'] = grouped['Weighted_Return'].rank(pct=True) * 98 + 1
  df['RS'] = df['RS'].fillna(1).astype(int).clip(1, 99)

  # for period in ["1M", "3M", "6M", "12M"]:
  #   return_col = f'Return_{period}'
  #   rs_col = f'RS_{period}'
  #
  #   # 평균 대체 및 표준화
  #   df[return_col] = df.groupby('Market_Group')[return_col].transform(
  #       lambda x: x.fillna(x.mean()) if x.notna().any() else 0
  #   )
  #   df[return_col] = df.groupby('Market_Group')[return_col].transform(
  #       lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0
  #   )
  #
  #   # 순위 기반 정규화
  #   df[rs_col] = df.groupby('Market_Group')[return_col].transform(
  #       lambda x: pd.Series(rankdata(x, method='average') / len(x) * 98 + 1, index=x.index).round().astype(int)
  #   )
  #   df[rs_col] = df[rs_col].clip(1, 99)
  #
  # # Weighted_Return도 동일 처리
  # df['Weighted_Return'] = df.groupby('Market_Group')['Weighted_Return'].transform(
  #     lambda x: x.fillna(x.mean()) if x.notna().any() else 0
  # )
  # df['Weighted_Return'] = df.groupby('Market_Group')['Weighted_Return'].transform(
  #     lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0
  # )
  # df['RS'] = df.groupby('Market_Group')['Weighted_Return'].transform(
  #     lambda x: pd.Series(rankdata(x, method='average') / len(x) * 98 + 1, index=x.index).round().astype(int)
  # )
  # df['RS'] = df['RS'].clip(1, 99)

  # df = df.drop('Market_Group', axis=1)
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
    yesterday = today - timedelta(days=3)
    two_years_ago = today.year - 2
    result_file = "rs.csv"
    result_data = parallel_process_stocks(all_stocks, two_years_ago)
    # 오늘 날짜만 필터링
    result_data = result_data[result_data.index.date == yesterday.date()]

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