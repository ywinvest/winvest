import json
import os
from datetime import datetime, timedelta

import FinanceDataReader as fdr

import indicators


def buy_condition(df):
  """Buy condition for global indices."""
  return (df['RSI'] <= 35) & (~df['Bullish']) & (df['Change_Rate'] < 0)
  # return (df['Close'].lt(df['MA_10'], axis=0))
  # return df['Close'].eq(df['Close'])


def backtest(data, ticker, buy_condition):
  """Perform backtest with the specified buy and sell conditions."""
  df = indicators.calculate_indicators(data.copy())

  buys = df[buy_condition(df)]

  returns = []
  holding_periods = []
  buy_count = len(buys)

  for buy_date in buys.index:
    position = df.loc[buy_date, 'Close']
    df.loc[buy_date, 'Action'] = 'Buy'

    # Subset the data to look forward from the buy date
    subsequent_data = df.loc[buy_date:]

    sell_date_full = subsequent_data.index[-1]

    df.loc[sell_date_full, 'Action'] = 'Full Sell'
    full_return = (df.loc[sell_date_full, 'Close'] / position - 1)
    returns.append(full_return)
    holding_periods.append((sell_date_full - buy_date).days)

  avg_return = sum(returns) / len(returns) if returns else 0
  avg_holding_period = sum(holding_periods) / len(
    holding_periods) if holding_periods else 0

  output_dir = 'global/buy-and-hold'
  os.makedirs(output_dir, exist_ok=True)

  df.to_csv(os.path.join(output_dir, f'{ticker}_backtest_results.csv'))

  return avg_return, avg_holding_period, buy_count


if __name__ == "__main__":
  with open('config-woo2.json', 'r') as config_file:
    config = json.load(config_file)

  tickers = config["global"]["tickers"]

  results = {}

  today = datetime.today()
  ten_years_ago = today.year - 10

  # 오늘 날짜와 10년 전 날짜를 'YYYY-MM-DD' 형식으로 계산
  end_date = datetime.today()
  start_date = end_date - timedelta(days=10 * 365)  # 근사치로 10년 계산

  # 날짜를 문자열 형식으로 변환
  end_date_str = end_date.strftime('%Y-%m-%d')
  start_date_str = start_date.strftime('%Y-%m-%d')

  for ticker, name in tickers.items():
    print(f"Processing {ticker} ({name})...")
    # data = fdr.DataReader(ticker, start=start_date_str, end=end_date_str)
    data = fdr.DataReader(ticker)

    if data.empty:
      print(f"No data found for {ticker}, skipping.")
      continue

    avg_return, avg_holding_period, buy_count = backtest(
        data, ticker,
        buy_condition
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
