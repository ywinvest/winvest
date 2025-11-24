import json
import os
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd
import numpy as np

import indicators

INIT_RSI = 35

# 초기 필터링용 조건
def buy_condition_broad(df):
  """Broad buy condition for global indices (RSI <= 35)."""
  return (df['RSI'] <= INIT_RSI) & (~df['Bullish']) & (df['Change_Rate'] < 0)

def sell_condition_partial(df):
  """Partial sell condition for global indices (10-MA Cross)."""
  return df['MA_10_Cross']

def sell_condition_full(df):
  """
  [NOTE]: 이 전역 함수는 더 이상 5회 미만 그룹의 전체 매도 조건으로 직접 사용되지 않습니다.
  """
  return df['MA_20_Cross'] | df['MA_10_Break']

def backtest(data, ticker, buy_condition, sell_condition_partial, sell_condition_full):
  """Backtest with dynamic Full Sell logic based on consecutive buy count."""
  df = indicators.calculate_indicators(data.copy())

  df['Weight'] = 0.0

  buys = df[buy_condition(df)]

  returns = []
  holding_periods = []
  buy_count = 0

  current_buy_group_flag = False
  sell_date_full = buys.index[0] if not buys.empty else None
  last_buy_price = None

  current_group_buy_count = 0
  group_consecutive_buys = 0

  group_partial_returns = []
  group_full_returns = []
  group_sell_date_partial = None
  group_sell_date_full = None

  # --- 내부 함수: 연속 매수 횟수 미리 계산 ---
  def count_potential_buys(start_date, end_date, initial_price):
    if end_date:
      group_data = df.loc[start_date:end_date]
    else:
      group_data = df.loc[start_date:]

    potential_candidates = group_data[buy_condition(group_data)]

    c_buys = 1
    temp_last_price = initial_price
    next_buy_order = 2

    for idx in potential_candidates.index:
      if idx <= start_date:
        continue
      current_close = group_data.loc[idx, 'Close']
      current_rsi = group_data.loc[idx, 'RSI']

      if current_close >= temp_last_price:
        continue
      threshold = 30 if next_buy_order == 2 else INIT_RSI
      if current_rsi <= threshold:
        c_buys += 1
        temp_last_price = current_close
        next_buy_order += 1
    return c_buys

  # --- 그룹 정산(Flush) 함수 ---
  def flush_group_metrics():
    nonlocal group_partial_returns, group_full_returns, group_sell_date_partial, group_sell_date_full

    if group_sell_date_partial and group_partial_returns:
      avg_partial = sum(group_partial_returns) / len(group_partial_returns)
      df.loc[group_sell_date_partial, 'Partial Return'] = avg_partial

    if group_sell_date_full and group_full_returns:
      avg_full = sum(group_full_returns) / len(group_full_returns)
      df.loc[group_sell_date_full, 'Full Return'] = avg_full

    group_partial_returns = []
    group_full_returns = []
    group_sell_date_partial = None
    group_sell_date_full = None

  for buy_date in buys.index:
    # 새 그룹 시작 여부 확인
    if sell_date_full is not None and buy_date > sell_date_full:
      # 이전 그룹 정산(Flush) 수행
      flush_group_metrics()

      # 상태 초기화
      current_buy_group_flag = False
      last_buy_price = None
      current_group_buy_count = 0
      group_consecutive_buys = 0

    is_first_buy = not current_buy_group_flag

    # 가격 조건 확인
    if not is_first_buy:
      current_price = df.loc[buy_date, 'Close']
      if last_buy_price is None or current_price >= last_buy_price:
        continue

    # RSI 조건 검증
    current_rsi = df.loc[buy_date, 'RSI']
    required_rsi = INIT_RSI
    if is_first_buy:
      required_rsi = INIT_RSI
    else:
      check_order = current_group_buy_count + 1
      if check_order == 2:
        required_rsi = 30
      else:
        required_rsi = INIT_RSI

    if current_rsi > required_rsi:
      continue

    # --- 매수 실행 ---
    position = df.loc[buy_date, 'Close']
    df.loc[buy_date, 'Action'] = 'Buy'
    last_buy_price = position
    current_group_buy_count += 1
    buy_count += 1

    if current_rsi <= 20:
      position_size = 3
    elif current_rsi <= 30:
      position_size = 2
    else:
      position_size = 1

    df.loc[buy_date, 'Weight'] = position_size

    subsequent_data = df.loc[buy_date:]

    # 그룹 초기 설정
    if is_first_buy:
      current_buy_group_flag = True

      temp_sell_partial = subsequent_data[sell_condition_partial(subsequent_data)] if sell_condition_partial else pd.DataFrame()
      temp_sell_date = temp_sell_partial.index[0] if not temp_sell_partial.empty else None

      consecutive_buys = count_potential_buys(buy_date, temp_sell_date, position)

      if consecutive_buys >= 5:
        temp_sell_ma20 = subsequent_data[subsequent_data['MA_20_Cross']]
        temp_sell_date_ma20 = temp_sell_ma20.index[0] if not temp_sell_ma20.empty else None
        consecutive_buys = count_potential_buys(buy_date, temp_sell_date_ma20, position)

      group_consecutive_buys = consecutive_buys

    df.loc[buy_date, 'Consecutive Buys'] = group_consecutive_buys

    # 매도 로직 결정
    if group_consecutive_buys >= 5:
      # 5회 이상: Partial Sell 없음, Full Sell = MA_20_Cross
      override_condition = lambda d: d['MA_20_Cross']
      sell_full_new = subsequent_data[override_condition(subsequent_data)]
      sell_date_full = sell_full_new.index[0] if not sell_full_new.empty else None
      sell_date_partial = None
    else:
      # 1. Partial Sell은 MA_10_Cross로 유지
      temp_sell_partial = subsequent_data[sell_condition_partial(subsequent_data)] if sell_condition_partial else pd.DataFrame()
      sell_date_partial = temp_sell_partial.index[0] if not temp_sell_partial.empty else None

      # 2. Full Sell 조건은 MA_10_Cross로 변경
      full_sell_condition_lt_5 = lambda d: d['MA_10_Cross']

      # 부분 매도일 이후부터 Full Sell 조건 탐색 시작 (부분 매도일 포함)
      sell_full = subsequent_data.loc[sell_date_partial:] if sell_date_partial else subsequent_data

      # 변경된 조건 적용 (MA_10_Cross)
      sell_full = sell_full[full_sell_condition_lt_5(sell_full)] if full_sell_condition_lt_5 else pd.DataFrame()
      sell_date_full = sell_full.index[0] if not sell_full.empty else None


    remaining_position = position_size

    # --- 부분 매도 처리 ---
    if sell_date_partial:
      df.loc[sell_date_partial, 'Action'] = 'Partial Sell'
      partial_price = df.loc[sell_date_partial, 'Close']
      partial_return = (partial_price / position - 1) * position_size

      df.loc[buy_date, 'Partial Return'] = partial_return
      returns.append(partial_return)
      holding_periods.append((sell_date_partial - buy_date).days)

      # Weight 누적
      sell_amount = position_size / 2
      df.loc[sell_date_partial, 'Weight'] += sell_amount
      remaining_position -= sell_amount

      # 그룹 통계 수집
      group_partial_returns.append(partial_return)
      group_sell_date_partial = sell_date_partial

    # --- 전체 매도 처리 ---
    if sell_date_full:
      df.loc[sell_date_full, 'Action'] = 'Full Sell'
      full_price = df.loc[sell_date_full, 'Close']
      full_return = (full_price / position - 1) * position_size

      df.loc[buy_date, 'Full Return'] = full_return
      returns.append(full_return)
      holding_periods.append((sell_date_full - buy_date).days)

      # Weight 누적
      df.loc[sell_date_full, 'Weight'] += remaining_position

      # 그룹 통계 수집
      group_full_returns.append(full_return)
      group_sell_date_full = sell_date_full

  # 루프 종료 후 마지막 그룹 정산(Flush)
  flush_group_metrics()

  avg_return = sum(returns) / len(returns) if returns else 0
  avg_holding_period = sum(holding_periods) / len(holding_periods) if holding_periods else 0

  output_dir = 'global/buy-and-sell'
  os.makedirs(output_dir, exist_ok=True)

  df.to_csv(os.path.join(output_dir, f'{ticker}_backtest_results.csv'))

  return avg_return, avg_holding_period, buy_count


if __name__ == "__main__":
  with open('config-woo3.json', 'r') as config_file:
    config = json.load(config_file)

  tickers = config["global"]["tickers"]
  results = {}

  end_date = datetime.today()
  start_date = end_date - timedelta(days=30 * 365)

  end_date_str = end_date.strftime('%Y-%m-%d')
  start_date_str = start_date.strftime('%Y-%m-%d')

  for ticker, name in tickers.items():
    print(f"Processing {ticker} ({name})...")
    data = fdr.DataReader(ticker, start=start_date_str, end=end_date_str)

    if data.empty:
      print(f"No data found for {ticker}, skipping.")
      continue

    avg_return, avg_holding_period, buy_count = backtest(
        data, ticker,
        buy_condition_broad,
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
    print(f"{name}: Average Return: {metrics['Average Return']:.2f}%, Average Holding Period: {metrics['Average Holding Period']:.2f} days, Buy Count: {metrics['Buy Count']}")