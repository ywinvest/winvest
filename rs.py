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
END_DATE = datetime(2025, 6, 27)
LOOKBACK_PERIOD = 20  # 20 거래일 전과 비교
START_DATE = END_DATE - timedelta(days=LOOKBACK_PERIOD + 20) # 데이터 조회 여유 기간 설정

# 날짜 형식 변환
END_DATE_STR = END_DATE.strftime('%Y%m%d')
START_DATE_STR = START_DATE.strftime('%Y%m%d')

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
    raise ValueError("KOSPI 지수 데이터가 부족합니다.")

  # iloc를 사용하여 20거래일 전 종가 계산
  price_current = kospi_index['종가'].iloc[-1]
  price_past = kospi_index['종가'].iloc[-(lookback + 1)]
  kospi_price_return = (price_current / price_past - 1) if price_past != 0 else 0

  # 실제 사용된 날짜 확인
  latest_date = kospi_index.index[-1].strftime('%Y%m%d')
  past_date = kospi_index.index[-(lookback + 1)].strftime('%Y%m%d')

  # 2. KOSPI 전체 시가총액 (시가총액 기준)
  marcap_current = stock.get_market_cap_by_ticker(latest_date, market='KOSPI')['시가총액'].sum()
  marcap_past = stock.get_market_cap_by_ticker(past_date, market='KOSPI')['시가총액'].sum()
  kospi_marcap_return = (marcap_current / marcap_past - 1) if marcap_past != 0 else 0

  print(f"계산 기준일: {past_date} -> {latest_date} ({lookback} 거래일)")
  print(f"KOSPI 지수 수익률: {kospi_price_return:.2%}")
  print(f"KOSPI 시총 수익률: {kospi_marcap_return:.2%}")

  return kospi_price_return, kospi_marcap_return

def calculate_rs_for_ticker(ticker, lookback, kospi_price_ret, kospi_marcap_ret):
  """개별 종목의 상대강도(RS) 계산 (병렬 처리를 위한 함수)"""
  try:
    # 시가총액 데이터 조회
    df_marcap = stock.get_market_cap(START_DATE_STR, END_DATE_STR, ticker)
    # 주가(OHLCV) 데이터 조회
    df_price = stock.get_market_ohlcv(START_DATE_STR, END_DATE_STR, ticker)

    # 데이터가 충분한지 확인 (최소 lookback + 1일)
    if len(df_marcap) < lookback + 1 or len(df_price) < lookback + 1:
      return None

    # 1. 시가총액 기준 RS 계산
    marcap_current = df_marcap['시가총액'].iloc[-1]
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
  except Exception as e:
    # print(f"Error processing {ticker}: {e}") # 에러가 많을 경우 주석 처리
    return None

def scale_rank(df, col_name):
  """상대강도 점수를 0-99점으로 스케일링하는 함수"""
  new_col_name = f"{col_name}_Scaled"
  # inf 값을 NaN으로 변환 후 순위 계산
  rank_series = df[col_name].replace([np.inf, -np.inf], np.nan).rank(ascending=True, method='min', na_option='bottom')

  # 스케일링
  rank_min = rank_series.min()
  rank_max = rank_series.max()

  if rank_max == rank_min:
    df[new_col_name] = 99
  else:
    # 순위가 높을수록 높은 점수(99점)를 받도록 스케일링
    df[new_col_name] = ((rank_series - rank_min) / (rank_max - rank_min) * 99).round().astype(int)
  return df

def main():
  """메인 실행 함수"""
  start_time = time.time()

  # 1. 코스피 상장 종목 리스트 필터링
  print("코스피 종목 리스트를 가져오는 중...")
  kospi_tickers = filter_common_stocks(fdr.StockListing('KOSPI'))['Code'].tolist()
  print(f"분석 대상 종목 수: {len(kospi_tickers)}")

  # 2. 코스피 수익률 계산 (시장 전체)
  print("\nKOSPI 시장 수익률 계산 중...")
  try:
    kospi_price_return, kospi_marcap_return = get_kospi_returns(START_DATE_STR, END_DATE_STR, LOOKBACK_PERIOD)
  except ValueError as e:
    print(f"오류: {e}")
    return

  # 3. 병렬 처리를 이용한 종목별 데이터 계산
  print(f"\n{len(kospi_tickers)}개 종목에 대한 상대강도 계산 시작 (병렬 처리)...")
  results = []
  # functools.partial를 사용하여 worker 함수에 고정 인자 전달
  worker = partial(calculate_rs_for_ticker,
                   lookback=LOOKBACK_PERIOD,
                   kospi_price_ret=kospi_price_return,
                   kospi_marcap_ret=kospi_marcap_return)

  # ProcessPoolExecutor를 사용하여 병렬 작업 실행
  with ProcessPoolExecutor() as executor:
    # future 객체들을 생성
    futures = {executor.submit(worker, ticker): ticker for ticker in kospi_tickers}

    # 작업 완료 시 결과 리스트에 추가
    for i, future in enumerate(as_completed(futures)):
      result = future.result()
      if result:
        results.append(result)
      # 진행 상황 표시
      print(f"\r진행률: {i+1}/{len(kospi_tickers)} ({((i+1)/len(kospi_tickers))*100:.2f}%)", end="")

  print("\n모든 종목 계산 완료.")

  if not results:
    print("유효한 결과를 생성하지 못했습니다.")
    return

  # 4. 결과 데이터프레임 생성 및 스케일링
  result_df = pd.DataFrame(results)
  result_df = scale_rank(result_df, 'RS_Marcap')
  result_df = scale_rank(result_df, 'RS_Price')

  # KOSPI 수익률 추가
  result_df['Kospi_Marcap_Return'] = kospi_marcap_return
  result_df['Kospi_Price_Return'] = kospi_price_return

  # 5. 최종 결과 정리 및 출력
  final_cols = [
    'Ticker', 'Name',
    'RS_Price_Scaled', 'RS_Marcap_Scaled',
    'RS_Price', 'RS_Marcap',
    'Stock_Price_Return', 'Stock_Marcap_Return',
    'Kospi_Price_Return', 'Kospi_Marcap_Return'
  ]
  result_df = result_df[final_cols]

  # 수익률을 퍼센트로 변환하여 보기 좋게 만듦
  for col in ['Stock_Price_Return', 'Stock_Marcap_Return', 'Kospi_Price_Return', 'Kospi_Marcap_Return']:
    result_df[col] = result_df[col].apply(lambda x: f"{x:.2%}")

  # 수익률 기준 상대강도 점수(RS_Price_Scaled)로 정렬
  result_df = result_df.sort_values(by='RS_Price_Scaled', ascending=False)

  print("\n--- 수익률 기준 상대강도(RS) 상위 10개 종목 ---")
  print(result_df.head(10).to_string())

  # 6. 결과 저장
  output_filename = 'kospi_traderlion_relative_strength.csv'
  result_df.to_csv(output_filename, index=False, encoding='utf-8-sig')

  end_time = time.time()
  print(f"\n결과가 '{output_filename}' 파일로 저장되었습니다.")
  print(f"총 실행 시간: {end_time - start_time:.2f}초")

if __name__ == '__main__':
  main()