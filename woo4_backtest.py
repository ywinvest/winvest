import concurrent.futures
import io
import time
from datetime import datetime
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
import pandas_ta as ta
import requests
from dotenv import load_dotenv

import woo1
import woo4


def calculate_trading_days(df, start_date, end_date):
  """
  실제 거래일 기준으로 보유기간을 계산하는 함수

  Args:
      df (pandas.DataFrame): 주가 데이터
      start_date (datetime): 시작일
      end_date (datetime): 종료일

  Returns:
      int: 실제 거래일 수
  """
  if pd.isna(end_date):
    return None

  # start_date와 end_date 사이의 실제 거래일만 필터링
  trading_days = df.loc[start_date:end_date].index
  return len(trading_days) - 1  # 매수일 제외

def parallel_process_stocks(all_stocks):
  process_func = partial(process_stock)
  results = []

  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(process_func, row) for _, row in all_stocks.iterrows()]
    for future in concurrent.futures.as_completed(futures):
      result = future.result()
      if result is not None:
        results.append(result)

  return pd.concat(results) if results else pd.DataFrame()

def process_stock(row):
  code = row['Code']
  name = row['Name']
  marcap = row['Marcap']
  market = row['Market']
  listing_date = row['ListingDate']  # all_stocks에서 상장일 가져오기

  try:
    # 종목 데이터 가져오기
    df = fdr.DataReader(code, "2014")

    # 상장일 이전 데이터 제거
    if not pd.isna(listing_date):
      df = df[df.index >= listing_date]

    # 상장일 이후 데이터가 없으면 처리 중단
    if df.empty:
      print(f"No data after listing date for {code}")
      return None

    df = woo4.calculate_indicators(df)

    if not df.empty:
      df['Code'] = code
      df['Name'] = name
      df['Marcap'] = marcap
      df['Market'] = market
      return df
    return None
  except Exception as e:
    print(f"Error processing {code}: {e}")
    return None

def buy_and_sell(df, kospi_df, kosdaq_df):
  # 매수 신호가 발생한 모든 거래를 가져옵니다.
  buy_signals = df[woo4.buy_condition(df)].copy()
  buy_signals = buy_signals[buy_signals.index >= '2015-06-15']

  if buy_signals.empty:
    return pd.DataFrame()

  trades = []
  # 종목별로 순회하며 처리합니다.
  for code, stock_group in df.groupby('Code'):
    # 해당 종목의 매수 신호만 필터링합니다.
    stock_buy_signals = buy_signals[buy_signals['Code'] == code]
    if stock_buy_signals.empty:
      continue

    prev_sell_date = pd.Timestamp.min

    for buy_date, buy_row in stock_buy_signals.iterrows():
      # 이전 거래가 끝나기 전의 신호는 무시합니다.
      if buy_date <= prev_sell_date:
        continue

      # --- RSI 및 시가총액 조건 검사 (수정된 로직) ---
      market = buy_row['Market']
      index_rsi = None
      index_ma60_up = None

      rsi_source_df = None
      if market == 'KOSPI':
        rsi_source_df = kospi_df
      elif market in ['KOSDAQ', 'KOSDAQ GLOBAL']:
        rsi_source_df = kosdaq_df

      if rsi_source_df is not None and buy_date in rsi_source_df.index:
        rsi_val = rsi_source_df.loc[buy_date, 'RSI']
        index_rsi = rsi_val.iloc[0] if isinstance(rsi_val, pd.Series) else rsi_val
        ma60_up_val = rsi_source_df.loc[buy_date, 'MA60_Up']
        index_ma60_up = ma60_up_val.iloc[0] if isinstance(ma60_up_val, pd.Series) else ma60_up_val

      # if index_rsi is None or index_rsi > 80 or index_rsi < 30:
      #   continue

      buy_price = buy_row['Close']
      current_price = stock_group['Close'].iloc[-1]
      estimated_marcap = buy_row['Marcap'] * (buy_price / current_price)

      if estimated_marcap < 2e+11:
        continue

      # 매수일 이후의 데이터만 사용합니다.
      trade_data = stock_group.loc[buy_date:].iloc[1:]

      # 매도 조건 초기화
      sell_date, sell_price = None, None
      full_sell_date, full_sell_price = None, None

      if not trade_data.empty:
        # 익절/손절 가격 정의
        take_profit_price = buy_price * 1.3
        stop_loss_price = buy_price * 0.92
        trailing_stop_loss_price = buy_price * 1.1

        # 1차 매도 (분할 익절 또는 전체 손절)
        take_profit_dates = trade_data.index[trade_data['High'] >= take_profit_price]
        stop_loss_dates = trade_data.index[trade_data['Close'] < stop_loss_price]

        first_take_profit_date = take_profit_dates[0] if not take_profit_dates.empty else None
        first_stop_loss_date = stop_loss_dates[0] if not stop_loss_dates.empty else None

        # 어떤 매도 조건이 먼저 충족되었는지 확인
        if first_stop_loss_date and (first_take_profit_date is None or first_stop_loss_date < first_take_profit_date):
          # 손절 조건이 먼저 발생하면 즉시 전체 매도
          sell_date = first_stop_loss_date
          sell_price = trade_data.loc[sell_date, 'Close']
          full_sell_date, full_sell_price = sell_date, sell_price
        elif first_take_profit_date:
          # 익절 조건이 먼저 발생하면 1차 분할 매도
          sell_date = first_take_profit_date
          sell_price = take_profit_price

          # 2차 매도 (남은 물량) 조건 탐색
          after_partial_sell_data = trade_data.loc[sell_date:].iloc[1:]
          if not after_partial_sell_data.empty:
            # 2차 매도 조건: 20일선 하향 돌파 등
            second_sell_cond = (
                (after_partial_sell_data['Close'] < after_partial_sell_data['MA20']) &
                (after_partial_sell_data['MA20_Slope'] < 0) &
                (after_partial_sell_data['MA20_Gap'] < -0.05) &
                (after_partial_sell_data['Bullish'] == False) &
                (after_partial_sell_data['Change'] < -0.02)
            )
            second_stop_loss_cond = (
                (after_partial_sell_data['Close'] < trailing_stop_loss_price)
            )
            second_sell_dates = after_partial_sell_data.index[second_sell_cond]
            second_stop_loss_dates = after_partial_sell_data.index[second_stop_loss_cond]

            final_sell_date = second_sell_dates[0] if not second_sell_dates.empty else None
            final_stop_loss_date = second_stop_loss_dates[0] if not second_stop_loss_dates.empty else None

            if final_stop_loss_date and (final_sell_date is None or final_stop_loss_date < final_sell_date):
              full_sell_date = final_stop_loss_date
              full_sell_price = after_partial_sell_data.loc[full_sell_date, 'Close']
            elif final_sell_date:
              full_sell_date = final_sell_date
              full_sell_price = after_partial_sell_data.loc[full_sell_date, 'Close']

      # 최종 거래 결과 기록
      trade_info = buy_row.to_dict()
      trade_info.update({
        'Buy_Date': buy_date,
        'Buy_Price': buy_price,
        'Estimated_Marcap': estimated_marcap,
        'Index_RSI': index_rsi,
        'Index_MA60_Up': index_ma60_up,
        'Sell_Date': sell_date,
        'Sell_Price': sell_price,
        'Full_Sell_Date': full_sell_date,
        'Full_Sell_Price': full_sell_price,
        'Return': (sell_price / buy_price - 1) if sell_price else (current_price / buy_price - 1),
        'Full_Return': (full_sell_price / buy_price - 1) if full_sell_price else ((current_price / buy_price - 1) if sell_date else None),
        'Holding_Days': calculate_trading_days(stock_group, buy_date, sell_date),
        'Full_Holding_Days': calculate_trading_days(stock_group, buy_date, full_sell_date),
      })
      trades.append(trade_info)

      # 다음 거래가 이 거래의 종료일 이후에 시작되도록 설정
      if full_sell_date:
        prev_sell_date = full_sell_date
      else: # 매도가 일어나지 않았다면 이 종목은 더 이상 거래하지 않음
        prev_sell_date = pd.Timestamp.max

  return pd.DataFrame(trades)

