import yfinance as yf
import pandas_ta as ta
import requests
import json

def fetch_rsi_and_change(ticker, period='14'):
  """
  Fetch the RSI (Relative Strength Index), daily change, and candle type for the given ticker.

  Parameters:
      ticker (str): The stock ticker symbol.
      period (str): The period for RSI calculation (default: 14).

  Returns:
      tuple: The latest RSI value, percentage change, and candle type (양봉/음봉).
  """
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

    # Determine candle type
    candle_type = "양봉" if latest_close > latest_open else "음봉"

    return f"{latest_rsi:.2f}", latest_change, candle_type
  except Exception as e:
    print(f"Error fetching RSI and change for {ticker}: {e}")
    return None, None, None

def send_to_slack_combined(tickers_local, tickers_global, webhook_url):
  """
  Send results for both Local and Global markets in a single Slack message with formatted text.

  Parameters:
      tickers_local (dict): Dictionary of local tickers and their names.
      tickers_global (dict): Dictionary of global tickers and their names.
      webhook_url (str): The Slack webhook URL.
  """
  try:
    # Helper function to process tickers and sort by RSI
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
      # Sort by RSI (ascending)
      return sorted(results, key=lambda x: x[0])

    # Process and sort local and global tickers
    local_sorted = process_and_sort_tickers(tickers_local)
    global_sorted = process_and_sort_tickers(tickers_global)

    # Prepare Slack message
    message_lines = []

    # Local Market section
    message_lines.append(":round_pushpin: *Local Market*")
    for _, line in local_sorted:
      message_lines.append(line)

    # Global Market section
    message_lines.append("\n:earth_africa: *Global Market*")
    for _, line in global_sorted:
      message_lines.append(line)

    # Combine all lines into a single message
    message_text = "\n".join(message_lines)

    # Send the message to Slack
    payload = {"text": message_text}
    response = requests.post(webhook_url, json=payload)

    if response.status_code == 200:
      print("Message sent to Slack successfully.")
    else:
      print(f"Failed to send message to Slack: {response.status_code}, {response.text}")
  except Exception as e:
    print(f"Error sending message to Slack: {e}")

if __name__ == "__main__":
  try:
    # Load config
    with open("config.json", "r") as config_file:
      config = json.load(config_file)

    slack_webhook_url = config["slack_webhook_url"]
    local_tickers = config["local"]["tickers"]
    global_tickers = config["global"]["tickers"]
  except Exception as e:
    print(f"Error loading configuration file: {e}")
    exit(1)

  # Send combined Slack message
  send_to_slack_combined(local_tickers, global_tickers, slack_webhook_url)
