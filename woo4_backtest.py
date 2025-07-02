import concurrent.futures
import time
from datetime import datetime
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv

import woo1
import woo4


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
  df['Pre39WeekHigh'] = df['High'].shift(1).rolling(window='273D', min_periods=1).max()

  df['Pre52WeekHigh'] = df['High'].shift(1).rolling(window='364D', min_periods=1).max()

  # 39주 신고가 돌파 여부
  is_39weekhigh_break = df['Close'] > df['Pre39WeekHigh']
  # 52주 신고가 돌파 여부
  is_52weekhigh_break = df['Close'] > df['Pre52WeekHigh']

  # 연속적인 신고가 돌파를 그룹화하여 첫 돌파만 선택
  # 돌파가 시작되는 지점을 그룹화 기준으로 사용
  # breaks = (~is_52weekhigh_break).cumsum()  # 돌파가 끊기는 지점으로 그룹화
  # is_first_break = is_52weekhigh_break & (~is_52weekhigh_break.shift(1).fillna(False))
  # df['First_52WeekHigh_Break'] = is_first_break.groupby(breaks).cumsum() == 1
  # df['First_52WeekHigh_Break'] = df['First_52WeekHigh_Break'].where(is_52weekhigh_break, False)
  # 39주 신고가 첫 돌파여부
  # df['First_39WeekHigh_Break'] = is_39weekhigh_break & (~is_39weekhigh_break.shift(1, fill_value=False))
  # 52주 신고가 첫 돌파여부
  # df['First_52WeekHigh_Break'] = is_52weekhigh_break & (~is_52weekhigh_break.shift(1, fill_value=False))
  # 첫 돌파 이후 10일 동안 추가 돌파 무시
  # df['First_52WeekHigh_Break'] = df['First_52WeekHigh_Break'].where(
  #     ~df['First_52WeekHigh_Break'].rolling(window=10, min_periods=1).sum().shift(1).fillna(0).astype(bool),
  #     False
  # )

  def calculate_stable_high_break(df, window_days='364D', cooldown_days=10):
    """
    고가 돌파 후 종가가 마감하지 못했을 때, 특정 기간 기준가를 고정하여 돌파 신호를 계산합니다.
    (This is the improved function)

    Args:
        df (pd.DataFrame): 'High', 'Close' 컬럼을 포함한 데이터프레임
        window_days (str): 신고가 판단을 위한 기간 (예: '364D'는 52주)
        cooldown_days (int): 기준가를 고정할 거래일 수

    Returns:
        pd.Series: 돌파 신호가 발생한 날을 True로 표시하는 boolean 시리즈
    """
    # 1. 각 거래일 직전까지의 'window_days' 기간 동안의 최고가를 계산합니다.
    # shift(1)을 사용하여 당일의 고가는 포함하지 않습니다.
    prev_period_high = df['High'].shift(1).rolling(window=window_days, min_periods=1).max()

    # 2. '실패한 돌파'를 감지합니다. (고가는 넘었지만, 종가는 넘지 못함)
    is_failed_breakout = (df['High'] > prev_period_high) & (df['Close'] <= prev_period_high)

    # 3. '실패한 돌파'가 발생한 날의 'prev_period_high' 값을 저장합니다. 이 값이 '고정 기준가'가 됩니다.
    # where 함수를 사용해 조건이 False인 날은 NaN으로 처리합니다.
    freeze_high_marker = prev_period_high.where(is_failed_breakout)

    # 4. '고정 기준가'를 'cooldown_days' 동안 유지합니다.
    # ffill(limit=...)을 사용해 NaN 값을 직전의 유효한 값으로 채웁니다.
    # limit는 채울 수 있는 최대 연속 NaN 개수를 의미하며, cooldown_days-1로 설정하여 총 10일간 값이 유지되도록 합니다.
    frozen_high_series = freeze_high_marker.ffill(limit=cooldown_days - 1)

    # 5. 최종 '돌파 기준가'를 결정합니다.
    # '고정 기준가'가 존재하면(NaN이 아니면) 그 값을 사용하고, 아니면 일반 'prev_period_high'를 사용합니다.
    # combine_first는 frozen_high_series의 non-NaN 값을 우선적으로 사용하고, 나머지를 prev_period_high로 채웁니다.
    baseline_high = frozen_high_series.combine_first(prev_period_high)

    # 6. '돌파 기준가'를 처음으로 상향 돌파하는 날을 찾습니다.
    # 현재 종가가 기준가를 넘고, 바로 전날 종가는 기준가보다 아래여야 합니다.
    is_breakout_day = (df['Close'] > baseline_high) & (df['Close'].shift(1) <= baseline_high.shift(1))

    return is_breakout_day.fillna(False)

  # 52주 신고가 돌파 (안정된 기준 사용)
  df['First_52WeekHigh_Break'] = calculate_stable_high_break(df, window_days='364D', cooldown_days=10)
  # 39주 신고가 돌파 (273일 기준)
  df['First_39WeekHigh_Break'] = calculate_stable_high_break(df, window_days='273D', cooldown_days=10)

  # 이동평균선 추세 상승 여부 (기울기 > 0)
  # df['MA20_Uptrend'] = df['MA20'] > df['MA20'].shift(1)
  # df['MA60_Uptrend'] = df['MA60'] > df['MA60'].shift(1)
  # df['MA120_Uptrend'] = df['MA120'] > df['MA120'].shift(1)
  df['MA20_Slope'] = df['MA20'].pct_change(fill_method=None)
  df['MA60_Slope'] = df['MA60'].pct_change(fill_method=None)
  df['MA120_Slope'] = df['MA120'].pct_change(fill_method=None)

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
  df['MA20_Uptrend_Days'] = calculate_uptrend_days_vec(df['MA20_Slope'] > 0)
  df['MA60_Uptrend_Days'] = calculate_uptrend_days_vec(df['MA60_Slope'] > 0)
  df['MA120_Uptrend_Days'] = calculate_uptrend_days_vec(df['MA120_Slope'] > 0)

  df['MA20_Gap'] = df['Close'] / df['MA20'] - 1

  df['Return_1M'] = df['Close'] / df['Close'].shift(20) - 1
  df['Return_3M'] = df['Close'] / df['Close'].shift(60) - 1
  df['Return_6M'] = df['Close'] / df['Close'].shift(120) - 1
  return df

