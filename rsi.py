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
      results.append((float(latest_rsi),
                      f"{emoji} `{change_value:+.2f}%` `{latest_rsi:.2f}` {candle_type} _{ticker_link}_"))
    except Exception as e:
      print(f"Error processing {ticker}: {e}")
      ticker_link = f"<https://finance.yahoo.com/quote/{ticker}|{name}>"
      results.append(
          (float('inf'), f":grey_question: `N/A` `N/A` _{ticker_link}_"))

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
      print(
        f"Failed to send {market_name} message to Slack: {response.status_code}, {response.text}")
  except Exception as e:
    print(f"Error sending {market_name} message to Slack: {e}")


if __name__ == "__main__":
  parser = argparse.ArgumentParser(
    description="Send RSI and market data to Slack")
  parser.add_argument("--market", choices=["korea", "global"], required=True,
                      help="Specify the market to process (korea or global)")
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
      send_to_slack_market(tickers, "Global Market", slack_webhook_url,
                           ":earth_americas:")
  except Exception as e:
    print(f"Error loading configuration file or sending message: {e}")
