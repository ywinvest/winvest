import concurrent.futures
import os
import time
from datetime import datetime, timedelta
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
import pandas_ta as ta
import requests
from dotenv import load_dotenv

import woo1

def calculate_indicators(df):
  # df['MA5'] = df['Close'].rolling(window=5).mean()
  # df['MA10'] = df['Close'].rolling(window=10).mean()
  df['MA20'] = df['Close'].rolling(window=20).mean()
  df['MA60'] = df['Close'].rolling(window=60).mean()
  df['MA120'] = df['Close'].rolling(window=120).mean()
  df['MA20_Cross'] = (df['Close'].gt(df['MA20'], axis=0)) & (df['Close'].shift(1).le(df['MA20'].shift(1), axis=0))
  df['MA20_Break'] = (df['Close'].lt(df['MA20'], axis=0)) & (df['Close'].shift(1).ge(df['MA20'].shift(1), axis=0))
  df['Bullish'] = df['Close'] > df['Open']
  df['Volume_Change'] = df['Volume'] / df['Volume'].shift(1) - 1
  # df['High_Change'] = (df['High'] / df['Close'].shift(1) - 1) * 100
  # df['Pre_Change'] = df['Change'].shift(1)
  # # df['Pre_Bullish'] = df['Close'].shift(1) > df['Open'].shift(1)
  # df['Pre_High_Change'] = df['High_Change'].shift(1)
  # df['Pre_Volume_Change'] = df['Volume'].shift(1) / df['Volume'].shift(2)
  # df['Crossover'] = (df['MA5'] > df['MA20']) & (df['MA5'].shift(1) <= df['MA20'].shift(1))
  # df['Crossover_Count'] = df['Crossover'].rolling(window=30, min_periods=1).sum()
  df['Pre52WeekLow'] = df['Low'].shift(1).rolling(window='365D', min_periods=1).min()
  df['Pre52WeekHigh'] = df['High'].shift(1).rolling(window='365D', min_periods=1).max()
  # 52주 신고가 돌파 여부
  is_52weekhigh_break = df['Close'] > df['Pre52WeekHigh']

  # 연속적인 신고가 돌파를 그룹화하여 첫 돌파만 선택
  # 돌파가 시작되는 지점을 그룹화 기준으로 사용
  # breaks = (~is_52weekhigh_break).cumsum()  # 돌파가 끊기는 지점으로 그룹화
  # is_first_break = is_52weekhigh_break & (~is_52weekhigh_break.shift(1).fillna(False))
  # df['First_52WeekHigh_Break'] = is_first_break.groupby(breaks).cumsum() == 1
  # df['First_52WeekHigh_Break'] = df['First_52WeekHigh_Break'].where(is_52weekhigh_break, False)
  # 52주 신고가 첫 돌파여부
  df['First_52WeekHigh_Break'] = is_52weekhigh_break & (~is_52weekhigh_break.shift(1).fillna(False))
  # 첫 돌파 이후 10일 동안 추가 돌파 무시
  # df['First_52WeekHigh_Break'] = df['First_52WeekHigh_Break'].where(
  #     ~df['First_52WeekHigh_Break'].rolling(window=10, min_periods=1).sum().shift(1).fillna(0).astype(bool),
  #     False
  # )

  # 이동평균선 추세 상승 여부 (기울기 > 0)
  df['MA20_Uptrend'] = df['MA20'] > df['MA20'].shift(1)
  df['MA60_Uptrend'] = df['MA60'] > df['MA60'].shift(1)
  df['MA120_Uptrend'] = df['MA120'] > df['MA120'].shift(1)

  # 벡터화된 연속 상승 일수 계산
  def calculate_uptrend_days_vec(uptrend_series):
    """벡터화 방식으로 연속 상승 일수를 계산"""
    # 상승 추세가 끊기는 지점을 그룹화 기준으로 사용
    breaks = (~uptrend_series).cumsum()
    # 각 그룹 내에서 연속된 True의 개수 계산
    uptrend_days = uptrend_series.groupby(breaks).cumsum()
    # 상승 추세가 아닌 경우(False)는 0으로 설정
    uptrend_days = uptrend_days.where(uptrend_series, 0)
    return uptrend_days

  # 각 MA에 대해 추세 상승 유지 일수 추가
  df['MA20_Uptrend_Days'] = calculate_uptrend_days_vec(df['MA20_Uptrend'])
  df['MA60_Uptrend_Days'] = calculate_uptrend_days_vec(df['MA60_Uptrend'])
  df['MA120_Uptrend_Days'] = calculate_uptrend_days_vec(df['MA120_Uptrend'])

  # df['MA20_Gap'] = df['Close']/df['MA20'] - 1
  return df

