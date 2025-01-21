import json
import time
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd
import requests

SLACK_API_URL = "https://slack.com/api"

def calculate_indicators(df):
  df['MA5'] = df['Close'].rolling(window=5).mean()
  df['MA10'] = df['Close'].rolling(window=10).mean()
  df['MA20'] = df['Close'].rolling(window=20).mean()
  df['MA60'] = df['Close'].rolling(window=60).mean()
  df['Bullish'] = df['Close'] > df['Open']
  df['Volume_Change'] = df['Volume'] / df['Volume'].shift(1)
  df['Pre_Change'] = df['Change'].shift(1)
  # df['Pre_Bullish'] = df['Close'].shift(1) > df['Open'].shift(1)
  df['Pre_Volume_Change'] = df['Volume'].shift(1) / df['Volume'].shift(2)
  df['High_Change'] = (df['High'] / df['Close'].shift(1) - 1) * 100
  df['Crossover'] = (df['MA5'] > df['MA20']) & (df['MA5'].shift(1) <= df['MA20'].shift(1))
  df['Crossover_Count'] = df['Crossover'].rolling(window=30, min_periods=1).sum()
  df['52WeekLow'] = df['Low'].rolling(window=364, min_periods=1).min()
  return df

def filter_common_stocks(df):
  return df[
    (~df['Name'].str.contains('ETN|ETF|리츠|선박펀드', na=False)) # ETN, ETF, 리츠, 선박펀드 제외
    & (~df['Name'].str.contains('우|2우|3우|우B|우C', na=False)) # 우선주 제외
    & (~df['Name'].str.contains('스팩', na=False))              # 스팩 제외
    # & (df['Marcap'] >= 500 * 1e8)                              # 시가총액 500억 이상
    # & (df['Marcap'] < 10 * 1e12)                             # 시가총액 10조 미만
    ]

def buy_condition(df):
  # 각 조건 정의
  condition1 = df['Close'] <= df['52WeekLow'] * 1.3
  condition2 = df['Change'] >= 0
  condition3 = df['High_Change'] >= 8
  condition4 = df['Bullish']
  condition5 = df['Volume_Change'] > 3 # 300% 초과
  condition6 = df['Volume_Change'] < 1000 # 100,000% 미만
  condition7 = df['Crossover_Count'] >= 2
  condition8 = ~((df['Pre_Volume_Change'] > 3) & (df['Pre_Change'] > 0)) # 전봉 거래량 300% 초과 + 등락률 0% 초과 제외
  condition9 = df['Close'] >= df['MA20']

  # 모든 조건 결합
  return (
      condition1
      & condition2
      & condition3
      & condition4
      & condition5
      # & condition6
      & condition7
      & condition8
      & condition9
  )

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

def send_to_slack(result_data, token, channel):
  try:
    # 기본 메시지 헤더
    header = f"🔍{today.year}년 {today.month}월 {today.day}일 매수 후보"

    if result_data.empty:
      message = f"{header}\n• 오늘은 매수 후보가 없습니다."
      send_slack_message(token, channel, message)
      print("No stocks match the buying conditions")
      return

    # 결과를 High_Change를 기준으로 정렬
    result_data = result_data.sort_values('High_Change', ascending=False)

    # 메시지 생성
    message_lines = [header]

    for _, row in result_data.iterrows():
      ticker = row['Ticker']
      name = row['Name']
      market = row['Market']
      high_change = row['High_Change']

      message_line = f"• {name}({market}) - 고가: {high_change:.2f}%"
      message_lines.append(message_line)

    # 메시지 결합 및 전송
    main_message = "\n".join(message_lines)
    send_slack_message(token, channel, main_message)
  except Exception as e:
    print(f"Error sending Slack message: {e}")

if __name__ == "__main__":
  start_time = time.time()
  try:
    with open("config-woo1.json", "r") as config_file:
      config = json.load(config_file)

    slack_token = config["slack_bot_token"]
    slack_channel = config["slack_channel"]

    kospi = fdr.StockListing('KOSPI')
    kospi = kospi.tail(-100)
    kosdaq = fdr.StockListing('KOSDAQ')

    kospi = filter_common_stocks(kospi)
    kosdaq = filter_common_stocks(kosdaq)

    # 3. 코스피/코스닥 종목 병합
    all_stocks = pd.concat([kospi, kosdaq], ignore_index=True)

    result_data = pd.DataFrame()
    today = datetime.today()
    yesterday = today - timedelta(days=1)
    current_year = datetime.today().year
    two_years_ago = current_year - 2

    for _, row in all_stocks.iterrows():
      ticker = row['Code']
      name = row['Name']
      marcap = row['Marcap']
      market = row['Market']
      df = fdr.DataReader(ticker, two_years_ago)
      df = calculate_indicators(df)

      # 매수 조건에 해당하는 데이터 필터링
      buys = df[buy_condition(df)]
      buys = buys[buys.index.date == today.date()]
      if not buys.empty:
        buys['Ticker'] = ticker
        buys['Name'] = name
        buys['Marcap'] = marcap
        buys['Market'] = market
        result_data = pd.concat([result_data, buys])

    send_to_slack(result_data, slack_token, slack_channel)
  except Exception as e:
    print(f"Error loading configuration file or sending message: {e}")

  end_time = time.time()
  elapsed_time = end_time - start_time
  print(f"총 소요시간: {elapsed_time:.2f}초")
