import json
import os
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd

import indicators


def buy_condition(df, is_first_buy=True):
  """Buy condition for global indices."""
  if is_first_buy:
    return (df['RSI'] <= 35) & (~df['Bullish']) & (df['Change_Rate'] < 0)
  else:
    return (df['RSI'] <= 30) & (~df['Bullish']) & (df['Change_Rate'] < 0)

def sell_condition_partial(df):
  """Partial sell condition for global indices."""
  return df['MA_10_Cross']

def sell_condition_full(df):
  """Full sell condition for global indices."""
  return df['MA_20_Cross'] | df['MA_10_Break']
  # return df['MA_10_Cross']

def backtest(data, ticker, buy_condition, sell_condition_partial, sell_condition_full):
  """Perform backtest with the specified buy and sell conditions."""
  df = indicators.calculate_indicators(data.copy())

  df['Weight'] = 0.0

  buys = df[buy_condition(df)]

  returns = []
  holding_periods = []
  buy_count = len(buys)

  current_buy_group_flag = False
  sell_date_full = buys.index[0]

  for buy_date in buys.index:
    if sell_date_full is not None and buy_date > sell_date_full:
      current_buy_group_flag = False

    # 현재 매수가 그룹 내 첫 매수인지 확인
    is_first_buy = not current_buy_group_flag

    # 첫 매수가 아닌 경우, RSI 30 이하 조건 확인
    if not is_first_buy:
      # 단일 행에 대한 조건 체크를 수정
      row_data = df.loc[[buy_date]]
      if not buy_condition(row_data, is_first_buy=False).any():
        continue

    position = df.loc[buy_date, 'Close']
    df.loc[buy_date, 'Action'] = 'Buy'

    # Check RSI and adjust position size
    rsi = df.loc[buy_date, 'RSI']
    if rsi <= 25:
      position_size = 3  # RSI 25 이하일 때 3배
    elif rsi <= 30:
      position_size = 2  # RSI 30 이하일 때 2배
    else:
      position_size = 1  # 그 외의 경우 1배

    df.loc[buy_date:, 'Weight'] += position_size

    # Subset the data to look forward from the buy date
    subsequent_data = df.loc[buy_date:]

    # 1. 일단 기본 반매도 조건(MA10 Cross)으로 시점을 계산
    temp_sell_partial = subsequent_data[sell_condition_partial(subsequent_data)] if sell_condition_partial else pd.DataFrame()
    sell_date_partial = temp_sell_partial.index[0] if not temp_sell_partial.empty else None

    consecutive_buys = 0

    # 2. 해당 기간 내 연속 매수 횟수 카운트
    if sell_date_partial:
      group_data = subsequent_data.loc[:sell_date_partial]
      consecutive_buys = len(group_data[buy_condition(group_data, is_first_buy=False)])

      # 현재 매수 건을 포함하여 카운트 조정 (로직에 따라 필요시)
      if rsi <= 30:
        df.loc[buy_date, 'Consecutive Buys'] = consecutive_buys
      else:
        df.loc[buy_date, 'Consecutive Buys'] = consecutive_buys + 1 # 첫 매수 포함 등 로직 보정

    # -------------------------------------------------------
    # [수정된 부분] 연속 매수가 3회 이상인 경우 매도 조건 변경 로직
    # -------------------------------------------------------
    if consecutive_buys >= 3:
      current_buy_group_flag = True

      # 반매도, 전체매도 모두 20일선 돌파(MA_20_Cross)로 변경
      override_condition = lambda d: d['MA_20_Cross']

      # 반매도 시점 재계산 (MA20)
      sell_partial_new = subsequent_data[override_condition(subsequent_data)]
      sell_date_partial = sell_partial_new.index[0] if not sell_partial_new.empty else None

      # 전체 매도 시점 재계산 (MA20 - 반매도와 동일하거나 그 이후)
      if sell_date_partial:
        sell_full_new = subsequent_data.loc[sell_date_partial:]
        sell_full_new = sell_full_new[override_condition(sell_full_new)]
        sell_date_full = sell_full_new.index[0] if not sell_full_new.empty else None
      else:
        sell_date_full = None

    else:
      # 3회 미만인 경우 기존 로직 유지 (기본 반매도 날짜 유지)
      current_buy_group_flag = True if consecutive_buys > 0 else False # 플래그 관리

      # 전체 매도 시점 계산 (기본 조건: MA20 Cross or MA10 Break)
      sell_full = (
        subsequent_data.loc[sell_date_partial:] if sell_date_partial else subsequent_data
      )
      sell_full = sell_full[sell_condition_full(sell_full)] if sell_condition_full else pd.DataFrame()
      sell_date_full = sell_full.index[0] if not sell_full.empty else None

    if sell_date_partial:
      df.loc[sell_date_partial, 'Action'] = 'Partial Sell'
      partial_price = df.loc[sell_date_partial, 'Close']
      partial_return = (partial_price / position - 1) * position_size
      df.loc[buy_date, 'Partial Return'] = partial_return
      returns.append(partial_return)
      holding_periods.append((sell_date_partial - buy_date).days)

      current_weight = df.loc[sell_date_partial, 'Weight']
      df.loc[sell_date_partial:, 'Weight'] = current_weight / 2

    if sell_date_full:
      df.loc[sell_date_full, 'Action'] = 'Full Sell'
      full_price = df.loc[sell_date_full, 'Close']
      full_return = (full_price / position - 1) * position_size
      df.loc[buy_date, 'Full Return'] = full_return
      returns.append(full_return)
      holding_periods.append((sell_date_full - buy_date).days)

      current_weight = df.loc[sell_date_full, 'Weight']
      df.loc[sell_date_full:, 'Weight'] -= current_weight

  avg_return = sum(returns) / len(returns) if returns else 0
  avg_holding_period = sum(holding_periods) / len(
    holding_periods) if holding_periods else 0

  output_dir = 'global/buy-and-sell'
  os.makedirs(output_dir, exist_ok=True)

  df.to_csv(os.path.join(output_dir, f'{ticker}_backtest_results.csv'))

  return avg_return, avg_holding_period, buy_count


if __name__ == "__main__":
  with open('config-woo3.json', 'r') as config_file:
    config = json.load(config_file)

  tickers = config["global"]["tickers"]

  results = {}

  today = datetime.today()
  ten_years_ago = today.year - 10

  # 오늘 날짜와 10년 전 날짜를 'YYYY-MM-DD' 형식으로 계산
  end_date = datetime.today()
  start_date = end_date - timedelta(days=30 * 365)  # 근사치로 10년 계산

  # 날짜를 문자열 형식으로 변환
  end_date_str = end_date.strftime('%Y-%m-%d')
  start_date_str = start_date.strftime('%Y-%m-%d')

  for ticker, name in tickers.items():
    print(f"Processing {ticker} ({name})...")
    data = fdr.DataReader(ticker, start=start_date_str, end=end_date_str)
    # data = fdr.DataReader(ticker)

    if data.empty:
      print(f"No data found for {ticker}, skipping.")
      continue

    avg_return, avg_holding_period, buy_count = backtest(
        data, ticker,
        buy_condition,
        sell_condition_partial=sell_condition_partial,
        sell_condition_full=sell_condition_full
    )

    results[name] = {
      "Average Return": avg_return * 100,
      "Average Holding Period": avg_holding_period,
      "Buy Count": buy_count
    }

  print("\nBacktest Results:")
  for name, metrics in results.items():
    print(
      f"{name}: Average Return: {metrics['Average Return']:.2f}%, Average Holding Period: {metrics['Average Holding Period']:.2f} days, Buy Count: {metrics['Buy Count']}")