def buy_condition(df):
  # 벡터화된 연산 사용
  conditions = pd.Series(True, index=df.index)
  # conditions &= (df['MA60_Uptrend'])
  # conditions &= (df['MA120_Uptrend'])
  # conditions &= (df['MA20_Cross'])
  # conditions &= (df['Close'] > df['Pre52WeekHigh'])
  kospi_or_kosdaq_global = df['Market'].isin(['KOSPI', 'KOSDAQ GLOBAL'])
  kosdaq = df['Market'] == 'KOSDAQ'

  conditions &= (
      ((kospi_or_kosdaq_global) & df['Pre52WeekHigh'].ne(0) & df['First_52WeekHigh_Break']) |
      ((kosdaq) & df['Pre39WeekHigh'].ne(0) & df['First_39WeekHigh_Break'])
  )
  # conditions &= (df['MA20_Uptrend'] == True)
  # conditions &= (df['MA60_Uptrend'] == True)
  # conditions &= (df['MA120_Uptrend'] == True)
  conditions &= (df['MA20_Slope'] > 0)
  conditions &= (df['MA60_Slope'] > 0)
  conditions &= (df['MA120_Slope'] > 0)
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

    df = calculate_indicators(df)

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
  buy_signals = df[buy_condition(df)].copy()
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
            second_sell_dates = after_partial_sell_data.index[second_sell_cond]
            second_stop_loss_dates = after_partial_sell_data.index[after_partial_sell_data['Close'] < stop_loss_price]

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
    krx_desc = fdr.StockListing('KRX-DESC', "2014")[['Code', 'ListingDate']]
    all_stocks = all_stocks.merge(krx_desc, on='Code', how='left')

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
