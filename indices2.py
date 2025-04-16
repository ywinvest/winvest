import pandas as pd
import pandas_ta as ta
import yfinance as yf

def calculate_indicators(df):
  """Calculate technical indicators."""
  df['RSI'] = ta.rsi(df['Close'], length=14).round(2)
  df['MA_10'] = df['Close'].rolling(window=10).mean()
  df['MA_20'] = df['Close'].rolling(window=20).mean()
  df['MA_60'] = df['Close'].rolling(window=60).mean()
  df['Bullish'] = df['Close'] > df['Open']
  df['Change_Rate'] = (df['Close'].pct_change() * 100).round(2)
  df['MA_10_Trend'] = df['MA_10'].diff().gt(0)
  df['MA_20_Trend'] = df['MA_20'].diff().gt(0)

  df['MA_10_Cross'] = (df['Close'].gt(df['MA_10'], axis=0)) & (df['Close'].shift(1).le(df['MA_10'].shift(1), axis=0))
  df['MA_20_Cross'] = (df['Close'].gt(df['MA_20'], axis=0)) & (df['Close'].shift(1).le(df['MA_20'].shift(1), axis=0))
  df['MA_60_Cross'] = (df['Close'].gt(df['MA_60'], axis=0)) & (df['Close'].shift(1).le(df['MA_60'].shift(1), axis=0))
  df['MA_10_Break'] = (df['Close'].lt(df['MA_10'], axis=0)) & (df['Close'].shift(1).ge(df['MA_10'].shift(1), axis=0))
  df['MA_20_Break'] = (df['Close'].lt(df['MA_20'], axis=0)) & (df['Close'].shift(1).ge(df['MA_20'].shift(1), axis=0))

  df.dropna(inplace=True)
  return df

def buy_condition_kospi_kosdaq(df):
  """Buy condition for KOSPI and KOSDAQ."""
  return (df['RSI'] <= 30) & (~df['Bullish']) & (df['Change_Rate'] < 0)

def sell_condition_kospi_kosdaq_partial(df):
  """Partial sell condition for KOSPI and KOSDAQ."""
  return df['MA_10_Cross']

def sell_condition_kospi_kosdaq_full(df):
  """Full sell condition for KOSPI and KOSDAQ."""
  return df['MA_20_Cross'] | df['MA_10_Break']

def buy_condition_global(df):
  """Buy condition for global indices."""
  return df['RSI'] <= 35

def backtest(data, ticker, buy_condition, sell_condition_partial=None, sell_condition_full=None):
  """Perform backtest with the specified buy and sell conditions."""
  df = calculate_indicators(data.copy())
  df['Action'] = None

  buys = df[buy_condition(df)].index
  buy_count = 0
  returns = []
  holding_periods = []

  for buy_date in buys:
    buy_count += 1
    position = df.loc[buy_date, 'Close']
    df.loc[buy_date, 'Action'] = 'Buy'

    # Subset the data to look forward from the buy date
    subsequent_data = df.loc[buy_date:]

    # Adjust sell conditions based on buy count for KOSPI and KOSDAQ
    if ticker in ["^KS11", "^KQ11"] and buy_count >= 5:
      partial_condition = lambda x: x['MA_20_Cross']
      full_condition = lambda x: x['MA_60_Cross'] | x['MA_20_Break']
    else:
      partial_condition = sell_condition_partial
      full_condition = sell_condition_full

    # Calculate partial sell dates
    sell_partial = subsequent_data[partial_condition(subsequent_data)] if partial_condition else pd.DataFrame()
    sell_date_partial = sell_partial.index[0] if not sell_partial.empty else None

    # Calculate full sell dates after partial sell
    sell_full = (
      subsequent_data.loc[sell_date_partial:] if sell_date_partial else subsequent_data
    )
    sell_full = sell_full[full_condition(sell_full)] if full_condition else pd.DataFrame()
    sell_date_full = sell_full.index[0] if not sell_full.empty else subsequent_data.index[-1]

    if sell_date_partial:
      df.loc[sell_date_partial, 'Action'] = 'Partial Sell'
      partial_return = (df.loc[sell_date_partial, 'Close'] / position - 1)
      returns.append(partial_return)
      holding_periods.append((sell_date_partial - buy_date).days)

    if sell_date_full:
      df.loc[sell_date_full, 'Action'] = 'Full Sell'
      full_return = (df.loc[sell_date_full, 'Close'] / position - 1)
      returns.append(full_return)
      holding_periods.append((sell_date_full - buy_date).days)

  avg_return = sum(returns) / len(returns) if returns else 0
  avg_holding_period = sum(holding_periods) / len(holding_periods) if holding_periods else 0

  # Save details to CSV
  df.to_csv(f'{ticker}_backtest_results.csv')

  return avg_return, avg_holding_period, buy_count

if __name__ == "__main__":
  tickers = {
    "kospi_kosdaq": ["^KS11", "^KQ11"],
    "global": ["^IXIC", "^DJI", "^GSPC", "GC=F"]
  }

  results = {}

  for market, symbols in tickers.items():
    for ticker in symbols:
      print(f"Processing {ticker}...")
      stock = yf.Ticker(ticker)
      data = stock.history(period="1y")
      if market == "kospi_kosdaq":
        avg_return, avg_holding_period, buy_count = backtest(
            data, ticker,
            buy_condition_kospi_kosdaq,
            sell_condition_partial=sell_condition_kospi_kosdaq_partial,
            sell_condition_full=sell_condition_kospi_kosdaq_full
        )
      else:
        avg_return, avg_holding_period, buy_count = backtest(
            data, ticker,
            buy_condition_global
        )

      results[ticker] = {
        "Average Return": avg_return * 100,
        "Average Holding Period": avg_holding_period,
        "Buy Count": buy_count
      }

  print("\nBacktest Results:")
  for ticker, metrics in results.items():
    print(f"{ticker}: {metrics}")
