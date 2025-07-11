import concurrent.futures
import os
import time
from datetime import datetime
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
import pandas_ta as ta
import requests
from dotenv import load_dotenv

SLACK_API_URL = "https://slack.com/api"

def calculate_indicators(df):
  # df['MA5'] = df['Close'].rolling(window=5).mean()
  # df['MA10'] = df['Close'].rolling(window=10).mean()
  df['MA20'] = df['Close'].rolling(window=20).mean()
  df['MA60'] = df['Close'].rolling(window=60).mean()
  df['MA120'] = df['Close'].rolling(window=120).mean()
  df['MA20_Cross'] = (df['Close'].gt(df['MA20'], axis=0)) & (df['Close'].shift(1).le(df['MA20'].shift(1), axis=0))
  df['MA20_Break'] = (df['Close'].lt(df['MA20'], axis=0)) & (df['Close'].shift(1).ge(df['MA20'].shift(1), axis=0))
  df['Bullish'] = df['Close'] > df['Open']
  df['Volume_Change'] = df['Volume'] / df['Volume'].shift(1) - 1
  # df['High_Change'] = (df['High'] / df['Close'].shift(1) - 1) * 100
  # df['Pre_Change'] = df['Change'].shift(1)
  # # df['Pre_Bullish'] = df['Close'].shift(1) > df['Open'].shift(1)
  # df['Pre_High_Change'] = df['High_Change'].shift(1)
  # df['Pre_Volume_Change'] = df['Volume'].shift(1) / df['Volume'].shift(2)
  # df['Crossover'] = (df['MA5'] > df['MA20']) & (df['MA5'].shift(1) <= df['MA20'].shift(1))
  # df['Crossover_Count'] = df['Crossover'].rolling(window=30, min_periods=1).sum()
  df['Pre39WeekHigh'] = df['High'].shift(1).rolling(window='273D', min_periods=1).max()

  df['Pre52WeekHigh'] = df['High'].shift(1).rolling(window='364D', min_periods=1).max()

  # 39주 신고가 돌파 여부
  is_39weekhigh_break = df['Close'] > df['Pre39WeekHigh']
  # 52주 신고가 돌파 여부
  is_52weekhigh_break = df['Close'] > df['Pre52WeekHigh']

  # 연속적인 신고가 돌파를 그룹화하여 첫 돌파만 선택
  # 돌파가 시작되는 지점을 그룹화 기준으로 사용
  # breaks = (~is_52weekhigh_break).cumsum()  # 돌파가 끊기는 지점으로 그룹화
  # is_first_break = is_52weekhigh_break & (~is_52weekhigh_break.shift(1).fillna(False))
  # df['First_52WeekHigh_Break'] = is_first_break.groupby(breaks).cumsum() == 1
  # df['First_52WeekHigh_Break'] = df['First_52WeekHigh_Break'].where(is_52weekhigh_break, False)
  # 39주 신고가 첫 돌파여부
  df['First_39WeekHigh_Break'] = is_39weekhigh_break & (~is_39weekhigh_break.shift(1, fill_value=False))
  # 52주 신고가 첫 돌파여부
  df['First_52WeekHigh_Break'] = is_52weekhigh_break & (~is_52weekhigh_break.shift(1, fill_value=False))
  # 첫 돌파 이후 10일 동안 추가 돌파 무시
  # df['First_52WeekHigh_Break'] = df['First_52WeekHigh_Break'].where(
  #     ~df['First_52WeekHigh_Break'].rolling(window=10, min_periods=1).sum().shift(1).fillna(0).astype(bool),
  #     False
  # )

  # 이동평균선 추세 상승 여부 (기울기 > 0)
  # df['MA20_Uptrend'] = df['MA20'] > df['MA20'].shift(1)
  # df['MA60_Uptrend'] = df['MA60'] > df['MA60'].shift(1)
  # df['MA120_Uptrend'] = df['MA120'] > df['MA120'].shift(1)
  df['MA20_Slope'] = df['MA20'].pct_change(fill_method=None)
  df['MA60_Slope'] = df['MA60'].pct_change(fill_method=None)
  df['MA120_Slope'] = df['MA120'].pct_change(fill_method=None)

  # 벡터화된 연속 상승 일수 계산
  def calculate_uptrend_days_vec(uptrend_series):
    """벡터화 방식으로 연속 상승 일수를 계산"""
    # 상승 추세가 끊기는 지점을 그룹화 기준으로 사용
    breaks = (~uptrend_series).cumsum()
    # 각 그룹 내에서 연속된 True의 개수 계산
    uptrend_days = uptrend_series.groupby(breaks).cumsum()
    # 상승 추세가 아닌 경우(False)는 0으로 설정
    uptrend_days = uptrend_days.where(uptrend_series, 0)
    return uptrend_days

  # 각 MA에 대해 추세 상승 유지 일수 추가
  df['MA20_Uptrend_Days'] = calculate_uptrend_days_vec(df['MA20_Slope'] > 0)
  df['MA60_Uptrend_Days'] = calculate_uptrend_days_vec(df['MA60_Slope'] > 0)
  df['MA120_Uptrend_Days'] = calculate_uptrend_days_vec(df['MA120_Slope'] > 0)

  df['MA20_Gap'] = df['Close'] / df['MA20'] - 1

  df['Return_1M'] = df['Close'] / df['Close'].shift(20) - 1
  df['Return_3M'] = df['Close'] / df['Close'].shift(60) - 1
  df['Return_6M'] = df['Close'] / df['Close'].shift(120) - 1
  df['Return_12M'] = df['Close'] / df['Close'].shift(240) - 1
  df['Weighted_Return'] = (df['Return_3M'] * 0.5 +
                           df['Return_6M'] * 0.3 +
                           df['Return_12M'] * 0.2)
  return df


