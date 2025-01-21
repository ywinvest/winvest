import concurrent.futures
import json
import time
from datetime import datetime, timedelta
from functools import partial

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
  # ETN, ETF, 리츠, 선박펀드, 우선주, 스팩 제외
  exclude_pattern = r'ETN|ETF|리츠|선박펀드|우|2우|3우|우B|우C|스팩'
  return df[~df['Name'].str.contains(exclude_pattern, na=False, regex=True)]

def buy_condition(df):
  # 벡터화된 연산 사용
  conditions = pd.Series(True, index=df.index)
  conditions &= (df['Close'] <= df['52WeekLow'] * 1.3)
  conditions &= (df['Change'] >= 0)
  conditions &= (df['High_Change'] >= 8)
  conditions &= (df['Bullish'])
  conditions &= (df['Volume_Change'] > 3) # 300% 초과
  conditions &= (df['Volume_Change'] < 1000) # 100,000% 미만
  conditions &= (df['Crossover_Count'] >= 2)
  conditions &= ~((df['Pre_Volume_Change'] > 3) & (df['Pre_Change'] > 0)) # 전봉 거래량 300% 초과 + 등락률 0% 초과 제외
  conditions &= (df['Close'] >= df['MA20'])
  return conditions

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

def process_stock(row, two_years_ago, today):
  try:
    ticker = row['Code']
    name = row['Name']
    marcap = row['Marcap']
    market = row['Market']

    df = fdr.DataReader(ticker, two_years_ago)
    df = calculate_indicators(df)

    buys = df[buy_condition(df)]
    buys = buys[buys.index.date == today.date()]

    if not buys.empty:
      buys['Ticker'] = ticker
      buys['Name'] = name
      buys['Marcap'] = marcap
      buys['Market'] = market
      return buys
    return None
  except Exception as e:
    print(f"Error processing {ticker}: {e}")
    return None

def parallel_process_stocks(all_stocks, two_years_ago, today):
  process_func = partial(process_stock, two_years_ago=two_years_ago, today=today)
  results = []

  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(process_func, row) for _, row in all_stocks.iterrows()]
    for future in concurrent.futures.as_completed(futures):
      result = future.result()
      if result is not None:
        results.append(result)

  return pd.concat(results) if results else pd.DataFrame()

if __name__ == "__main__":
  start_time = time.time()
  try:
    # 설정 로드
    with open("config-woo1.json", "r") as config_file:
      config = json.load(config_file)

    slack_token = config["slack_bot_token"]
    slack_channel = config["slack_channel"]

    # 종목 리스트 가져오기 및 필터링
    all_stocks = pd.concat([
      filter_common_stocks(fdr.StockListing('KOSPI').tail(-100)),
      filter_common_stocks(fdr.StockListing('KOSDAQ'))
    ], ignore_index=True)

    # 날짜 설정
    today = datetime.today()
    two_years_ago = today.year - 2

    # 병렬 처리로 데이터 분석
    result_data = parallel_process_stocks(all_stocks, two_years_ago, today)

    # Slack 메시지 전송
    send_to_slack(result_data, slack_token, slack_channel)

  except Exception as e:
    print(f"Error in main execution: {e}")

  finally:
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"총 소요시간: {elapsed_time:.2f}초")