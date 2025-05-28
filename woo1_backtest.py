import concurrent.futures
import os
import time
from datetime import datetime, timedelta
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
import pandas_ta as ta
import requests
from dotenv import load_dotenv

import woo1

PARTIAL_TARGET_RETURN = 1.082
FULL_TARTET_RETURN = 1.10

# 매도 조건 함수들
def sell_condition_partial(df):
  return df['High'] >= df['Buy'] * PARTIAL_TARGET_RETURN

def sell_condition_full(df):
  return df['High'] >= df['Buy'] * FULL_TARTET_RETURN

def sell_condition_stop_loss(df):
  return df['Close'] < df['MA20']

def calculate_trading_days(df, start_date, end_date):
  """
  실제 거래일 기준으로 보유기간을 계산하는 함수

  Args:
      df (pandas.DataFrame): 주가 데이터
      start_date (datetime): 시작일
      end_date (datetime): 종료일

  Returns:
      int: 실제 거래일 수
  """
  if pd.isna(end_date):
    return None

  # start_date와 end_date 사이의 실제 거래일만 필터링
  trading_days = df.loc[start_date:end_date].index
  return len(trading_days) - 1  # 매수일 제외

def parallel_process_stocks(all_stocks):
  process_func = partial(process_stock)
  results = []

  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(process_func, row) for _, row in all_stocks.iterrows()]
    for future in concurrent.futures.as_completed(futures):
      result = future.result()
      if result is not None:
        results.append(result)

  return pd.concat(results) if results else pd.DataFrame()

