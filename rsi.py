import argparse
import json
import os

import pandas as pd
import pandas_ta as ta
import yfinance as yf
from pykrx import stock

from slack_utils import SlackMessageBuilder, send_slack_message


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

def fetch_and_process_ticker(ticker):
  """지정된 티커의 시세 데이터와 기술 지표를 포함하는 DataFrame을 가져옵니다."""
  try:
    stock = yf.Ticker(ticker)
    df = stock.history(period="6mo", interval="1d")
    if df.empty:
      print(f"No history data for {ticker}")
      return pd.DataFrame()

    return calculate_indicators(df)
  except Exception as e:
    print(f"Error processing {ticker}: {e}")
    return pd.DataFrame()

def process_and_sort_tickers(tickers):
  """
  티커 목록을 처리하고 각 티커의 DataFrame을 포함하는 딕셔너리 리스트를 반환합니다.
  결과는 최신 RSI를 기준으로 정렬됩니다.
  """
  results = []
  for ticker, name in tickers.items():
    df = fetch_and_process_ticker(ticker)
    if not df.empty and 'RSI' in df.columns and not df['RSI'].dropna().empty:
      results.append({"ticker": ticker, "name": name, "df": df})

  results.sort(key=lambda x: x['df']['RSI'].iloc[-1] if pd.notna(x['df']['RSI'].iloc[-1]) else float('inf'))
  return results

def process_etf_components(etf_tickers):
  """
  ETF 구성 종목을 처리하고 각 종목의 DataFrame을 포함하는 데이터 구조를 반환합니다.
  """
  etf_results = []
  for ticker, name in etf_tickers.items():
    try:
      print(f"Fetching ETF components for {ticker} ({name})...")
      yf_ticker = yf.Ticker(ticker)
      if yf_ticker.info.get('quoteType', '').lower() != 'etf':
        print(f"{ticker} is not an ETF. Skipping.")
        continue

      krx_ticker = convert_ticker(ticker)
      components_df = stock.get_etf_portfolio_deposit_file(krx_ticker)
      exclude_tickers = ['010010', '010000', '010140']  # 원화현금 등 제외
      exclude_mask = ~components_df.index.isin(exclude_tickers)

      components_df = components_df[exclude_mask]
      components_df = components_df.sort_values(by='비중', ascending=False).head(10)

      component_details = []
      for component_code in components_df.index:
        component_name = stock.get_market_ticker_name(component_code)
        component_ticker_name = determine_ticker_suffix(component_code)
        df = fetch_and_process_ticker(component_ticker_name)

        if not df.empty and 'RSI' in df.columns and not df['RSI'].dropna().empty:
          component_details.append({
            "ticker": component_ticker_name,
            "name": component_name,
            "df": df
          })

      component_details.sort(key=lambda x: x['df']['RSI'].iloc[-1] if pd.notna(x['df']['RSI'].iloc[-1]) else float('inf'))
      etf_results.append({"name": name, "components": component_details})
    except Exception as e:
      print(f"Error processing ETF {ticker}: {e}")

  return etf_results

def send_to_slack_market(sorted_tickers, etf_components, name, token, channel, emoji):
  """
  처리된 DataFrame 데이터를 기반으로 Slack 메시지를 구성하고 전송합니다.
  """
  builder = SlackMessageBuilder()

  try:
    with builder.line() as line:
      line.emoji(emoji).space().text(name, bold=True)

    # 기본 티커 목록 메시지 생성
    for data in sorted_tickers:
      df = data.get('df')
      if df is None or df.empty:
        continue

      latest = df.iloc[-1]
      rsi = latest.get('RSI')
      change_rate = latest.get('Change_Rate')
      is_bullish = latest.get('Bullish')
      ticker_url = f"https://finance.yahoo.com/quote/{data['ticker']}"
      name = data['name']

      change_value = float(change_rate)
      emoji = "red_circle" if change_value > 0 else "large_blue_circle"
      candle_type = "양봉" if is_bullish else "음봉"

      with builder.line() as line:
        line.emoji(emoji).space()
        line.text(f"{change_value:+.2f}%", code=True).space()
        line.text(f"{rsi:.2f}", code=True).space()
        line.text(candle_type).space()
        line.link(ticker_url, name, italic=True)

    main_ts = send_slack_message(builder.build(), token, channel)

    # ETF 구성 종목 쓰레드 메시지 생성
    for etf_data in etf_components:
      etf_builder = SlackMessageBuilder()
      with etf_builder.line() as line:
        line.text(f"{etf_data['name']} 구성 종목:", bold=True)

      for component in etf_data['components']:
        df = component.get('df')
        if df is None or df.empty:
          continue

        latest = df.iloc[-1]
        rsi = latest.get('RSI')
        change_rate = latest.get('Change_Rate')
        is_bullish = latest.get('Bullish')
        ticker_url = f"https://finance.yahoo.com/quote/{component['ticker']}"
        name = component['name']

        change_value = float(change_rate)
        emoji = "red_circle" if change_value > 0 else "large_blue_circle"
        candle_type = "양봉" if is_bullish else "음봉"

        with etf_builder.line() as line:
          line.emoji(emoji).space()
          line.text(f"{change_value:+.2f}%", code=True).space()
          line.text(f"{rsi:.2f}", code=True).space()
          line.text(candle_type).space()
          line.link(ticker_url, name, italic=True)

      send_slack_message(etf_builder.build(), token, channel, main_ts)

  except Exception as e:
    print(f"Error sending Slack message: {e}")

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="Send RSI and market data to Slack")
  parser.add_argument("--market", choices=["korea", "global"], required=True, help="Specify the market to process (korea or global)")
  args = parser.parse_args()

  try:
    with open("config.json", "r") as config_file:
      config = json.load(config_file)

    token = os.getenv("SLACK_BOT_TOKEN")
    channel = os.getenv("SLACK_CHANNEL")

    slack_token = config["slack_bot_token"]
    slack_channel = config["slack_channel"]

    if args.market in config:
      market_config = config[args.market]
      tickers = market_config["tickers"]
      name = market_config["name"]
      icon = market_config["icon"]
      emoji = market_config["emoji"]

      sorted_tickers = process_and_sort_tickers(tickers)

      etf_components = []
      if args.market == "korea":
        etf_components = process_etf_components(tickers)

      send_to_slack_market(sorted_tickers, etf_components, name, token, channel, emoji)
    else:
      print(f"Market configuration for {args.market} not found.")
  except Exception as e:
    print(f"Error loading configuration file or sending message: {e}")
