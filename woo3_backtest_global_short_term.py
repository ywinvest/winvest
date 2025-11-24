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
    return (df['RSI'] <= 35) & (~df['Bullish']) & (df['Change_Rate'] < 0)

def sell_condition_partial(df):
  """Partial sell condition for global indices."""
  return df['MA_10_Cross']

def sell_condition_full(df):
  """Full sell condition for global indices."""
  return df['MA_20_Cross'] | df['MA_10_Break']

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
  last_buy_price = None  # 이전 매수 가격 추적
  group_consecutive_buys = 0  # 그룹의 연속매수회수 (첫 매수에서 계산)

  for buy_date in buys.index:
    if sell_date_full is not None and buy_date > sell_date_full:
      current_buy_group_flag = False
      last_buy_price = None  # 새 그룹 시작시 초기화
      group_consecutive_buys = 0  # 새 그룹 시작시 초기화

    # 현재 매수가 그룹 내 첫 매수인지 확인
    is_first_buy = not current_buy_group_flag

    # 첫 매수가 아닌 경우, 이전 매수보다 종가가 낮은지 확인
    if not is_first_buy:
      current_price = df.loc[buy_date, 'Close']
      if last_buy_price is None or current_price >= last_buy_price:
        continue  # 이전 매수보다 가격이 높거나 같으면 매수하지 않음

    position = df.loc[buy_date, 'Close']
    df.loc[buy_date, 'Action'] = 'Buy'
    last_buy_price = position  # 현재 매수 가격 저장

    # Check RSI and adjust position size
    rsi = df.loc[buy_date, 'RSI']
    if rsi <= 20:
      position_size = 3
    elif rsi <= 30:
      position_size = 2
    else:
      position_size = 1

    df.loc[buy_date:, 'Weight'] += position_size

    # Subset the data to look forward from the buy date
    subsequent_data = df.loc[buy_date:]

    # 첫 매수인 경우에만 연속매수회수 계산
    if is_first_buy:
      # 1단계: 기본 매도 조건(10일선 돌파)으로 일단 계산
      temp_sell_partial = subsequent_data[sell_condition_partial(subsequent_data)] if sell_condition_partial else pd.DataFrame()
      temp_sell_date = temp_sell_partial.index[0] if not temp_sell_partial.empty else None

      if temp_sell_date:
        group_data = subsequent_data.loc[:temp_sell_date]
      else:
        group_data = subsequent_data

      # 그룹 내 잠재적 매수 신호 찾기
      potential_buys = group_data[buy_condition(group_data, is_first_buy=False)]

      # 이전 매수보다 낮은 가격인 경우만 카운트 (break 없이 계속 체크)
      consecutive_buys = 1  # 첫 매수 포함
      temp_last_price = position

      for idx in potential_buys.index:
        if idx > buy_date:
          current_close = group_data.loc[idx, 'Close']
          if current_close < temp_last_price:
            consecutive_buys += 1
            temp_last_price = current_close  # 실제 매수한 가격으로 업데이트

      # 2단계: 연속매수가 5회 이상이면 20일선 돌파 기준으로 재계산
      if consecutive_buys >= 5:
        temp_sell_ma20 = subsequent_data[subsequent_data['MA_20_Cross']]
        temp_sell_date_ma20 = temp_sell_ma20.index[0] if not temp_sell_ma20.empty else None

        if temp_sell_date_ma20:
          group_data = subsequent_data.loc[:temp_sell_date_ma20]
        else:
          group_data = subsequent_data

        # 20일선 기준으로 다시 계산
        potential_buys = group_data[buy_condition(group_data, is_first_buy=False)]

        consecutive_buys = 1
        temp_last_price = position

        for idx in potential_buys.index:
          if idx > buy_date:
            current_close = group_data.loc[idx, 'Close']
            if current_close < temp_last_price:
              consecutive_buys += 1
              temp_last_price = current_close

      group_consecutive_buys = consecutive_buys

    # 모든 매수에 첫 매수에서 계산한 연속매수회수 할당
    df.loc[buy_date, 'Consecutive Buys'] = group_consecutive_buys

    # 연속매수회수가 3회 이상인 경우 매도 조건 변경
    if group_consecutive_buys >= 5:
      current_buy_group_flag = True

      # 20일선 돌파시 전체 매도 (부분매도 없음)
      override_condition = lambda d: d['MA_20_Cross']

      sell_full_new = subsequent_data[override_condition(subsequent_data)]
      sell_date_full = sell_full_new.index[0] if not sell_full_new.empty else None
      sell_date_partial = None  # 부분매도 없음

    else:
      current_buy_group_flag = True

      # 기본 매도 로직
      temp_sell_partial = subsequent_data[sell_condition_partial(subsequent_data)] if sell_condition_partial else pd.DataFrame()
      sell_date_partial = temp_sell_partial.index[0] if not temp_sell_partial.empty else None

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

  today = datetime.today()
  ten_years_ago = today.year - 10

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