def process_stock(row):
  ticker = row['Code']
  name = row['Name']
  marcap = row['Marcap']
  market = row['Market']
  try:
    # 종목 데이터 가져오기
    df = fdr.DataReader(ticker, "2004")
    df = woo1.calculate_indicators(df)

    # 매수 조건에 해당하는 데이터 필터링
    buys = df[woo1.buy_condition(df)]
    buys = buys[~buys.index.year.isin([2004])]  # 2004년 데이터 제외

    if not buys.empty:
      for buy_date in buys.index:
        df['Buy'] = buys.loc[buy_date, 'Close']
        buy_date_idx = df.index.get_loc(buy_date)
        data_1_5 = df.iloc[buy_date_idx + 1:buy_date_idx + 6]

        buy_price = df.loc[buy_date, 'Buy']

        partial_sell_date = None
        partial_sell_price = None

        # 1~5일차 (T+1~T+5)
        if not data_1_5.empty:
          target_open_sell = data_1_5[data_1_5['Open'] >= buy_price * PARTIAL_TARGET_RETURN]
          target_high_sell = data_1_5[(data_1_5['Open'] < buy_price * PARTIAL_TARGET_RETURN) & (data_1_5['High'] >= buy_price * PARTIAL_TARGET_RETURN)]

          open_sell_date = target_open_sell.index[0] if not target_open_sell.empty else None
          high_sell_date = target_high_sell.index[0] if not target_high_sell.empty else None

          if open_sell_date:
            partial_sell_date = open_sell_date
            partial_sell_price = data_1_5.loc[open_sell_date, 'Open']
          elif high_sell_date:
            partial_sell_date = high_sell_date
            partial_sell_price = buy_price * PARTIAL_TARGET_RETURN

        else:
          print(f"{name} buy in {buy_date}")

        # 6~22일차 (T+6~T+22)
        if not partial_sell_date:
          data_6_22 = df.iloc[buy_date_idx + 6:buy_date_idx + 23]

          if not data_6_22.empty:
            # 각 조건이 처음 발생하는 날짜 찾기
            target_open_sell = data_6_22[data_6_22['Open'] >= buy_price * PARTIAL_TARGET_RETURN]
            target_high_sell = data_6_22[(data_6_22['Open'] < buy_price * PARTIAL_TARGET_RETURN) & (data_6_22['High'] >= buy_price * PARTIAL_TARGET_RETURN)]
            stop_loss1 = data_6_22[(data_6_22['Close'] < df.loc[buy_date, 'Open']) & (data_6_22['Close'] < data_6_22['MA20']) & ~data_6_22['Bullish']]
            stop_loss2 = data_6_22[(data_6_22['Close'] <= buy_price * 0.92) & ((data_6_22['Close'] < df.loc[buy_date, 'Open']) | (data_6_22['Close'] < data_6_22['MA20'])) & ~data_6_22['Bullish']]

            # 각 조건의 첫 발생일 저장 (발생하지 않으면 None)
            open_sell_date = target_open_sell.index[0] if not target_open_sell.empty else None
            high_sell_date = target_high_sell.index[0] if not target_high_sell.empty else None
            stop_loss1_date = stop_loss1.index[0] if not stop_loss1.empty else None
            stop_loss2_date = stop_loss2.index[0] if not stop_loss2.empty else None

            # 발생한 날짜들 중 가장 빠른 날짜와 해당 조건 찾기
            valid_dates = [(d, 'open') for d in [open_sell_date] if d is not None] + \
                          [(d, 'high') for d in [high_sell_date] if d is not None] + \
                          [(d, 'stop2') for d in [stop_loss2_date] if d is not None] + \
                          [(d, 'stop1') for d in [stop_loss1_date] if d is not None]

            if valid_dates:
              earliest_date, condition = min(valid_dates, key=lambda x: x[0])

              if condition == 'open':
                partial_sell_date = earliest_date
                partial_sell_price = data_6_22.loc[earliest_date, 'Open']
              elif condition == 'high':
                partial_sell_date = earliest_date
                partial_sell_price = buy_price * PARTIAL_TARGET_RETURN
              elif condition == 'stop2':
                partial_sell_date = earliest_date
                partial_sell_price = data_6_22.loc[earliest_date, 'Close']
              else:  # condition == 'stop'
                partial_sell_date = earliest_date
                partial_sell_price = data_6_22.loc[earliest_date, 'Close']

        # 22일차 (T+22)
        if not partial_sell_date:
          final_data = df.iloc[buy_date_idx + 22:]
          if not final_data.empty:
            final_date = final_data.index[0] if not final_data.empty else None

            partial_sell_date = final_date
            partial_sell_price = final_data.loc[final_date, 'Close']
          else:
            print(f"{name} no sell condition met. {buy_date}, {buy_price}")

        # 매도 정보를 해당 행에 추가
        buys.loc[buy_date, 'Ticker'] = ticker
        buys.loc[buy_date, 'Name'] = name
        buys.loc[buy_date, 'Marcap'] = marcap
        buys.loc[buy_date, 'Buy_Date'] = buy_date
        buys.loc[buy_date, 'Buy_Price'] = buy_price
        buys.loc[buy_date, 'Partial_Sell_Date'] = partial_sell_date
        buys.loc[buy_date, 'Partial_Sell_Price'] = partial_sell_price
        buys.loc[buy_date, 'Full_Sell_Date'] = partial_sell_date
        buys.loc[buy_date, 'Full_Sell_Price'] = partial_sell_price

        # 보유기간 계산 (영업일 기준)
        if partial_sell_date:
          buys.loc[buy_date, 'Partial_Holding_Days'] = calculate_trading_days(df, buy_date, partial_sell_date)
          # 부분매도 수익률 계산 (%)
          buys.loc[buy_date, 'Partial_Return'] = ((partial_sell_price / buy_price) - 1)
          if market == 'KOSPI':
            buys.loc[buy_date, 'Index_RSI'] = kospi.loc[partial_sell_date, 'RSI']
          elif market == 'KOSDAQ':
            buys.loc[buy_date, 'Index_RSI'] = kosdaq.loc[partial_sell_date, 'RSI']
          buys.loc[buy_date, 'Full_Holding_Days'] = calculate_trading_days(df, buy_date, partial_sell_date)
          # 전량매도 수익률 계산 (%)
          buys.loc[buy_date, 'Full_Return'] = ((partial_sell_price / buy_price) - 1)
        else:
          buys.loc[buy_date, 'Partial_Holding_Days'] = None
          buys.loc[buy_date, 'Partial_Return'] = None
          buys.loc[buy_date, 'Index_RSI'] = None
          buys.loc[buy_date, 'Full_Holding_Days'] = None
          buys.loc[buy_date, 'Full_Return'] = None

      return buys
    return None
  except Exception as e:
    print(f"Error processing {ticker}: {e}")
    return None

