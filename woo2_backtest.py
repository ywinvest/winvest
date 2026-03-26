import concurrent.futures
import os
import time
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv

import krx_auth
import rs
import woo1
import woo2


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
  code = row['Code']
  name = row['Name']
  marcap = row['Marcap']
  market = row['Market']
  listing_date = row['ListingDate']  # all_stocks에서 상장일 가져오기

  try:
    # 종목 데이터 가져오기
    df = fdr.DataReader(code, "2014")

    # 상장일 이전 데이터 제거
    if not pd.isna(listing_date):
      df = df[df.index >= listing_date]

    # 상장일 이후 데이터가 없으면 처리 중단
    if df.empty:
      print(f"No data after listing date for {code}")
      return None

    df = woo2.calculate_indicators(df)

    if not df.empty:
      df['Code'] = code
      df['Name'] = name
      df['Marcap'] = marcap
      df['Market'] = market
      return df
    return None
  except Exception as e:
    print(f"Error processing {code}: {e}")
    return None

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

    all_stocks = pd.concat([
      fdr.StockListing('KOSPI'),
      fdr.StockListing('KOSDAQ')
    ], ignore_index=True)

    # 상장일 정보 가져오기
    df_listing = fdr.StockListing('KRX-DESC', "2014")[['Code', 'ListingDate']]
    # url = 'http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'
    # headers = {
    #   'User-Agent': 'Chrome/78.0.3904.87 Safari/537.36',
    #   'Referer': 'http://data.krx.co.kr/'
    # }
    # r = requests.get(url, headers)
    # dfs = pd.read_html(io.StringIO(r.text), header=0)
    # df_listing = dfs[0]
    # cols_ren = {'종목코드': 'Code', '상장일': 'ListingDate'}
    # df_listing = df_listing.rename(columns = cols_ren)
    # df_listing['Code'] = df_listing['Code'].apply(lambda x: x.zfill(6))
    # df_listing['ListingDate'] = pd.to_datetime(df_listing['ListingDate'])

    all_stocks = all_stocks.merge(df_listing, on='Code', how='left')

    kospi = fdr.DataReader('KS11')
    kospi['Change'] = kospi['Close'].pct_change()
    kospi['RSI'] = ta.rsi(kospi['Close'], length=14)
    adx_data = ta.adx(high=kospi['High'], low=kospi['Low'], close=kospi['Close'], length=14, mamode='EMA')
    kospi['ADX'] = adx_data['ADX_14']
    kospi['DI'] = adx_data['DMP_14'] > adx_data['DMN_14']
    kospi['MA5_Up'] = kospi['Close'] > kospi['Close'].rolling(window=5).mean()
    kospi['MA20_Up'] = kospi['Close'] > kospi['Close'].rolling(window=20).mean()
    kospi['MA60_Up'] = kospi['Close'] > kospi['Close'].rolling(window=60).mean()
    kospi['MA120_Up'] = kospi['Close'] > kospi['Close'].rolling(window=120).mean()

    kosdaq = fdr.DataReader('KQ11')
    kosdaq['Change'] = kosdaq['Close'].pct_change()
    kosdaq['RSI'] = ta.rsi(kosdaq['Close'], length=14)
    adx_data = ta.adx(high=kosdaq['High'], low=kosdaq['Low'], close=kosdaq['Close'], length=14, mamode='EMA')
    kosdaq['ADX'] = adx_data['ADX_14']
    kosdaq['DI'] = adx_data['DMP_14'] > adx_data['DMN_14']
    kosdaq['MA5_Up'] = kosdaq['Close'] > kosdaq['Close'].rolling(window=5).mean()
    kosdaq['MA20_Up'] = kosdaq['Close'] > kosdaq['Close'].rolling(window=20).mean()
    kosdaq['MA60_Up'] = kosdaq['Close'] > kosdaq['Close'].rolling(window=60).mean()
    kosdaq['MA120_Up'] = kosdaq['Close'] > kosdaq['Close'].rolling(window=120).mean()

    result_file = "woo2_backtest_results.csv"

    # 병렬 처리로 데이터 분석
    result_data = parallel_process_stocks(all_stocks)
    result_data = rs.calculate_relative_strength(result_data)
    filtered_data = woo1.filter_common_stocks(result_data)

    last_trading_day = result_data.index.max()
    if last_trading_day:
      today_rs_data = result_data[result_data.index == last_trading_day].copy()
      today_rs_data = woo2.filter_common_stocks(today_rs_data)
      today_rs_data['Marcap(억)'] = (today_rs_data['Marcap'] / 100_000_000).round(0).astype(int)
      rs_report = today_rs_data.drop(columns=['Marcap'])
      rs_cols = ['Code', 'Name', 'Market', 'Marcap(억)', 'RS', 'RS_1M', 'RS_3M', 'RS_6M', 'RS_12M']
      rs_report = today_rs_data[rs_cols].sort_values(
          by=['RS', 'RS_1M', 'RS_3M', 'RS_6M', 'RS_12M'],
          ascending=False
      )
      filename = f"rs_{last_trading_day.strftime('%Y%m%d')}.xlsx"
      rs_report.to_excel(filename, index=False)

    result_data = woo2.buy_and_sell(filtered_data, kospi, kosdaq)
    # final_data = result_data[buy_condition(result_data)]
    result_data.to_csv(result_file, index=False, encoding='utf-8-sig')
  except Exception as e:
    print(f"Error in main execution: {e}")

  finally:
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"총 소요시간: {elapsed_time:.2f}초")
