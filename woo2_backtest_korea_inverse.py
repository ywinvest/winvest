import json
import os
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd

import indicators


def buy_condition(df):
  """Buy condition for korea indicies."""
  return (df['RSI'] > 70) & \
    (df['Bullish']) & \
    (df['Change_Rate'] > 0) & \
    (((df['High'] - df['Close']) / df['Close']) > 0.0001)
    # (df['Is_Option_Week'])

def sell_condition_partial(df):
  """Partial sell condition for korea indicies."""
  return df['MA_10_Break']

def sell_condition_full(df):
  """Full sell condition for korea indicies."""
  return df['MA_20_Break'] | df['MA_10_Cross']

def is_option_expiration_week(date):
  """Checks if a given date is in the week of the second Thursday of the month."""
  # Find the first day of the month
  first_day_of_month = date.replace(day=1)
  # Find the first Thursday of the month
  first_thursday = first_day_of_month + timedelta(days=((3 - first_day_of_month.weekday() + 7) % 7))
  # Calculate the second Thursday (option expiration day)
  second_thursday = first_thursday + timedelta(days=7)

  # Determine the start (Monday) and end (Friday) of the expiration week
  start_of_week = second_thursday - timedelta(days=second_thursday.weekday())
  end_of_week = start_of_week + timedelta(days=4)

  return start_of_week <= date <= end_of_week

def backtest(data, ticker, buy_condition, sell_condition_partial, sell_condition_full):
  """Perform backtest with the specified buy and sell conditions."""
  df = indicators.calculate_indicators(data.copy())

  df['Is_Option_Week'] = df.index.to_series().apply(is_option_expiration_week)

  buys = df[buy_condition(df)]

  returns = []
  holding_periods = []
  buy_count = len(buys)

  current_buy_group_flag = False
  sell_date_full = buys.index[0]

  for buy_date in buys.index:
    if sell_date_full is not None and buy_date > sell_date_full:
      current_buy_group_flag = False

    position = df.loc[buy_date, 'Close']
    df.loc[buy_date, 'Action'] = 'Buy'

    position_size = 1  # 그 외의 경우 1배

    # Subset the data to look forward from the buy date
    subsequent_data = df.loc[buy_date:]

    sell_date_partial = None

    # Calculate partial sell dates
    if not current_buy_group_flag:
      sell_partial = subsequent_data[sell_condition_partial(subsequent_data)] if sell_condition_partial else pd.DataFrame()
      sell_date_partial = sell_partial.index[0] if not sell_partial.empty else None

    # Determine consecutive buys in the current group
    if sell_date_partial:
      group_data = subsequent_data.loc[:sell_date_partial]
      consecutive_buys = len(group_data[buy_condition(group_data)])
      # if consecutive_buys >= 3:
      #   current_buy_group_flag = True
      df.loc[buy_date, 'Consecutive Buys'] = consecutive_buys


    # Adjust sell conditions based on the flag
    # if current_buy_group_flag:
    #   sell_condition_partial = lambda df: df['MA_20_Cross']
    #   sell_condition_full = lambda df: df['MA_20_Cross']
    # else:
    #   sell_condition_partial = lambda df: df['MA_10_Cross']
    #   sell_condition_full = lambda df: df['MA_20_Cross'] | df['MA_10_Break']

    # Calculate partial sell dates
    sell_partial = subsequent_data[sell_condition_partial(subsequent_data)] if sell_condition_partial else pd.DataFrame()
    sell_date_partial = sell_partial.index[0] if not sell_partial.empty else None

    # Calculate full sell dates after partial sell
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

    if sell_date_full:
      df.loc[sell_date_full, 'Action'] = 'Full Sell'
      full_price = df.loc[sell_date_full, 'Close']
      full_return = (full_price / position - 1) * position_size
      df.loc[buy_date, 'Full Return'] = full_return
      returns.append(full_return)
      holding_periods.append((sell_date_full - buy_date).days)

  avg_return = sum(returns) / len(returns) if returns else 0
  avg_holding_period = sum(holding_periods) / len(
    holding_periods) if holding_periods else 0

  output_dir = 'korea/buy-and-sell/inverse'
  os.makedirs(output_dir, exist_ok=True)

  df.to_csv(os.path.join(output_dir, f'{ticker}_backtest_results.csv'))

  return avg_return, avg_holding_period, buy_count


if __name__ == "__main__":
  with open('config-woo2.json', 'r') as config_file:
    config = json.load(config_file)

  tickers = config["korea"]["tickers"]

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