def process_stock_complex(row):
  ticker = None
  if hasattr(row, 'Code'):
    ticker = row['Code']
  elif hasattr(row, 'Symbol'):
    ticker = row['Symbol']
  name = row['Name']
  marcap = None
  if hasattr(row, 'Marcap'):
    marcap = row['Marcap']

  market = row['Market']
  try:
    # 종목 데이터 가져오기
    df = fdr.DataReader(ticker, "2004")
    df = woo1.calculate_indicators(df)

    # 매수 조건에 해당하는 데이터 필터링
    buys = df[woo1.buy_condition(df)]
    buys = buys[~buys.index.year.isin([2004])]  # 2020년 데이터 제외

    if not buys.empty:
      for buy_date in buys.index:
        df['Buy'] = buys.loc[buy_date, 'Close']
        subsequent_data = df.loc[buy_date + timedelta(days=1):]

        buy_price = df.loc[buy_date, 'Buy']

        partial_sell_date = None
        full_sell_date = None
        partial_sell_price = None
        full_sell_price = None

        if not subsequent_data.empty:
          # 매수 다음 거래일 조건 확인
          next_day = subsequent_data.iloc[0]
          next_date = next_day.name

          # 시가가 10% 이상 형성되면 시가에 부분매도 및 전량매도
          if next_day['Open'] >= buy_price * FULL_TARTET_RETURN:
            partial_sell_date = next_date
            partial_sell_price = next_day['Open']
            full_sell_date = next_date
            full_sell_price = next_day['Open']
          # 시가가 5% 이상 형성되면 시가에 부분매도
          elif next_day['Open'] >= buy_price * PARTIAL_TARGET_RETURN:
            partial_sell_date = next_date
            partial_sell_price = next_day['Open']

          # 시가에 부분매도만 성공 시
          if partial_sell_date and not full_sell_date:
            # 고가가 10% 이상이면 10%에 전량매도
            if next_day['High'] >= buy_price * FULL_TARTET_RETURN:
              full_sell_date = next_date
              full_sell_price = buy_price * FULL_TARTET_RETURN

          # 시가에 매도 실패 시
          if not partial_sell_date and not full_sell_date:
            # 고가가 10% 이상이면 5%에 부분매도 및 10%에 전량매도
            if next_day['High'] >= buy_price * FULL_TARTET_RETURN:
              partial_sell_date = next_date
              partial_sell_price = buy_price * PARTIAL_TARGET_RETURN
              full_sell_date = next_date
              full_sell_price = buy_price * FULL_TARTET_RETURN
            # 고가가 5% 이상이면 5%에 부분매도
            elif next_day['High'] >= buy_price * PARTIAL_TARGET_RETURN:
              partial_sell_date = next_date
              partial_sell_price = buy_price * PARTIAL_TARGET_RETURN

          # 다음 거래일에 부분매도만 성공 시
          if partial_sell_date and not full_sell_date:
            remaining_data = subsequent_data.loc[next_date + timedelta(days=1):]

            # 두 조건의 발생일을 계산
            long_bullish = remaining_data[(remaining_data['Close'] / remaining_data['Open'] - 1) >= 0.10]
            stop_loss = remaining_data[sell_condition_stop_loss(remaining_data)]

            # 먼저 발생하는 조건 처리
            if not long_bullish.empty and not stop_loss.empty:
              if long_bullish.index[0] < stop_loss.index[0]:  # 장대양봉 먼저 발생
                full_sell_date = long_bullish.index[0]
                full_sell_price = remaining_data.loc[full_sell_date, 'Close']
              else:  # 20일선 이탈 먼저 발생
                full_sell_date = stop_loss.index[0]
                full_sell_price = remaining_data.loc[full_sell_date, 'Close']
            elif not long_bullish.empty:  # 장대양봉만 발생
              full_sell_date = long_bullish.index[0]
              full_sell_price = remaining_data.loc[full_sell_date, 'Close']
            elif not stop_loss.empty:  # 20일선 이탈만 발생
              full_sell_date = stop_loss.index[0]
              full_sell_price = remaining_data.loc[full_sell_date, 'Close']
            else:
              print(f"{name} no sell. {buy_date}, {buy_price}")
          # 다음 거래일에 매도 실패 시
          elif not partial_sell_date and not full_sell_date:
            remaining_data = subsequent_data.loc[next_date + timedelta(days=1):]

            # 매수일로부터 22일 후의 날짜 계산
            max_hold_date = None
            trading_days = 0
            for date in remaining_data.index:
              trading_days += 1
              if trading_days >= 21:
                max_hold_date = date
                break

            # 각 조건이 처음 발생하는 날짜 찾기
            target_open_sell = remaining_data[remaining_data['Open'] >= buy_price * PARTIAL_TARGET_RETURN]
            target_high_sell = remaining_data[(remaining_data['Open'] < buy_price * PARTIAL_TARGET_RETURN) & (remaining_data['High'] >= buy_price * PARTIAL_TARGET_RETURN)]
            stop_loss = remaining_data[(remaining_data['Close'] < df.loc[buy_date, 'Open']) & (remaining_data['Close'] < remaining_data['MA20'])]

            # 각 조건의 첫 발생일 저장 (발생하지 않으면 None)
            open_sell_date = target_open_sell.index[0] if not target_open_sell.empty else None
            high_sell_date = target_high_sell.index[0] if not target_high_sell.empty else None
            stop_loss_date = stop_loss.index[0] if not stop_loss.empty else None

            # 발생한 날짜들 중 가장 빠른 날짜와 해당 조건 찾기
            valid_dates = [(d, 'open') for d in [open_sell_date] if d is not None] + \
                          [(d, 'high') for d in [high_sell_date] if d is not None] + \
                          [(d, 'stop') for d in [stop_loss_date] if d is not None] + \
                          [(d, 'max_hold') for d in [max_hold_date] if d is not None]

            if valid_dates:
              earliest_date, condition = min(valid_dates, key=lambda x: x[0])

              if condition == 'open':
                # 시가 5% 이상 시 시가에 부분매도
                partial_sell_date = earliest_date
                partial_sell_price = remaining_data.loc[earliest_date, 'Open']
              elif condition == 'high':
                # 고가 5% 이상 시 5%에 부분매도
                partial_sell_date = earliest_date
                partial_sell_price = buy_price * PARTIAL_TARGET_RETURN
              elif condition == 'max_hold':
                # 25일 보유 제한에 도달 시 전량 매도
                partial_sell_date = earliest_date
                partial_sell_price = remaining_data.loc[earliest_date, 'Close']
                full_sell_date = earliest_date
                full_sell_price = remaining_data.loc[earliest_date, 'Close']
              else:  # condition == 'stop'
                # 손절 시 종가에 전량 매도
                partial_sell_date = earliest_date
                partial_sell_price = remaining_data.loc[earliest_date, 'Close']
                full_sell_date = earliest_date
                full_sell_price = remaining_data.loc[earliest_date, 'Close']
            else:
              print(f"{name} no sell condition met. {buy_date}, {buy_price}")

            # 2.3 부분매도 후 장대양봉 확인과 20일선 이탈 조건 중 먼저 발생하는 조건 처리
            if partial_sell_date and not full_sell_date:
              subsequent_after_partial = remaining_data.loc[partial_sell_date + timedelta(days=1):]

              # 두 조건의 발생일 계산
              strong_bullish = subsequent_after_partial[
                (subsequent_after_partial['Close'] / subsequent_after_partial['Open'] - 1) >= 0.10
                ]
              stop_loss = subsequent_after_partial[
                sell_condition_stop_loss(subsequent_after_partial)
              ]

              # 먼저 발생하는 조건 처리
              if not strong_bullish.empty and not stop_loss.empty:
                if strong_bullish.index[0] < stop_loss.index[0]:  # 장대양봉 먼저 발생
                  full_sell_date = strong_bullish.index[0]
                  full_sell_price = subsequent_after_partial.loc[full_sell_date, 'Close']
                else:  # 20일선 이탈 먼저 발생
                  full_sell_date = stop_loss.index[0]
                  full_sell_price = subsequent_after_partial.loc[full_sell_date, 'Close']
              elif not strong_bullish.empty:  # 장대양봉만 발생
                full_sell_date = strong_bullish.index[0]
                full_sell_price = subsequent_after_partial.loc[full_sell_date, 'Close']
              elif not stop_loss.empty:  # 20일선 이탈만 발생
                full_sell_date = stop_loss.index[0]
                full_sell_price = subsequent_after_partial.loc[full_sell_date, 'Close']
              # 여기까지 오면 문제있는 로직
              else:
                print(f"{name} no sell. {buy_date}, {buy_price}")
          # else:
          #   print(f"{name} full sell complete. {buy_date}, {buy_price}")
        else:
          print(f"{name} buy in {buy_date}")
        # 매도 정보를 해당 행에 추가
        buys.loc[buy_date, 'Ticker'] = ticker
        buys.loc[buy_date, 'Name'] = name
        buys.loc[buy_date, 'Marcap'] = marcap
        buys.loc[buy_date, 'Buy_Date'] = buy_date
        buys.loc[buy_date, 'Buy_Price'] = buy_price
        buys.loc[buy_date, 'Partial_Sell_Date'] = partial_sell_date
        buys.loc[buy_date, 'Partial_Sell_Price'] = partial_sell_price
        buys.loc[buy_date, 'Full_Sell_Date'] = full_sell_date
        buys.loc[buy_date, 'Full_Sell_Price'] = full_sell_price

        # 보유기간 계산 (영업일 기준)
        if partial_sell_date:
          buys.loc[buy_date, 'Partial_Holding_Days'] = calculate_trading_days(df, buy_date, partial_sell_date)
          # 부분매도 수익률 계산 (%)
          buys.loc[buy_date, 'Partial_Return'] = ((partial_sell_price / buy_price) - 1)
          if market == 'KOSPI':
            buys.loc[buy_date, 'Index_RSI'] = kospi.loc[partial_sell_date, 'RSI']
          elif market == 'KOSDAQ':
            buys.loc[buy_date, 'Index_RSI'] = kosdaq.loc[partial_sell_date, 'RSI']
        else:
          buys.loc[buy_date, 'Partial_Holding_Days'] = None
          buys.loc[buy_date, 'Partial_Return'] = None
          buys.loc[buy_date, 'Index_RSI'] = None

        if full_sell_date:
          buys.loc[buy_date, 'Full_Holding_Days'] = calculate_trading_days(df, buy_date, full_sell_date)
          # 전량매도 수익률 계산 (%)
          buys.loc[buy_date, 'Full_Return'] = ((full_sell_price / buy_price) - 1)
        else:
          buys.loc[buy_date, 'Full_Holding_Days'] = None
          buys.loc[buy_date, 'Full_Return'] = None
      return buys
    return None
  except Exception as e:
    print(f"Error processing {ticker}: {e}")
    return None

