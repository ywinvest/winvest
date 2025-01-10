import argparse
import json

import pandas_ta as ta
import requests
import yfinance as yf

def calculate_indicators(df, period='14'):
  try:
    if df.empty:
      print("No data available in the DataFrame")
      return None

    df['RSI'] = ta.rsi(df['Close'], length=int(period))
    df['Change_Rate'] = df['Close'].pct_change() * 100
    df['Bullish'] = df['Close'] > df['Open']

    return df
  except Exception as e:
    print(f"Error calculating indicators: {e}")
    return None

def process_and_sort_tickers(tickers):
  results = []
  for ticker, name in tickers.items():
    print(f"Fetching data for {ticker} ({name})...")
    try:
      stock = yf.Ticker(ticker)
      data = stock.history(period="6mo", interval="1d")

      data = calculate_indicators(data)
      if data is None or data.empty:
        raise ValueError("Failed to calculate indicators or data is empty")

      latest_rsi = data['RSI'].iloc[-1]
      latest_change = data['Change_Rate'].iloc[-1]
      candle_type = "양봉" if data['Bullish'].iloc[-1] else "음봉"

      ticker_link = f"<https://finance.yahoo.com/quote/{ticker}|{name}>"
      change_value = float(latest_change)
      emoji = ":red_circle:" if change_value > 0 else ":large_blue_circle:"
      results.append((float(latest_rsi), f"{emoji} `{change_value:+.2f}%` `{latest_rsi:.2f}` {candle_type} _{ticker_link}_"))
    except Exception as e:
      print(f"Error processing {ticker}: {e}")
      ticker_link = f"<https://finance.yahoo.com/quote/{ticker}|{name}>"
      results.append((float('inf'), f":grey_question: `N/A` `N/A` _{ticker_link}_"))

  return sorted(results, key=lambda x: x[0])

def send_to_slack_market(sorted_tickers, name, webhook_url, icon):
  try:
    message_lines = [f"{icon} *{name}*"]
    for _, line in sorted_tickers:
      message_lines.append(line)
    message_text = "\n".join(message_lines)
    payload = {"text": message_text}
    response = requests.post(webhook_url, json=payload)

    if response.status_code == 200:
      print(f"{name} message sent to Slack successfully.")
    else:
      print(f"Failed to send {name} message to Slack: {response.status_code}, {response.text}")
  except Exception as e:
    print(f"Error sending {name} message to Slack: {e}")

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="Send RSI and market data to Slack")
  parser.add_argument("--market", choices=["korea", "global"], required=True, help="Specify the market to process (korea or global)")
  args = parser.parse_args()

  try:
    with open("config.json", "r") as config_file:
      config = json.load(config_file)

    slack_webhook_url = config["slack_webhook_url"]

    if args.market in config:
      market_config = config[args.market]
      tickers = market_config["tickers"]
      name = market_config["name"]
      icon = market_config["icon"]

      sorted_tickers = process_and_sort_tickers(tickers)
      send_to_slack_market(sorted_tickers, name, slack_webhook_url, icon)
    else:
      print(f"Market configuration for {args.market} not found.")
  except Exception as e:
    print(f"Error loading configuration file or sending message: {e}")