if __name__ == "__main__":
  start_time = time.time()

  # .env 파일 로드
  load_dotenv()

  try:
    # delisting = fdr.StockListing('KRX-DELISTING') # 3천+ 종목 - 상장폐지 종목 전체
    # admin = fdr.StockListing('KRX-ADMIN') # 50+ 종목 - KRX 관리종목

    kospi = fdr.StockListing('KOSPI')
    kosdaq = fdr.StockListing('KOSDAQ')
    all_stocks = pd.concat([kospi, kosdaq], ignore_index=True)

    # 상장일 정보 가져오기
    # krx_desc = fdr.StockListing('KRX-DESC', "2014")[['Code', 'ListingDate']]
    url = 'http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'
    headers = {
      'User-Agent': 'Chrome/78.0.3904.87 Safari/537.36',
      'Referer': 'http://data.krx.co.kr/'
    }
    r = requests.get(url, headers)
    dfs = pd.read_html(io.StringIO(r.text), header=0)
    df_listing = dfs[0]
    cols_ren = {'종목코드': 'Code', '상장일': 'ListingDate'}
    df_listing = df_listing.rename(columns = cols_ren)
    df_listing['Code'] = df_listing['Code'].apply(lambda x: x.zfill(6))
    df_listing['ListingDate'] = pd.to_datetime(df_listing['ListingDate'])

    all_stocks = all_stocks.merge(df_listing, on='Code', how='left')

    kospi = fdr.DataReader('KS11')
    kospi['RSI'] = ta.rsi(kospi['Close'], length=14)
    kospi['MA60_Up'] = kospi['Close'] > kospi['Close'].rolling(window=60).mean()

    kosdaq = fdr.DataReader('KQ11')
    kosdaq['RSI'] = ta.rsi(kosdaq['Close'], length=14)
    kosdaq['MA60_Up'] = kosdaq['Close'] > kosdaq['Close'].rolling(window=60).mean()

    result_file = "woo4_backtest_results.csv"

    # 병렬 처리로 데이터 분석
    result_data = parallel_process_stocks(all_stocks)
    result_data = woo4.calculate_relative_strength(result_data)
    filtered_data = woo1.filter_common_stocks(result_data)
    result_data = buy_and_sell(filtered_data, kospi, kosdaq)
    # final_data = result_data[buy_condition(result_data)]
    result_data.to_csv(result_file, index=False, encoding='utf-8-sig')
  except Exception as e:
    print(f"Error in main execution: {e}")

  finally:
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"총 소요시간: {elapsed_time:.2f}초")