def upload_to_github_releases(file_path, release_tag="v1.0.0"):
  """
  GitHub Releases 에 파일 업로드
  Args:
      file_path (str): 업로드할 파일 경로
      release_tag (str): 릴리즈 태그 이름
  """
  # 설정 로드
  # with open("config-woo1.json", "r") as config_file:
  #   config = json.load(config_file)

  # GitHub 설정
  # token = config["github_token"]
  # api_url = config["github_api_url"]
  token = os.getenv("RELEASE_TOKEN")
  api_url = os.getenv("RELEASE_API_URL")

  # 파일 이름 추출
  file_name = os.path.basename(file_path)

  # 1. 릴리즈 생성
  headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github.v3+json"
  }
  data = {
    "tag_name": release_tag,
    "name": release_tag,
    "body": f"Uploading {file_name} via script",
    "draft": False,
    "prerelease": False
  }

  response = requests.post(api_url, headers=headers, json=data)
  if response.status_code != 201:
    raise Exception(f"Failed to create release: {response.json()}")

  release = response.json()
  upload_url = release["upload_url"].split("{")[0]  # 업로드 URL 추출

  # 2. 파일 업로드
  with open(file_path, "rb") as f:
    file_data = f.read()
  upload_headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "text/csv"
  }
  upload_params = {"name": file_name}
  upload_response = requests.post(upload_url, headers=upload_headers, params=upload_params, data=file_data)

  if upload_response.status_code not in [200, 201]:
    raise Exception(f"Failed to upload asset: {upload_response.json()}")

  print(f"File '{file_name}' uploaded successfully to release '{release_tag}'.")

