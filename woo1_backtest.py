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

import krx_auth
import woo1

TARGET_RETURN = 1.082

# 매도 조건 함수들
def sell_condition(df):
  return df['High'] >= df['Buy'] * TARGET_RETURN

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
    df = fdr.DataReader(ticker, "2014")
    df = woo1.calculate_indicators(df)

    # 매수 조건에 해당하는 데이터 필터링
    buys = df[woo1.buy_condition(df)]
    buys = buys[buys.index >= '2015-06-15']
    # buys = buys[~buys.index.year.isin([2014])]  # 2004년 데이터 제외

    if not buys.empty:
      for buy_date in buys.index:
        df['Buy'] = buys.loc[buy_date, 'Close']
        buy_date_idx = df.index.get_loc(buy_date)
        data_1 = df.iloc[buy_date_idx + 1:]

        buy_price = df.loc[buy_date, 'Buy']
        current_price = df['Close'].iloc[-1]
        estimated_marcap = marcap * (buy_price / current_price)

        sell_date = None
        sell_price = None

        buy_index_rsi = None
        buy_index_ma5_up = None
        buy_index_ma20_up = None
        buy_index_adx = None
        buy_index_di = None

        buy_kospi_ma5_up = None
        buy_kospi_ma20_up = None
        buy_kospi_ma60_up = None
        buy_kospi_ma120_up = None
        buy_kospi_adx = None
        buy_kospi_di = None

        buy_kosdaq_ma5_up = None
        buy_kosdaq_ma20_up = None
        buy_kosdaq_ma60_up = None
        buy_kosdaq_ma120_up = None
        buy_kosdaq_adx = None
        buy_kosdaq_di = None

        # 매수일 KOSPI 지표 저장
        if buy_date in kospi.index:
          buy_kospi_ma5_up = kospi.loc[buy_date, 'MA5_Up']
          buy_kospi_ma20_up = kospi.loc[buy_date, 'MA20_Up']
          buy_kospi_ma60_up = kospi.loc[buy_date, 'MA60_Up']
          buy_kospi_ma120_up = kospi.loc[buy_date, 'MA120_Up']
          buy_kospi_adx = kospi.loc[buy_date, 'ADX']
          buy_kospi_di = kospi.loc[buy_date, 'DI']

        # 매수일 KOSPI 지표 저장
        if buy_date in kosdaq.index:
          buy_kosdaq_ma5_up = kosdaq.loc[buy_date, 'MA5_Up']
          buy_kosdaq_ma20_up = kosdaq.loc[buy_date, 'MA20_Up']
          buy_kosdaq_ma60_up = kosdaq.loc[buy_date, 'MA60_Up']
          buy_kosdaq_ma120_up = kosdaq.loc[buy_date, 'MA120_Up']
          buy_kosdaq_adx = kosdaq.loc[buy_date, 'ADX']
          buy_kosdaq_di = kosdaq.loc[buy_date, 'DI']

        # 매수일 시장지수 저장
        source_df = None
        if market == 'KOSPI':
          source_df = kospi
        elif market in ['KOSDAQ', 'KOSDAQ GLOBAL']:
          source_df = kosdaq

        if source_df is not None and buy_date in source_df.index:
          buy_index_rsi = source_df.loc[buy_date, 'RSI']
          buy_index_ma5_up = source_df.loc[buy_date, 'MA5_Up']
          buy_index_ma20_up = source_df.loc[buy_date, 'MA20_Up']
          buy_index_adx = source_df.loc[buy_date, 'ADX']
          buy_index_di = source_df.loc[buy_date, 'DI']

        # 1일차 (T+1)
        if not data_1.empty:
          # 매수 다음 거래일 조건 확인
          next_day = data_1.iloc[0]
          next_date = next_day.name

          # 시가가 TARGET_RETURN 이상 형성되면 시가에 매도
          if next_day['Open'] >= buy_price * TARGET_RETURN:
            sell_date = next_date
            sell_price = next_day['Open']

          # 시가에 매도 실패 시
          if not sell_date:
            # 고가가 TARGET_RETURN 이상이면 TARGET_RETURN 에 매도
            if next_day['High'] >= buy_price * TARGET_RETURN:
              sell_date = next_date
              sell_price = buy_price * TARGET_RETURN
        else:
          print(f"{name} buy in {buy_date}")

        # 2~22일차 (T+2~T+22)
        if not sell_date:
          data_2_22 = df.iloc[buy_date_idx + 2:buy_date_idx + 23]

          if not data_2_22.empty:
            # 각 조건이 처음 발생하는 날짜 찾기
            target_open_sell = data_2_22[data_2_22['Open'] >= buy_price * TARGET_RETURN]
            target_high_sell = data_2_22[(data_2_22['Open'] < buy_price * TARGET_RETURN) & (data_2_22['High'] >= buy_price * TARGET_RETURN)]
            stop_loss1 = data_2_22[(data_2_22['Close'] < df.loc[buy_date, 'Open']) & (data_2_22['Close'] < data_2_22['MA20']) & ~data_2_22['Bullish']]
            stop_loss2 = data_2_22[(data_2_22['Close'] <= buy_price * 0.92) & ((data_2_22['Close'] < df.loc[buy_date, 'Open']) | (data_2_22['Close'] < data_2_22['MA20'])) & ~data_2_22['Bullish']]

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
                sell_date = earliest_date
                sell_price = data_2_22.loc[earliest_date, 'Open']
              elif condition == 'high':
                sell_date = earliest_date
                sell_price = buy_price * TARGET_RETURN
              elif condition == 'stop2':
                sell_date = earliest_date
                sell_price = data_2_22.loc[earliest_date, 'Close']
              else:  # condition == 'stop'
                sell_date = earliest_date
                sell_price = data_2_22.loc[earliest_date, 'Close']

        # 22일차 (T+22)
        if not sell_date:
          final_data = df.iloc[buy_date_idx + 22:]
          if not final_data.empty:
            final_date = final_data.index[0] if not final_data.empty else None

            sell_date = final_date
            sell_price = final_data.loc[final_date, 'Close']
          else:
            print(f"{name} no sell condition met. {buy_date}, {buy_price}")

        # 매도 정보를 해당 행에 추가
        buys.loc[buy_date, 'Ticker'] = ticker
        buys.loc[buy_date, 'Name'] = name
        buys.loc[buy_date, 'Marcap'] = marcap
        buys.loc[buy_date, 'Estimated_Marcap'] = estimated_marcap
        buys.loc[buy_date, 'Buy_Date'] = buy_date
        buys.loc[buy_date, 'Buy_Price'] = buy_price
        buys.loc[buy_date, 'Sell_Date'] = sell_date
        buys.loc[buy_date, 'Sell_Price'] = sell_price

        # KOSPI 지표 추가
        buys.loc[buy_date, 'Buy_Kospi_MA5_Up'] = buy_kospi_ma5_up
        buys.loc[buy_date, 'Buy_Kospi_MA20_Up'] = buy_kospi_ma20_up
        buys.loc[buy_date, 'Buy_Kospi_MA60_Up'] = buy_kospi_ma60_up
        buys.loc[buy_date, 'Buy_Kospi_MA120_Up'] = buy_kospi_ma120_up
        buys.loc[buy_date, 'Buy_Kospi_ADX'] = buy_kospi_adx
        buys.loc[buy_date, 'Buy_Kospi_DI'] = buy_kospi_di

        # KOSDAQ 지표 추가
        buys.loc[buy_date, 'Buy_Kosdaq_MA5_Up'] = buy_kosdaq_ma5_up
        buys.loc[buy_date, 'Buy_Kosdaq_MA20_Up'] = buy_kosdaq_ma20_up
        buys.loc[buy_date, 'Buy_Kosdaq_MA60_Up'] = buy_kosdaq_ma60_up
        buys.loc[buy_date, 'Buy_Kosdaq_MA120_Up'] = buy_kosdaq_ma120_up
        buys.loc[buy_date, 'Buy_Kosdaq_ADX'] = buy_kosdaq_adx
        buys.loc[buy_date, 'Buy_Kosdaq_DI'] = buy_kosdaq_di

        # 보유기간 계산 (영업일 기준)
        if sell_date:
          buys.loc[buy_date, 'Holding_Days'] = calculate_trading_days(df, buy_date, sell_date)
          # 부분매도 수익률 계산 (%)
          buys.loc[buy_date, 'Return'] = ((sell_price / buy_price) - 1)
        else:
          buys.loc[buy_date, 'Holding_Days'] = None
          buys.loc[buy_date, 'Return'] = None

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

    krx_id = os.getenv("KRX_ID")
    krx_pw = os.getenv("KRX_PW")

    print("0. KRX 정보데이터시스템 로그인 진행 중...")
    if not krx_auth.login_krx(krx_id, krx_pw):
      print("❌ KRX 로그인에 실패했습니다. 아이디와 비밀번호를 확인하세요.")
      exit()
    print("✅ KRX 로그인 성공! 세션 쿠키가 확보되었습니다.")

    # 종목 리스트 가져오기 및 필터링
    all_stocks = pd.concat([
      woo1.filter_common_stocks(fdr.StockListing('KOSPI').tail(-100)),
      woo1.filter_common_stocks(fdr.StockListing('KOSDAQ'))
    ], ignore_index=True)

    # KOSPI, KOSDAQ 지수 데이터 로드 및 지표 계산
    kospi = fdr.DataReader('KS11')
    kospi['RSI'] = ta.rsi(kospi['Close'], length=14)
    adx_data = ta.adx(high=kospi['High'], low=kospi['Low'], close=kospi['Close'], length=14, mamode='EMA')
    kospi['ADX'] = adx_data['ADX_14']
    kospi['DI'] = adx_data['DMP_14'] > adx_data['DMN_14']
    kospi['MA5_Up'] = kospi['Close'] > kospi['Close'].rolling(window=5).mean()
    kospi['MA20_Up'] = kospi['Close'] > kospi['Close'].rolling(window=20).mean()
    kospi['MA60_Up'] = kospi['Close'] > kospi['Close'].rolling(window=60).mean()
    kospi['MA120_Up'] = kospi['Close'] > kospi['Close'].rolling(window=120).mean()

    kosdaq = fdr.DataReader('KQ11')
    kosdaq['RSI'] = ta.rsi(kosdaq['Close'], length=14)
    adx_data = ta.adx(high=kosdaq['High'], low=kosdaq['Low'], close=kosdaq['Close'], length=14, mamode='EMA')
    kosdaq['ADX'] = adx_data['ADX_14']
    kosdaq['DI'] = adx_data['DMP_14'] > adx_data['DMN_14']
    kosdaq['MA5_Up'] = kosdaq['Close'] > kosdaq['Close'].rolling(window=5).mean()
    kosdaq['MA20_Up'] = kosdaq['Close'] > kosdaq['Close'].rolling(window=20).mean()
    kosdaq['MA60_Up'] = kosdaq['Close'] > kosdaq['Close'].rolling(window=60).mean()
    kosdaq['MA120_Up'] = kosdaq['Close'] > kosdaq['Close'].rolling(window=120).mean()

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