def calculate_relative_strength(df):
  for period in ["1M", "3M", "6M", "12M"]:
    return_col = f'Return_{period}'
    rs_col = f'RS_{period}'

    df[rs_col] = df.groupby('Market')[return_col].rank(pct=True) * 98 + 1
    df[rs_col] = df[rs_col].fillna(1).astype(int).clip(1, 99)

  df['RS'] = df.groupby('Market')['Weighted_Return'].rank(pct=True) * 98 + 1
  df['RS'] = df['RS'].fillna(1).astype(int).clip(1, 99)

  return df

def filter_common_stocks(df):
  # 스팩 제외
  exclude_pattern = r'스팩'
  return df[(~df['Name'].str.contains(exclude_pattern, na=False, regex=True))
            & (~df['Code'].str.endswith(("5", "7", "9", "K", "L", "M", "N", "O"))) # 우선주, 일부 ETN/ETF 등 제외
            & (df['Marcap'] >= 200_000_000_000)
            # & (df['Name'].str.contains("나무기술", na=False, regex=True))
            ]

def buy_condition(df):
  # 벡터화된 연산 사용
  conditions = pd.Series(True, index=df.index)
  # conditions &= (df['MA60_Uptrend'])
  # conditions &= (df['MA120_Uptrend'])
  # conditions &= (df['MA20_Cross'])
  # conditions &= (df['Close'] > df['Pre52WeekHigh'])
  kospi_or_kosdaq_global = df['Market'].isin(['KOSPI', 'KOSDAQ GLOBAL'])
  kosdaq = df['Market'] == 'KOSDAQ'

  conditions &= (
      ((kospi_or_kosdaq_global) & df['Pre52WeekHigh'].ne(0) & df['First_52WeekHigh_Break']) |
      ((kosdaq) & df['Pre39WeekHigh'].ne(0) & df['First_39WeekHigh_Break'])
  )
  # conditions &= (df['MA20_Uptrend'] == True)
  # conditions &= (df['MA60_Uptrend'] == True)
  # conditions &= (df['MA120_Uptrend'] == True)
  conditions &= (df['MA20_Slope'] > 0)
  conditions &= (df['MA60_Slope'] > 0)
  conditions &= (df['MA120_Slope'] > 0)
  conditions &= (df['Change'] < 0.295)
  conditions &= (df['Volume'] > 0)
  conditions &= (df['Volume'].shift(1) > 0)
  conditions &= (df['MA120_Uptrend_Days'] < 400) # 120일 상승 추세 장기 연속 제외
  conditions &= ((df['Close'] - df['Open'])/df['Close'] > -0.05) # 긴 음봉 제외
  # conditions &= (df['MA20_Gap'] < 0.3)
  return conditions

def create_rich_text_with_emoji(emoji, text, bold=True):
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
          "bold": bold
        }
      }
    ]
  }