if __name__ == "__main__":
  start_time = time.time()

  # .env 파일 로드
  load_dotenv()

  try:
    # delisting = fdr.StockListing('KRX-DELISTING') # 3천+ 종목 - 상장폐지 종목 전체
    # admin = fdr.StockListing('KRX-ADMIN') # 50+ 종목 - KRX 관리종목

    # 종목 리스트 가져오기 및 필터링
    all_stocks = pd.concat([
      woo1.filter_common_stocks(fdr.StockListing('KOSPI').tail(-100)),
      woo1.filter_common_stocks(fdr.StockListing('KOSDAQ'))
    ], ignore_index=True)

    kospi = fdr.DataReader('KS11')
    kospi['RSI'] = ta.rsi(kospi['Close'], length=14)

    kosdaq = fdr.DataReader('KQ11')
    kosdaq['RSI'] = ta.rsi(kosdaq['Close'], length=14)

    result_file = "woo1_backtest_result.csv"

    # 병렬 처리로 데이터 분석
    result_data = parallel_process_stocks(all_stocks)
    result_data.to_csv(result_file, index=False, encoding='utf-8-sig')

    # 업로드 파일 경로
    # release_tag = f"woo1-{datetime.now().strftime("%Y%m%d")}"
    # 파일 업로드 실행
    # upload_to_github_releases(result_file, release_tag)
  except Exception as e:
    print(f"Error in main execution: {e}")

  finally:
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"총 소요시간: {elapsed_time:.2f}초")
