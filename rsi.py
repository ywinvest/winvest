import argparse
import json

import pandas_ta as ta
import requests
import yfinance as yf


def fetch_rsi_and_change(ticker, period='14'):
  try:
    stock = yf.Ticker(ticker)
    data = stock.history(period="6mo", interval="1d")
    if data.empty:
      print(f"No data found for ticker {ticker}")
      return None, None, None

    data['RSI'] = ta.rsi(data['Close'], length=int(period))
    data['Change'] = data['Close'].pct_change() * 100

    latest_close = data['Close'].iloc[-1]
    latest_open = data['Open'].iloc[-1]
    latest_rsi = data['RSI'].iloc[-1]
    latest_change = data['Change'].iloc[-1]

    candle_type = "양봉" if latest_close > latest_open else "음봉"
    return f"{latest_rsi:.2f}", latest_change, candle_type
  except Exception as e:
    print(f"Error fetching RSI and change for {ticker}: {e}")
    return None, None, None


def process_and_sort_tickers(tickers):
  results = []
  for ticker, name in tickers.items():
    print(f"Fetching RSI and change for {ticker} ({name})...")
    rsi, change, candle_type = fetch_rsi_and_change(ticker)

    ticker_link = f"<https://finance.yahoo.com/quote/{ticker}|{name}>"
    if rsi and change is not None:
      change_value = float(change)
      emoji = ":red_circle:" if change_value > 0 else ":large_blue_circle:"
      results.append((float(rsi), f"{emoji} `{change_value:+.2f}%` `{rsi}` {candle_type} _{ticker_link}_"))
    else:
      results.append((float('inf'), f":grey_question: `N/A` `N/A` _{ticker_link}_"))
  return sorted(results, key=lambda x: x[0])


def send_to_slack_market(tickers, market_name, webhook_url, market_icon):
  try:
    sorted_tickers = process_and_sort_tickers(tickers)
    message_lines = [f"{market_icon} *{market_name}*"]
    for _, line in sorted_tickers:
      message_lines.append(line)
    message_text = "\n".join(message_lines)
    payload = {"text": message_text}
    response = requests.post(webhook_url, json=payload)

    if response.status_code == 200:
      print(f"{market_name} message sent to Slack successfully.")
    else:
      print(f"Failed to send {market_name} message to Slack: {response.status_code}, {response.text}")
  except Exception as e:
    print(f"Error sending {market_name} message to Slack: {e}")


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="Send RSI and market data to Slack")
  parser.add_argument("--market", choices=["korea", "global"], required=True, help="Specify the market to process (korea or global)")
  args = parser.parse_args()

  try:
    with open("config.json", "r") as config_file:
      config = json.load(config_file)

    slack_webhook_url = config["slack_webhook_url"]

    if args.market == "korea":
      tickers = config["korea"]["tickers"]
      send_to_slack_market(tickers, "Korea Market", slack_webhook_url, ":kr:")
    elif args.market == "global":
      tickers = config["global"]["tickers"]
      send_to_slack_market(tickers, "Global Market", slack_webhook_url, ":earth_americas:")
  except Exception as e:
    print(f"Error loading configuration file or sending message: {e}")