def create_rich_text_item(text, bold=False):
  return {
    "type": "rich_text_section",
    "elements": [
      {
        "type": "text",
        "text": text,
        "style": {
          "bold": bold
        }
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

def truncate_name(name, max_length=10):
  """종목명을 max_length자로 제한하고, 길면 말줄임표 추가"""
  return name[:max_length-1] + '…' if len(name) > max_length else name

def send_to_slack(result_data, kospi, kosdaq):
  try:
    if result_data.empty:
      blocks = [
        {
          "type": "rich_text",
          "elements": create_rich_text_item("오늘은 매수 후보가 없습니다.")
        }
      ]
      send_slack_message(blocks)
      print("No stocks match the buying conditions")
      return

    result_data = result_data.sort_values(['Market', 'RS'], ascending=[True, False])

    # 시장별 RSI 값 가져오기 (오늘 날짜 기준)
    kospi_rsi = kospi[kospi.index.date == today.date()]['RSI'].iloc[-1] if not kospi[kospi.index.date == today.date()].empty else None
    kosdaq_rsi = kosdaq[kosdaq.index.date == today.date()]['RSI'].iloc[-1] if not kosdaq[kosdaq.index.date == today.date()].empty else None
    kospi_adx = kospi[kospi.index.date == today.date()]['ADX'].iloc[-1] if not kospi[kospi.index.date == today.date()].empty else None
    kosdaq_adx = kosdaq[kosdaq.index.date == today.date()]['ADX'].iloc[-1] if not kosdaq[kosdaq.index.date == today.date()].empty else None
    kospi_di = kospi[kospi.index.date == today.date()]['DI'].iloc[-1] if not kospi[kospi.index.date == today.date()].empty else None
    kosdaq_di = kosdaq[kosdaq.index.date == today.date()]['DI'].iloc[-1] if not kosdaq[kosdaq.index.date == today.date()].empty else None

    # 시장별로 데이터 구성
    rich_text_elements = []
    rich_text_elements.append(create_rich_text_item(
        f" {today.year}년 {today.month}월 {today.day}일 신고가 돌파", True
    ))
    for market, group in result_data.groupby('Market'):
      rsi_emoji = "large_green_circle" if (50 <= (
        kospi_rsi if market == 'KOSPI' else kosdaq_rsi) <= 80) and (
          (kospi_adx if market == 'KOSPI' else kosdaq_adx) > 25) and (
        kospi_di if market == 'KOSPI' else kosdaq_di) else "red_circle"
      rsi_value = kospi_rsi if market == 'KOSPI' else kosdaq_rsi
      adx_value = kospi_adx if market == 'KOSPI' else kosdaq_adx
      rich_text_elements.append(create_rich_text_with_emoji(
          rsi_emoji, f"{market} ({rsi_value:.2f}, {adx_value:.2f})", True
      ))
      for _, row in group.iterrows():
        name = row['Name']
        marcap = row['Marcap']
        ma20_gap = row['MA20_Gap']
        rs = row['RS']
        rs_1m = row['RS_1M']
        rs_3m = row['RS_3M']
        rs_6m = row['RS_6M']

        name_truncated = truncate_name(name, 10)
        emoji = "first_place_medal" if ma20_gap < 0.3 and rs_1m >= 70 and rs_1m >= rs_3m and rs_1m >= rs_6m else "question"

        # 한 줄에 종목명과 값 출력, 종목명과 ":" 사이에 공백 2개
        rich_text_elements.append({
          "type": "rich_text_section",
          "elements": [
            {"type": "emoji", "name": emoji},
            {"type": "text", "text": f"{name_truncated}",
             "style": {"code": True}},
            {"type": "text", "text": f" {ma20_gap * 100:.2f}%, {rs} ({rs_1m}, {rs_3m}, {rs_6m}), {format_market_cap(marcap)}"}
          ]
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

def process_stock(row, two_years_ago):
  try:
    symbol = row['Code']
    name = row['Name']
    marcap = row['Marcap']
    market = row['Market']

    df = fdr.DataReader(symbol, two_years_ago)
    df = calculate_indicators(df)

    if not df.empty:
      df['Code'] = symbol
      df['Name'] = name
      df['Marcap'] = marcap
      df['Market'] = market
      return df
    return None
  except Exception as e:
    print(f"Error processing {symbol}: {e}")
    return None

def parallel_process_stocks(all_stocks, two_years_ago):
  process_func = partial(process_stock, two_years_ago=two_years_ago)
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
    all_stocks = pd.concat([
      fdr.StockListing('KOSPI'),
      fdr.StockListing('KOSDAQ')
    ], ignore_index=True)

    # 날짜 설정
    today = datetime.today()
    two_years_ago = today.year - 2

    kospi = fdr.DataReader('KS11', two_years_ago)
    kospi['RSI'] = ta.rsi(kospi['Close'], length=14)
    adx_data = ta.adx(high=kospi['High'], low=kospi['Low'], close=kospi['Close'], length=14, mamode='EMA')
    kospi['ADX'] = adx_data['ADX_14']
    kospi['DI'] = adx_data['DMP_14'] > adx_data['DMN_14']

    kosdaq = fdr.DataReader('KQ11', two_years_ago)
    kosdaq['RSI'] = ta.rsi(kosdaq['Close'], length=14)
    adx_data = ta.adx(high=kosdaq['High'], low=kosdaq['Low'], close=kosdaq['Close'], length=14, mamode='EMA')
    kosdaq['ADX'] = adx_data['ADX_14']
    kosdaq['DI'] = adx_data['DMP_14'] > adx_data['DMN_14']

    # 병렬 처리로 데이터 분석
    result_data = parallel_process_stocks(all_stocks, two_years_ago)
    result_data = result_data[result_data.index.date == today.date()]
    result_data = calculate_relative_strength(result_data)
    filtered_data = filter_common_stocks(result_data)
    final_data = filtered_data[buy_condition(filtered_data)]

    # Slack 메시지 전송
    send_to_slack(final_data, kospi, kosdaq)

  except Exception as e:
    print(f"Error in main execution: {e}")

  finally:
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"총 소요시간: {elapsed_time:.2f}초")