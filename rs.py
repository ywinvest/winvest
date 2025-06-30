import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta
from functools import partial

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
from pykrx import stock

warnings.filterwarnings('ignore')

# --- 설정값 ---
END_DATE = datetime(2025, 6, 30) # 기준일 (코드 실행 시점 기준 가장 최신 거래일로 자동 조정됨)
LOOKBACK_PERIOD = 20  # 20 거래일 전과 비교
MIN_MARCAP = 200_000_000_000 # 최소 시가총액: 2000억

# 데이터 조회 기간 설정 (여유있게)
START_DATE = END_DATE - timedelta(days=LOOKBACK_PERIOD + 30)
START_DATE_STR = START_DATE.strftime('%Y%m%d')
END_DATE_STR = END_DATE.strftime('%Y%m%d')

def filter_common_stocks(df):
  """ETN, ETF, 리츠, 선박펀드, 스팩, 우선주 등 제외"""
  exclude_pattern = r'스팩'
  df = df[~df['Name'].str.contains(exclude_pattern, na=False, regex=True)]
  # 우선주, 일부 ETN 등 제외
  df = df[~df['Code'].str.endswith(("5", "7", "9", "K", "L", "M", "N", "O"))]
  return df

def get_kospi_returns(start_str, end_str, lookback):
  """KOSPI 지수 수익률 및 전체 시가총액 수익률 계산"""
  # 1. KOSPI 지수 데이터 (수익률 기준)
  kospi_index = stock.get_index_ohlcv(start_str, end_str, "1001") # 1001: KOSPI 지수

  if len(kospi_index) < lookback + 1:
    raise ValueError(f"KOSPI 지수 데이터가 부족합니다. (필요: {lookback+1}일, 조회: {len(kospi_index)}일)")

  # iloc를 사용하여 20거래일 전 종가 계산
  price_current = kospi_index['종가'].iloc[-1]
  price_past = kospi_index['종가'].iloc[-(lookback + 1)]
  kospi_price_return = (price_current / price_past - 1) if price_past != 0 else 0

  # 실제 사용된 날짜 확인
  latest_date_dt = kospi_index.index[-1]
  past_date_dt = kospi_index.index[-(lookback + 1)]
  latest_date_str = latest_date_dt.strftime('%Y%m%d')
  past_date_str = past_date_dt.strftime('%Y%m%d')

  # 2. KOSPI 전체 시가총액 (시가총액 기준)
  marcap_current = stock.get_market_cap_by_ticker(latest_date_str, market='KOSPI')['시가총액'].sum()
  marcap_past = stock.get_market_cap_by_ticker(past_date_str, market='KOSPI')['시가총액'].sum()
  kospi_marcap_return = (marcap_current / marcap_past - 1) if marcap_past != 0 else 0

  print(f"계산 기준일: {past_date_dt.strftime('%Y-%m-%d')} -> {latest_date_dt.strftime('%Y-%m-%d')} ({lookback} 거래일)")
  print(f"KOSPI 지수 수익률: {kospi_price_return:.2%}")
  print(f"KOSPI 시총 수익률: {kospi_marcap_return:.2%}")

  return kospi_price_return, kospi_marcap_return

def calculate_rs_for_ticker(ticker, lookback, min_marcap, kospi_price_ret, kospi_marcap_ret):
  """개별 종목의 상대강도(RS) 계산 (병렬 처리를 위한 함수)"""
  try:
    # 주가(OHLCV) 및 시가총액 데이터 조회
    df_price = stock.get_market_ohlcv(START_DATE_STR, END_DATE_STR, ticker)
    df_marcap = stock.get_market_cap(START_DATE_STR, END_DATE_STR, ticker)

    # 데이터가 충분한지 확인
    if len(df_price) < lookback + 1 or len(df_marcap) < lookback + 1:
      return None

    # --- 필터링 조건 추가 ---
    # 1. 거래정지 종목 제거 (최종일 거래량 0)
    if df_price['거래량'].iloc[-1] == 0:
      return None

    # 2. 시가총액 2000억 미만 종목 제거
    marcap_current = df_marcap['시가총액'].iloc[-1]
    if marcap_current < min_marcap:
      return None
    # --- 필터링 끝 ---

    # 1. 시가총액 기준 RS 계산
    marcap_past = df_marcap['시가총액'].iloc[-(lookback + 1)]
    stock_marcap_return = (marcap_current / marcap_past - 1) if marcap_past != 0 else 0
    rs_marcap = (stock_marcap_return / kospi_marcap_ret) if kospi_marcap_ret != 0 else 0

    # 2. 수익률(주가) 기준 RS 계산
    price_current = df_price['종가'].iloc[-1]
    price_past = df_price['종가'].iloc[-(lookback + 1)]
    stock_price_return = (price_current / price_past - 1) if price_past != 0 else 0
    rs_price = (stock_price_return / kospi_price_ret) if kospi_price_ret != 0 else 0

    return {
      'Ticker': ticker,
      'Name': stock.get_market_ticker_name(ticker),
      'Stock_Marcap_Return': stock_marcap_return,
      'Stock_Price_Return': stock_price_return,
      'RS_Marcap': rs_marcap,
      'RS_Price': rs_price
    }
  except Exception:
    return None

