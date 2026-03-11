import concurrent.futures
import os
import time
from datetime import datetime
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
from dotenv import load_dotenv
from pykrx import stock

import krx_auth
from slack_utils import SlackMessageBuilder, send_slack_message


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
  conditions &= (df['Change'] > 0)
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

def format_market_cap(marcap):
  """시가총액을 조 또는 억 단위로 포맷팅"""
  if marcap >= 1e12:  # 1조 이상
    return f"{marcap/1e12:.1f}조"
  else:  # 억 단위
    return f"{marcap/1e8:.0f}억"

def send_to_slack(result_data):
  try:
    token = os.getenv("SLACK_BOT_TOKEN")
    channel = os.getenv("SLACK_CHANNEL")

    builder = SlackMessageBuilder()

    if result_data.empty:
      builder.add_line("오늘은 매수 후보가 없습니다.")
      send_slack_message(builder.build(), token, channel)
      print("No stocks match the buying conditions")
      return

    # 결과를 Market과 High_Change를 기준으로 정렬
    result_data = result_data.sort_values(['Market', 'High_Change'], ascending=[True, False])

    builder.add_line(f" {today.year}년 {today.month}월 {today.day}일 매수 후보", bold=True)
    if today.weekday() == 3: # 월=0, 화=1, 수=2, 목=3
      builder.add_line(f" 목요일이니 매수에 유의하세요!", emoji="warning", bold=True, italic=True)
    # 시장별로 데이터 구성
    for market, group in result_data.groupby('Market'):
      for _, row in group.iterrows():
        name = row['Name']
        change = row['Change']
        high_change = row['High_Change']
        marcap = row['Marcap']
        volume_change = row['Volume_Change']
        open = row['Open']
        close = row['Close']
        high = row['High']
        diff_high_close = (high - close) / close
        diff_close_open = (close - open) / open

        message = f"{name}({format_market_cap(marcap)}) 고 {high_change:.2f}%, 고-종 {diff_high_close * 100:.2f}%, 거래량 {volume_change * 100:.2f}%"

        if high_change >= 10 and volume_change > 5:
          # 위꼬리 짧을 때 (0~2%)
          if diff_high_close >= 0 and diff_high_close <= 0.02:
            builder.add_line(f" {message}", emoji="first_place_medal")
          # 위꼬리 길 때 (10% 초과)
          elif diff_high_close > 0.1: #and diff_close_open >= 0.01:
            builder.add_line(f" {message}", emoji="second_place_medal")
        else:
          builder.add_line(f" {message}", emoji="question")

    # Slack 메시지 전송
    send_slack_message(builder.build(), token, channel)

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

def get_all_stocks():
  """pykrx를 활용하여 KOSPI/KOSDAQ 전 종목의 기본 정보와 시가총액을 반환합니다."""
  print("1. pykrx를 활용하여 전 종목 기본 데이터 및 시가총액 수집 중...")

  today_str = datetime.today().strftime("%Y%m%d")

  # 1. 가장 최근 영업일 확인 (세션 패치가 적용된 상태에서 실행됨)
  latest_b_day = stock.get_nearest_business_day_in_a_week(today_str)

  # 2. KOSPI, KOSDAQ 시가총액 데이터를 가져오면서 티커(Code) 확보
  df_kospi = stock.get_market_cap(latest_b_day, market="KOSPI").reset_index()
  df_kospi['Market'] = 'KOSPI'

  df_kosdaq = stock.get_market_cap(latest_b_day, market="KOSDAQ").reset_index()
  df_kosdaq['Market'] = 'KOSDAQ'

  # 3. 두 시장 데이터 병합
  all_stocks = pd.concat([df_kospi, df_kosdaq], ignore_index=True)

  # 4. pykrx 내장 함수를 사용하여 티커를 종목명(Name)으로 변환
  # (내부적으로 캐싱된 마스터 데이터를 사용하므로 수천 개를 변환해도 1초 이내에 완료됨)
  all_stocks['Name'] = all_stocks['티커'].apply(stock.get_market_ticker_name)

  # 5. 필요한 컬럼만 추출하고 이름 변경 ('티커' -> 'Code', '시가총액' -> 'Marcap')
  all_stocks = all_stocks[['티커', 'Name', 'Market', '시가총액']].rename(
      columns={'티커': 'Code', '시가총액': 'Marcap'}
  )

  # 결측치(NaN) 처리: 시가총액이 없는 종목은 0으로 처리
  all_stocks['Marcap'] = all_stocks['Marcap'].fillna(0).astype(int)

  return all_stocks


def get_index_data(start_str, end_str=None):
  """pykrx를 활용하여 KOSPI와 KOSDAQ의 지수 OHLCV 데이터를 반환합니다."""
  if end_str is None:
    end_str = datetime.today().strftime("%Y%m%d")

  print(f"지수 데이터(KOSPI, KOSDAQ) 수집 중... ({start_str} ~ {end_str})")

  # KOSPI (1001)
  kospi = stock.get_index_ohlcv(start_str, end_str, "1001")
  kospi = kospi.rename(columns={'시가': 'Open', '고가': 'High', '저가': 'Low', '종가': 'Close', '거래량': 'Volume'})

  # KOSDAQ (2001)
  kosdaq = stock.get_index_ohlcv(start_str, end_str, "2001")
  kosdaq = kosdaq.rename(columns={'시가': 'Open', '고가': 'High', '저가': 'Low', '종가': 'Close', '거래량': 'Volume'})

  return kospi, kosdaq

if __name__ == "__main__":
  start_time = time.time()

  # .env 파일 로드
  load_dotenv()

  try:
    # 종목 리스트 가져오기 및 필터링
    # all_stocks = pd.concat([
    #   filter_common_stocks(fdr.StockListing('KOSPI').tail(-100)),
    #   filter_common_stocks(fdr.StockListing('KOSDAQ'))
    # ], ignore_index=True)

    # 날짜 설정
    today = datetime.today()
    # two_years_ago = today.year - 2

    krx_id = os.getenv("KRX_ID")
    krx_pw = os.getenv("KRX_PW")

    print("0. KRX 정보데이터시스템 로그인 진행 중...")
    if not krx_auth.login_krx(krx_id, krx_pw):
      print("❌ KRX 로그인에 실패했습니다. 아이디와 비밀번호를 확인하세요.")
      exit()
    print("✅ KRX 로그인 성공! 세션 쿠키가 확보되었습니다.")

    # 1. 전 종목 기본 정보 및 시가총액 가져오기
    all_stocks = get_all_stocks()
    print(f"\n✅ 종목 정보 수집 완료! 총 {len(all_stocks)}개 종목")

    # 윤달(2월 29일) 방어 로직 포함
    try:
      two_years_ago = today.replace(year=today.year - 2)
    except ValueError:
      two_years_ago = today.replace(year=today.year - 2, day=28)

    start_str = two_years_ago.strftime("%Y%m%d")

    # 2. woo2.py의 공통 함수를 호출하여 지수 데이터 가져오기 (2003년 1월 1일부터)
    kospi, kosdaq = get_index_data(start_str)

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