def buy_condition(df):
  # 벡터화된 연산 사용
  conditions = pd.Series(True, index=df.index)
  # conditions &= (df['MA60_Uptrend'])
  # conditions &= (df['MA120_Uptrend'])
  # conditions &= (df['MA20_Cross'])
  conditions &= (df['Pre52WeekHigh'] != 0)
  conditions &= (df['Close'] > df['Pre52WeekHigh'])
  conditions &= (df['First_52WeekHigh_Break'])
  conditions &= (df['MA20_Uptrend'] == True)
  conditions &= (df['MA60_Uptrend'] == True)
  conditions &= (df['MA120_Uptrend'] == True)
  conditions &= (df['Change'] < 0.295)
  conditions &= (df['Volume'] > 0)
  conditions &= (df['Volume'].shift(1) > 0)
  conditions &= (df['MA120_Uptrend_Days'] < 400) # 120일 상승 추세 장기 연속 제외
  conditions &= ((df['Close'] - df['Open'])/df['Close'] > -0.05) # 긴 음봉 제외
  # conditions &= (df['MA20_Gap'] < 0.3)
  return conditions

# 매도 조건 함수들
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
  ticker = row['Code']
  name = row['Name']
  marcap = row['Marcap']
  market = row['Market']
  listing_date = row['ListingDate']  # all_stocks에서 상장일 가져오기
  try:
    # 종목 데이터 가져오기
    df = fdr.DataReader(ticker, "2014")

    # 상장일 이전 데이터 제거
    if not pd.isna(listing_date):
      df = df[df.index >= listing_date]

    # 상장일 이후 데이터가 없으면 처리 중단
    if df.empty:
      print(f"No data after listing date for {ticker}")
      return None

    df = calculate_indicators(df)

    # 매수 조건에 해당하는 데이터 필터링
    buys = df[buy_condition(df)]
    buys = buys[~buys.index.year.isin([2014])]  # 2014년 데이터 제외

    # NEW LOGIC: 이전 거래의 매도일을 추적하기 위한 변수
    prev_sell_date = pd.Timestamp.min
    # NEW LOGIC: 아직 매도하지 않은 상태에서 발생한 매수 신호를 제거하기 위한 리스트
    buys_to_remove = []

    if not buys.empty:
      for buy_date in buys.index:
        # NEW LOGIC: 현재 매수 날짜가 이전 매도 날짜보다 이전이거나 같으면, 아직 포지션 보유중이므로 매수 불가
        if buy_date <= prev_sell_date:
          buys_to_remove.append(buy_date)  # 제거할 매수 신호로 추가
          continue  # 다음 신호로 넘어감

        df['Buy'] = buys.loc[buy_date, 'Close']
        buy_date_idx = df.index.get_loc(buy_date)
        data_1 = df.iloc[buy_date_idx + 1:]

        buy_price = df.loc[buy_date, 'Buy']
        current_price = df['Close'].iloc[-1]
        pre_52weekhigh = df.loc[buy_date, 'Pre52WeekHigh']
        take_profit_price = buy_price * 1.3
        # stop_loss1_price = buy_price * 0.84
        stop_loss2_price = buy_price * 0.92

        sell_date = None
        sell_price = None

        if not sell_date:
          if not data_1.empty:
            # 각 조건이 처음 발생하는 날짜 찾기
            # take_profit = data_1[data_1['Close'] >= take_profit_price]
            take_profit = data_1[
              (data_1['Close'] >= take_profit_price) &
              (data_1['Close'] < data_1['MA20']) &
              (data_1['MA20_Uptrend'] == False) &
              (data_1['Bullish'] == False) &
              (data_1['Change'] < -0.01)]
            # stop_loss1 = data_1[data_1['Low'] < stop_loss1_price]
            stop_loss2 = data_1[data_1['Close'] < stop_loss2_price]
            # stop_loss = data_1[(data_1['Close'] < data_1['MA20']) & (data_1['Volume_Change'] > 1)]

            # 각 조건의 첫 발생일 저장 (발생하지 않으면 None)
            take_profit_date = take_profit.index[0] if not take_profit.empty else None
            # stop_loss1_date = stop_loss1.index[0] if not stop_loss1.empty else None
            stop_loss2_date = stop_loss2.index[0] if not stop_loss2.empty else None

            # 발생한 날짜들 중 가장 빠른 날짜와 해당 조건 찾기
            valid_dates = [(d, 'take') for d in [take_profit_date] if d is not None] + \
                          [(d, 'stop2') for d in [stop_loss2_date] if d is not None]

            if valid_dates:
              earliest_date, condition = min(valid_dates, key=lambda x: x[0])

              if condition == 'take':
                sell_date = earliest_date
                sell_price = data_1.loc[earliest_date, 'Close']
              # elif condition == 'stop1':
              #   sell_date = earliest_date
              #   sell_price = stop_loss1_price
              elif condition == 'stop2':
                sell_date = earliest_date
                sell_price = data_1.loc[earliest_date, 'Close']
              else:  # condition == 'stop'
                sell_date = earliest_date
                sell_price = data_1.loc[earliest_date, 'Close']

        # 매도 정보를 해당 행에 추가
        buys.loc[buy_date, 'Ticker'] = ticker
        buys.loc[buy_date, 'Name'] = name
        buys.loc[buy_date, 'Marcap'] = marcap
        buys.loc[buy_date, 'Buy_Date'] = buy_date
        buys.loc[buy_date, 'Buy_Price'] = buy_price
        buys.loc[buy_date, 'Sell_Date'] = sell_date
        buys.loc[buy_date, 'Sell_Price'] = sell_price

        # 보유기간 계산 (영업일 기준)
        if sell_date:
          buys.loc[buy_date, 'Holding_Days'] = calculate_trading_days(df, buy_date, sell_date)
          # 매도 수익률 계산 (%)
          buys.loc[buy_date, 'Return'] = ((sell_price / buy_price) - 1)
          if market == 'KOSPI':
            buys.loc[buy_date, 'Index_RSI'] = kospi.loc[sell_date, 'RSI']
          elif market == 'KOSDAQ':
            buys.loc[buy_date, 'Index_RSI'] = kosdaq.loc[sell_date, 'RSI']
          # NEW LOGIC: 다음 매수 가능일을 위해 prev_sell_date 업데이트
          prev_sell_date = sell_date
        else:
          # NEW LOGIC: 매도되지 않았다면, 이 종목에 대한 모든 향후 매수를 막기 위해 prev_sell_date를 최대로 설정
          prev_sell_date = pd.Timestamp.max
          buys.loc[buy_date, 'Holding_Days'] = None
          buys.loc[buy_date, 'Return'] = ((current_price / buy_price) - 1)
          # buys.loc[buy_date, 'Return'] = None
          buys.loc[buy_date, 'Index_RSI'] = None

        buys.loc[buy_date, 'Current_Price'] = current_price

      # NEW LOGIC: 루프가 끝난 후, 보유 중 발생한 모든 매수 신호를 결과에서 제거
      if buys_to_remove:
        buys.drop(buys_to_remove, inplace=True)

      # 유효한 거래가 있는 경우에만 DataFrame을 반환
      return buys if not buys.empty else None
    return None
  except Exception as e:
    print(f"Error processing {ticker}: {e}")
    return None

