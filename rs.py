import pandas as pd
import fdr
from pykrx import stock
from datetime import datetime, timedelta
import numpy as np
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import partial
import time

warnings.filterwarnings('ignore')

# --- 설정값 ---
# 기준일은 가장 최신 거래일로 자동 조정됩니다.
END_DATE = datetime.now()
LOOKBACK_PERIOD = 20  # 20 거래일 전과 비교
MIN_MARCAP = 200_000_000_000 # 최소 시가총액: 2000억

# 데이터 조회 기간 설정 (여유있게)
START_DATE = END_DATE - timedelta(days=LOOKBACK_PERIOD + 45)
START_DATE_STR = START_DATE.strftime('%Y%m%d')
END_DATE_STR = END_DATE.strftime('%Y%m%d')

def filter_common_stocks(df):
  """ETN, ETF, 선박펀드, 스팩, 우선주 등 제외"""
  df = df[~df['Name'].str.contains('스팩', na=False, regex=True)]
  # 우선주, 일부 ETN/ETF 등 제외
  df = df[~df['Code'].str.endswith(("5", "7", "9", "K", "L", "M", "N", "O"))]
  return df

def get_market_returns(start_str, end_str, lookback, market_name, index_code):
  """지정된 시장의 지수 수익률 및 전체 시가총액 수익률 계산"""
  print(f"\n>> {market_name} 시장 수익률 계산 중...")

  # 1. 시장 지수 데이터 (수익률 기준)
  market_index = stock.get_index_ohlcv(start_str, end_str, index_code)

  if len(market_index) < lookback + 1:
    raise ValueError(f"{market_name} 지수 데이터가 부족합니다. (필요: {lookback+1}일, 조회: {len(market_index)}일)")

  # iloc를 사용하여 20거래일 전 종가 계산
  price_current = market_index['종가'].iloc[-1]
  price_past = market_index['종가'].iloc[-(lookback + 1)]
  market_price_return = (price_current / price_past - 1) if price_past != 0 else 0

  # 실제 사용된 날짜 확인
  latest_date_dt = market_index.index[-1]
  past_date_dt = market_index.index[-(lookback + 1)]
  latest_date_str = latest_date_dt.strftime('%Y%m%d')
  past_date_str = past_date_dt.strftime('%Y%m%d')

  # 2. 시장 전체 시가총액 (시가총액 기준)
  marcap_current = stock.get_market_cap_by_ticker(latest_date_str, market=market_name)['시가총액'].sum()
  marcap_past = stock.get_market_cap_by_ticker(past_date_str, market=market_name)['시가총액'].sum()
  market_marcap_return = (marcap_current / marcap_past - 1) if marcap_past != 0 else 0

  print(f"   계산 기준일: {past_date_dt.strftime('%Y-%m-%d')} -> {latest_date_dt.strftime('%Y-%m-%d')} ({lookback} 거래일)")
  print(f"   {market_name} 지수 수익률: {market_price_return:.2%}")
  print(f"   {market_name} 시총 수익률: {market_marcap_return:.2%}")

  return market_price_return, market_marcap_return

