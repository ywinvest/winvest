import concurrent.futures
import os
import time
from datetime import datetime
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
import requests
from dotenv import load_dotenv

SLACK_API_URL = "https://slack.com/api"

def calculate_indicators(df):
  df['MA5'] = df['Close'].rolling(window=5).mean()
  df['MA10'] = df['Close'].rolling(window=10).mean()
  df['MA20'] = df['Close'].rolling(window=20).mean()
  df['MA60'] = df['Close'].rolling(window=60).mean()
  df['Bullish'] = df['Close'] > df['Open']
  df['Volume_Change'] = df['Volume'] / df['Volume'].shift(1)
  df['High_Change'] = (df['High'] / df['Close'].shift(1) - 1) * 100
  df['Pre_Change'] = df['Change'].shift(1)
  # df['Pre_Bullish'] = df['Close'].shift(1) > df['Open'].shift(1)
  df['Pre_High_Change'] = df['High_Change'].shift(1)
  df['Pre_Volume_Change'] = df['Volume'].shift(1) / df['Volume'].shift(2)
  df['Crossover'] = (df['MA5'] > df['MA20']) & (df['MA5'].shift(1) <= df['MA20'].shift(1))
  df['Crossover_Count'] = df['Crossover'].rolling(window=30, min_periods=1).sum()
  df['52WeekLow'] = df['Low'].rolling(window='365D', min_periods=1).min()
  return df

def filter_common_stocks(df):
  # ETN, ETF, 리츠, 선박펀드, 스팩 제외
  exclude_pattern = r'ETN|ETF|리츠|선박펀드|스팩'
  return df[(~df['Name'].str.contains(exclude_pattern, na=False, regex=True))
            & (~df['Code'].str.endswith("5", na=False)) # 우선주
            & (~df['Code'].str.endswith("7", na=False)) # 우선주
            & (~df['Code'].str.endswith("K", na=False)) # 우선주
            & (~df['Code'].str.endswith("L", na=False)) # 우선주
            # & (df['Name'].str.contains("나무기술", na=False, regex=True))
            ]

def buy_condition(df):
  # 벡터화된 연산 사용
  conditions = pd.Series(True, index=df.index)
  conditions &= (df['Close'] <= df['52WeekLow'] * 1.3)
  conditions &= (df['Change'] >= 0)
  conditions &= (df['High_Change'] >= 8)
  conditions &= (df['Bullish'])
  conditions &= (df['Volume_Change'] > 3) # 300% 초과
  # conditions &= (df['Volume_Change'] < 1000) # 100,000% 미만
  conditions &= (df['Crossover_Count'] >= 2)
  # conditions &= ~((df['Pre_Volume_Change'] > 3) & (df['Pre_Change'] > 0)) # 전봉 거래량 300% 초과 + 등락률 0% 초과 제외
  conditions &= (df['Pre_Volume_Change'] <= 4) # 전봉 거래량 400% 이하
  conditions &= (df['Close'] >= df['MA20'])
  conditions &= (df['Low'] != df['52WeekLow']) # 52주 신저가 경신 제외
  return conditions

def create_rich_text_header(emoji, text):
  return {
    "type": "rich_text_section",
    "elements": [
      {
        "type": "emoji",
        "name": emoji,
      },
      {
        "type": "text",
        "text": text,
        "style": {
          "bold": True
        }
      }
    ]
  }

def create_rich_text_item(text):
  return {
    "type": "rich_text_section",
    "elements": [
      {
        "type": "text",
        "text": text
      }
    ]
  }

def send_slack_message(blocks):
  # 설정 로드
  # with open("config-woo1.json", "r") as config_file:
  #   config = json.load(config_file)

  # slack_token = config["slack_bot_token"]
  # slack_channel = config["slack_channel"]
  bot_token = os.getenv("SLACK_BOT_TOKEN")
  channel = os.getenv("SLACK_CHANNEL")

  headers = {
    "Authorization": f"Bearer {bot_token}",
    "Content-Type": "application/json"
  }

  payload = {
    "channel": channel,
    "blocks": blocks
  }

  response = requests.post(f"{SLACK_API_URL}/chat.postMessage", headers=headers, json=payload)
  response_data = response.json()
  if not response_data.get("ok"):
    raise Exception(f"Failed to send message: {response_data.get('error')}")
  return response_data.get("ts")

def format_market_cap(marcap):
  """시가총액을 조 또는 억 단위로 포맷팅"""
  if marcap >= 1e12:  # 1조 이상
    return f"{marcap/1e12:.1f}조"
  else:  # 억 단위
    return f"{marcap/1e8:.0f}억"

def send_to_slack(result_data):
  try:
    if result_data.empty:
      blocks = [
        {
          "type": "section",
          "text": {
            "type": "plain_text",
            "text": "오늘은 매수 후보가 없습니다.",
            "emoji": True
          }
        }
      ]
      send_slack_message(blocks)
      print("No stocks match the buying conditions")
      return

    # 결과를 Market과 High_Change를 기준으로 정렬
    result_data = result_data.sort_values(['Market', 'High_Change'], ascending=[True, False])

    # 시장별로 데이터 구성
    rich_text_elements = []
    for market, group in result_data.groupby('Market'):
      rich_text_elements.append(create_rich_text_header(
          "chart_with_upwards_trend", f" {today.year}년 {today.month}월 {today.day}일 {market} 매수 후보\n"
      ))
      # 리스트 아이템 추가
      list_elements = []
      for _, row in group.iterrows():
        name = row['Name']
        change = row['Change']
        high_change = row['High_Change']
        marcap = row['Marcap']
        volume_change = row['Volume_Change']

        # Rich Text 아이템 생성
        item = create_rich_text_item(
            f"{name} : {format_market_cap(marcap)}, 고가: {high_change:.2f}%, 고가-종가: {high_change - change * 100:.2f}%, 거래량: {volume_change * 100:.2f}%"
        )
        list_elements.append(item)

      rich_text_elements.append({
        "type": "rich_text_list",
        "style": "bullet",
        "indent": 0,
        "elements": list_elements
      })

    blocks = [
      {
        "type": "rich_text",
        "elements": rich_text_elements
      }
    ]

    # Slack 메시지 전송
    send_slack_message(blocks)

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

  # .env 파일 로드
  load_dotenv()

  try:
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
    send_to_slack(result_data)

  except Exception as e:
    print(f"Error in main execution: {e}")

  finally:
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"총 소요시간: {elapsed_time:.2f}초")