if __name__ == "__main__":
  start_time = time.time()

  # .env 파일 로드
  load_dotenv()

  try:
    # delisting = fdr.StockListing('KRX-DELISTING') # 3천+ 종목 - 상장폐지 종목 전체
    # admin = fdr.StockListing('KRX-ADMIN') # 50+ 종목 - KRX 관리종목

    # 종목 리스트 가져오기 및 필터링
    all_stocks = pd.concat([
      woo1.filter_common_stocks(fdr.StockListing('KOSPI')),
      woo1.filter_common_stocks(fdr.StockListing('KOSDAQ'))
    ], ignore_index=True)

    # 상장일 정보 가져오기
    krx_desc = fdr.StockListing('KRX-DESC', "2014")[['Code', 'ListingDate']]
    all_stocks = all_stocks.merge(krx_desc, on='Code', how='left')

    kospi = fdr.DataReader('KS11')
    kospi['RSI'] = ta.rsi(kospi['Close'], length=14)

    kosdaq = fdr.DataReader('KQ11')
    kosdaq['RSI'] = ta.rsi(kosdaq['Close'], length=14)

    result_file = "woo4_backtest_results.csv"

    # 병렬 처리로 데이터 분석
    result_data = parallel_process_stocks(all_stocks)
    result_data.to_csv(result_file, index=False, encoding='utf-8-sig')
  except Exception as e:
    print(f"Error in main execution: {e}")

  finally:
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"총 소요시간: {elapsed_time:.2f}초")
