import argparse
import json

import pandas_ta as ta
import requests
import yfinance as yf
from pykrx import stock


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

def convert_ticker(ticker):
  if ticker.endswith(".KS"):
    return ticker.split(".")[0]
  return ticker

def determine_ticker_suffix(ticker):
  df = yf.Ticker(f"{ticker}.KS").history(period="1d")
  if df.empty:
    return ticker + ".KQ"
  else:
    return ticker + ".KS"

def fetch_and_process_ticker(ticker, name):
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
    return (float(latest_rsi), f"{emoji} `{change_value:+.2f}%` `{latest_rsi:.2f}` {candle_type} _{ticker_link}_")
  except Exception as e:
    print(f"Error processing {ticker}: {e}")
    ticker_link = f"<https://finance.yahoo.com/quote/{ticker}|{name}>"
    return (float('inf'), f":grey_question: `N/A` `N/A` _{ticker_link}_")

def process_and_sort_tickers(tickers):
  results = [
    fetch_and_process_ticker(ticker, name)
    for ticker, name in tickers.items()
  ]
  return sorted(results, key=lambda x: x[0])

def process_etf_components(etf_tickers):
  etf_results = []
  for ticker, name in etf_tickers.items():
    try:
      print(f"Fetching ETF components for {ticker} ({name})...")
      yf_ticker = yf.Ticker(ticker)
      if yf_ticker.info.get('quoteType', '').lower() != 'etf':
        print(f"{ticker} is not an ETF. Skipping.")
        continue

      krx_ticker = convert_ticker(ticker)
      components = stock.get_etf_portfolio_deposit_file(krx_ticker)
      exclude_tickers = ['010010', '010000', '010140']  # 원화현금, 외화현금 등
      exclude_mask = ~components.index.isin(exclude_tickers)

      # 두 조건을 모두 적용
      components = components[exclude_mask]
      components = components.sort_values(by='비중', ascending=False).head(10)

      component_details = []
      for component in components.index:
        component_name = stock.get_market_ticker_name(component)
        component_ticker_name = determine_ticker_suffix(component)
        component_result = fetch_and_process_ticker(component_ticker_name, component_name)
        component_details.append(component_result)

      component_details = sorted(component_details, key=lambda x: x[0])
      component_list = [
        f"{detail[1]}"
        for detail in component_details
      ]
      etf_results.append((name, component_list))
    except Exception as e:
      print(f"Error processing ETF {ticker}: {e}")

  return etf_results

SLACK_API_URL = "https://slack.com/api"

def send_slack_message(token, channel, text):
  headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
  }
  payload = {"channel": channel, "text": text}
  response = requests.post(f"{SLACK_API_URL}/chat.postMessage", headers=headers, json=payload)
  response_data = response.json()
  if not response_data.get("ok"):
    raise Exception(f"Failed to send message: {response_data.get('error')}")
  return response_data.get("ts")  # 메시지의 timestamp 반환

def send_slack_thread_reply(token, channel, text, thread_ts):
  headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
  }
  payload = {"channel": channel, "text": text, "thread_ts": thread_ts}
  response = requests.post(f"{SLACK_API_URL}/chat.postMessage", headers=headers, json=payload)
  response_data = response.json()
  if not response_data.get("ok"):
    raise Exception(f"Failed to send thread reply: {response_data.get('error')}")

def send_to_slack_market(sorted_tickers, etf_components, name, token, channel, icon):
  try:
    # 메인 메시지 작성
    message_lines = [f"{icon} *{name}*"]
    for _, line in sorted_tickers:
      message_lines.append(line)
    main_message = "\n".join(message_lines)

    # 메인 메시지 전송 및 ts 반환
    main_ts = send_slack_message(token, channel, main_message)

    # ETF 구성 종목을 쓰레드로 전송
    for etf_name, components in etf_components:
      thread_message = f"*{etf_name} 구성 종목:*\n" + "\n".join(components)
      send_slack_thread_reply(token, channel, thread_message, main_ts)
  except Exception as e:
    print(f"Error sending Slack message: {e}")

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="Send RSI and market data to Slack")
  parser.add_argument("--market", choices=["korea", "global"], required=True, help="Specify the market to process (korea or global)")
  args = parser.parse_args()

  try:
    with open("config.json", "r") as config_file:
      config = json.load(config_file)

    slack_token = config["slack_bot_token"]
    slack_channel = config["slack_channel"]

    if args.market in config:
      market_config = config[args.market]
      tickers = market_config["tickers"]
      name = market_config["name"]
      icon = market_config["icon"]

      sorted_tickers = process_and_sort_tickers(tickers)

      if args.market == "korea":
        etf_components = process_etf_components(tickers)
      else:
        etf_components = []

      send_to_slack_market(sorted_tickers, etf_components, name, slack_token, slack_channel, icon)
    else:
      print(f"Market configuration for {args.market} not found.")
  except Exception as e:
    print(f"Error loading configuration file or sending message: {e}")
