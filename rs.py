import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta
from functools import partial

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
from pykrx import stock
from tqdm import tqdm

warnings.filterwarnings('ignore')

# --- 설정값 ---
# 기준일은 가장 최신 거래일로 자동 조정됩니다.
END_DATE = datetime.now()
LOOKBACK_PERIOD = 20  # 20 거래일 전과 비교

# 데이터 조회 기간 설정 (여유있게)
START_DATE = END_DATE - timedelta(days=LOOKBACK_PERIOD + 45)
START_DATE_STR = START_DATE.strftime('%Y%m%d')
END_DATE_STR = END_DATE.strftime('%Y%m%d')

def filter_common_stocks(df):
  """필터링 제거 - 모든 종목 포함"""
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

def check_trading_halt(ticker):
  """거래정지 여부 확인"""
  try:
    # 최근 거래일 데이터 조회
    recent_data = stock.get_market_ohlcv(END_DATE_STR, END_DATE_STR, ticker)
    if len(recent_data) == 0:
      return True  # 데이터가 없으면 거래정지로 간주

    # 거래량이 0이면 거래정지로 간주
    if recent_data['거래량'].iloc[-1] == 0:
      return True

    return False
  except:
    return True  # 오류 발생시 거래정지로 간주

def calculate_rs_for_ticker(ticker, market_name, lookback, market_price_ret, market_marcap_ret):
  """개별 종목의 상대강도(RS) 계산 (병렬 처리를 위한 함수)"""
  try:
    df_price = stock.get_market_ohlcv(START_DATE_STR, END_DATE_STR, ticker)
    df_marcap = stock.get_market_cap(START_DATE_STR, END_DATE_STR, ticker)

    if len(df_price) < lookback + 1 or len(df_marcap) < lookback + 1:
      return None

    # 현재 시가총액 정보
    marcap_current = df_marcap['시가총액'].iloc[-1]

    # 거래정지 여부 확인
    is_trading_halt = df_price['거래량'].iloc[-1] == 0

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
      'Current_Marcap': marcap_current,
      'Is_Trading_Halt': is_trading_halt,
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
  print(f"   - 모든 종목 포함 (필터링 없음)")

  results = []
  worker = partial(calculate_rs_for_ticker,
                   market_name=market_name,
                   lookback=LOOKBACK_PERIOD,
                   market_price_ret=market_price_return,
                   market_marcap_ret=market_marcap_return)

  with ProcessPoolExecutor() as executor:
    futures = {executor.submit(worker, ticker): ticker for ticker in tickers}

    # tqdm을 사용한 progress bar
    with tqdm(total=len(tickers), desc=f"   {market_name} 진행", unit="종목", ncols=100) as pbar:
      for future in as_completed(futures):
        result = future.result()
        if result:
          results.append(result)
        pbar.update(1)

  print(f"\n   {market_name} 계산 완료. 분석 종목 수: {len(results)}")

  if not results:
    return pd.DataFrame()

  # 시장별 데이터프레임 생성 및 랭킹
  market_df = pd.DataFrame(results)
  market_df = scale_rank(market_df, 'RS_Marcap')
  market_df = scale_rank(market_df, 'RS_Price')

  return market_df

def format_marcap(marcap):
  """시가총액을 억원 단위로 포맷팅"""
  return f"{marcap/100_000_000:.0f}억"

def main():
  """메인 실행 함수"""
  start_time = time.time()

  # 코스피, 코스닥 시장별로 각각 처리
  kospi_df = process_market('KOSPI', '1001')
  kosdaq_df = process_market('KOSDAQ', '2001')

  if kospi_df.empty and kosdaq_df.empty:
    print("\n분석할 유효한 종목이 없습니다.")
    return

  print(f"\n{'='*50}\n시장별 결과 정리\n{'='*50}")

  # 결과 정리 함수
  def format_results(df, market_name):
    if df.empty:
      print(f"\n{market_name} 시장: 분석 결과 없음")
      return df

    print(f"\n{market_name} 시장 분석 종목 수: {len(df)}")

    # 최종 결과 정리
    final_cols = [
      'Ticker', 'Name', 'Market',
      'Current_Marcap', 'Is_Trading_Halt',
      'RS_Price_Scaled', 'RS_Marcap_Scaled',
      'RS_Price', 'RS_Marcap',
      'Stock_Price_Return', 'Stock_Marcap_Return',
    ]

    result_df = df[final_cols].copy()

    # 시가총액 포맷팅
    result_df['Current_Marcap_Formatted'] = result_df['Current_Marcap'].apply(format_marcap)

    # 수익률 포맷팅
    for col in ['Stock_Price_Return', 'Stock_Marcap_Return']:
      result_df[col] = result_df[col].apply(lambda x: f"{x:.2%}")

    # 최종 정렬 (수익률 기준 RS 점수)
    result_df = result_df.sort_values(by='RS_Price_Scaled', ascending=False)

    print(f"\n--- {market_name} 시장 상대강도(RS) 상위 20개 종목 (0~98점) ---")
    display_cols = [
      'Ticker', 'Name', 'Current_Marcap_Formatted', 'Is_Trading_Halt',
      'RS_Price_Scaled', 'RS_Marcap_Scaled', 'Stock_Price_Return', 'Stock_Marcap_Return'
    ]
    print(result_df[display_cols].head(20).to_string(index=False))

    return result_df

  # 각 시장별 결과 포맷팅 및 출력
  kospi_formatted = format_results(kospi_df, 'KOSPI')
  kosdaq_formatted = format_results(kosdaq_df, 'KOSDAQ')

  # 결과 저장
  if not kospi_formatted.empty:
    kospi_filename = 'kospi_relative_strength.csv'
    # CSV 저장용 컬럼 정리
    kospi_save_cols = [
      'Ticker', 'Name', 'Market', 'Current_Marcap', 'Is_Trading_Halt',
      'RS_Price_Scaled', 'RS_Marcap_Scaled', 'RS_Price', 'RS_Marcap',
      'Stock_Price_Return', 'Stock_Marcap_Return'
    ]
    kospi_formatted[kospi_save_cols].to_csv(kospi_filename, index=False, encoding='utf-8-sig')
    print(f"\nKOSPI 결과가 '{kospi_filename}' 파일로 저장되었습니다.")

  if not kosdaq_formatted.empty:
    kosdaq_filename = 'kosdaq_relative_strength.csv'
    # CSV 저장용 컬럼 정리
    kosdaq_save_cols = [
      'Ticker', 'Name', 'Market', 'Current_Marcap', 'Is_Trading_Halt',
      'RS_Price_Scaled', 'RS_Marcap_Scaled', 'RS_Price', 'RS_Marcap',
      'Stock_Price_Return', 'Stock_Marcap_Return'
    ]
    kosdaq_formatted[kosdaq_save_cols].to_csv(kosdaq_filename, index=False, encoding='utf-8-sig')
    print(f"KOSDAQ 결과가 '{kosdaq_filename}' 파일로 저장되었습니다.")

  end_time = time.time()
  print(f"\n총 실행 시간: {end_time - start_time:.2f}초")

if __name__ == '__main__':
  main()