def calculate_rs_for_ticker(ticker, market_name, lookback, min_marcap, market_price_ret, market_marcap_ret):
  """개별 종목의 상대강도(RS) 계산 (병렬 처리를 위한 함수)"""
  try:
    df_price = stock.get_market_ohlcv(START_DATE_STR, END_DATE_STR, ticker)
    df_marcap = stock.get_market_cap(START_DATE_STR, END_DATE_STR, ticker)

    if len(df_price) < lookback + 1 or len(df_marcap) < lookback + 1:
      return None

    if df_price['거래량'].iloc[-1] == 0:
      return None

    marcap_current = df_marcap['시가총액'].iloc[-1]
    if marcap_current < min_marcap:
      return None

    marcap_past = df_marcap['시가총액'].iloc[-(lookback + 1)]
    stock_marcap_return = (marcap_current / marcap_past - 1) if marcap_past != 0 else 0
    rs_marcap = (stock_marcap_return / market_marcap_ret) if market_marcap_ret != 0 else 0

    price_current = df_price['종가'].iloc[-1]
    price_past = df_price['종가'].iloc[-(lookback + 1)]
    stock_price_return = (price_current / price_past - 1) if price_past != 0 else 0
    rs_price = (stock_price_return / market_price_ret) if market_price_ret != 0 else 0

    return {
      'Ticker': ticker,
      'Market': market_name,
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
    df[new_col_name] = 98
  else:
    df[new_col_name] = ((rank_series - rank_min) / (rank_max - rank_min) * 98).round().astype(int)
  return df

def process_market(market_name, index_code):
  """시장별로 RS를 계산하는 전체 프로세스"""
  print(f"\n{'='*50}\n{market_name} 시장 분석 시작\n{'='*50}")

  print(f"1. {market_name} 종목 리스트 필터링...")
  tickers = filter_common_stocks(fdr.StockListing(market_name))['Code'].tolist()
  print(f"   초기 분석 대상 종목 수: {len(tickers)}")

  market_price_return, market_marcap_return = get_market_returns(START_DATE_STR, END_DATE_STR, LOOKBACK_PERIOD, market_name, index_code)

  print(f"\n3. {len(tickers)}개 종목 상대강도 계산 시작 (병렬 처리)...")
  print(f"   - 필터 조건: 시총 {MIN_MARCAP/100_000_000:,.0f}억원 이상, 거래정지 제외")

  results = []
  worker = partial(calculate_rs_for_ticker,
                   market_name=market_name,
                   lookback=LOOKBACK_PERIOD,
                   min_marcap=MIN_MARCAP,
                   market_price_ret=market_price_return,
                   market_marcap_ret=market_marcap_return)

  with ProcessPoolExecutor() as executor:
    futures = {executor.submit(worker, ticker): ticker for ticker in tickers}

    for i, future in enumerate(as_completed(futures), 1):
      result = future.result()
      if result:
        results.append(result)
      print(f"\r   진행률: {i}/{len(tickers)} ({i/len(tickers):.2%})", end="")

  print(f"\n   {market_name} 계산 완료. 필터링 통과 종목 수: {len(results)}")
  return results

def main():
  """메인 실행 함수"""
  start_time = time.time()

  # 코스피, 코스닥 시장별로 각각 처리
  kospi_results = process_market('KOSPI', '1001')
  kosdaq_results = process_market('KOSDAQ', '2001')

  # 결과 통합
  all_results = kospi_results + kosdaq_results

  if not all_results:
    print("\n분석할 유효한 종목이 없습니다.")
    return

  print(f"\n{'='*50}\n전체 시장 결과 통합 및 랭킹\n{'='*50}")
  print(f"총 분석 종목 수 (KOSPI+KOSDAQ): {len(all_results)}")

  # 전체 통합 데이터프레임 생성
  result_df = pd.DataFrame(all_results)

  # 전체 종목 대상으로 랭킹 및 스케일링
  result_df = scale_rank(result_df, 'RS_Marcap')
  result_df = scale_rank(result_df, 'RS_Price')

  # 최종 결과 정리
  final_cols = [
    'Ticker', 'Name', 'Market',
    'RS_Price_Scaled', 'RS_Marcap_Scaled',
    'RS_Price', 'RS_Marcap',
    'Stock_Price_Return', 'Stock_Marcap_Return',
  ]
  result_df = result_df[final_cols]

  # 수익률 포맷팅
  for col in ['Stock_Price_Return', 'Stock_Marcap_Return']:
    result_df[col] = result_df[col].apply(lambda x: f"{x:.2%}")

  # 최종 정렬 (수익률 기준 RS 점수)
  result_df = result_df.sort_values(by='RS_Price_Scaled', ascending=False)

  print("\n--- 전체 시장 통합 상대강도(RS) 상위 20개 종목 (0~98점) ---")
  print(result_df.head(20).to_string())

  # 결과 저장
  output_filename = 'korea_market_relative_strength.csv'
  result_df.to_csv(output_filename, index=False, encoding='utf-8-sig')

  end_time = time.time()
  print(f"\n결과가 '{output_filename}' 파일로 저장되었습니다.")
  print(f"총 실행 시간: {end_time - start_time:.2f}초")

if __name__ == '__main__':
  main()