def scale_rank(df, col_name):
  """상대강도 점수를 0-98점으로 스케일링하는 함수"""
  new_col_name = f"{col_name}_Scaled"
  rank_series = df[col_name].replace([np.inf, -np.inf], np.nan).rank(ascending=True, method='min', na_option='bottom')

  rank_min = rank_series.min()
  rank_max = rank_series.max()

  if rank_max == rank_min:
    df[new_col_name] = 98 # 단일 값일 경우 최고점 부여
  else:
    # 순위가 높을수록 높은 점수(98점)를 받도록 스케일링
    df[new_col_name] = ((rank_series - rank_min) / (rank_max - rank_min) * 98).round().astype(int)
  return df

def main():
  """메인 실행 함수"""
  start_time = time.time()

  print("1. 코스피 종목 리스트 필터링...")
  kospi_tickers = filter_common_stocks(fdr.StockListing('KOSPI'))['Code'].tolist()
  print(f"   초기 분석 대상 종목 수: {len(kospi_tickers)}")

  print("\n2. KOSPI 시장 수익률 계산...")
  try:
    kospi_price_return, kospi_marcap_return = get_kospi_returns(START_DATE_STR, END_DATE_STR, LOOKBACK_PERIOD)
  except ValueError as e:
    print(f"   오류: {e}")
    return

  print(f"\n3. {len(kospi_tickers)}개 종목 상대강도 계산 시작 (병렬 처리)...")
  print(f"   - 필터 조건: 시총 {MIN_MARCAP/100_000_000:,.0f}억원 이상, 거래정지 제외")

  results = []
  worker = partial(calculate_rs_for_ticker,
                   lookback=LOOKBACK_PERIOD,
                   min_marcap=MIN_MARCAP,
                   kospi_price_ret=kospi_price_return,
                   kospi_marcap_ret=kospi_marcap_return)

  with ProcessPoolExecutor() as executor:
    futures = {executor.submit(worker, ticker): ticker for ticker in kospi_tickers}

    for i, future in enumerate(as_completed(futures), 1):
      result = future.result()
      if result:
        results.append(result)
      print(f"\r   진행률: {i}/{len(kospi_tickers)} ({i/len(kospi_tickers):.2%})", end="")

  print("\n   모든 종목 계산 완료.")

  if not results:
    print("   유효한 결과를 생성하지 못했습니다.")
    return

  print(f"\n4. 최종 결과 집계...")
  print(f"   필터링 통과 종목 수: {len(results)}")

  result_df = pd.DataFrame(results)
  result_df = scale_rank(result_df, 'RS_Marcap')
  result_df = scale_rank(result_df, 'RS_Price')

  result_df['Kospi_Marcap_Return'] = kospi_marcap_return
  result_df['Kospi_Price_Return'] = kospi_price_return

  final_cols = [
    'Ticker', 'Name',
    'RS_Price_Scaled', 'RS_Marcap_Scaled',
    'RS_Price', 'RS_Marcap',
    'Stock_Price_Return', 'Stock_Marcap_Return',
    'Kospi_Price_Return', 'Kospi_Marcap_Return'
  ]
  result_df = result_df[final_cols]

  for col in ['Stock_Price_Return', 'Stock_Marcap_Return', 'Kospi_Price_Return', 'Kospi_Marcap_Return']:
    result_df[col] = result_df[col].apply(lambda x: f"{x:.2%}")

  result_df = result_df.sort_values(by='RS_Price_Scaled', ascending=False)

  print("\n--- 수익률 기준 상대강도(RS) 상위 10개 종목 (0~98점) ---")
  print(result_df.head(10).to_string())

  output_filename = 'kospi_relative_strength_final.csv'
  result_df.to_csv(output_filename, index=False, encoding='utf-8-sig')

  end_time = time.time()
  print(f"\n결과가 '{output_filename}' 파일로 저장되었습니다.")
  print(f"총 실행 시간: {end_time - start_time:.2f}초")

if __name__ == '__main__':
  main()