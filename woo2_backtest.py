import concurrent.futures
import io
import time
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
import pandas_ta as ta
import requests
from dotenv import load_dotenv

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

    kospi = fdr.StockListing('KOSPI')
    kosdaq = fdr.StockListing('KOSDAQ')
    all_stocks = pd.concat([kospi, kosdaq], ignore_index=True)

    # 상장일 정보 가져오기
    # krx_desc = fdr.StockListing('KRX-DESC', "2014")[['Code', 'ListingDate']]
    url = 'http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'
    headers = {
      'User-Agent': 'Chrome/78.0.3904.87 Safari/537.36',
      'Referer': 'http://data.krx.co.kr/'
    }
    r = requests.get(url, headers)
    dfs = pd.read_html(io.StringIO(r.text), header=0)
    df_listing = dfs[0]
    cols_ren = {'종목코드': 'Code', '상장일': 'ListingDate'}
    df_listing = df_listing.rename(columns = cols_ren)
    df_listing['Code'] = df_listing['Code'].apply(lambda x: x.zfill(6))
    df_listing['ListingDate'] = pd.to_datetime(df_listing['ListingDate'])

    all_stocks = all_stocks.merge(df_listing, on='Code', how='left')

    kospi = fdr.DataReader('KS11')
    kospi['RSI'] = ta.rsi(kospi['Close'], length=14)
    adx_data = ta.adx(high=kospi['High'], low=kospi['Low'], close=kospi['Close'], length=14, mamode='EMA')
    kospi['ADX'] = adx_data['ADX_14']
    kospi['DI'] = adx_data['DMP_14'] > adx_data['DMN_14']
    kospi['MA20_Up'] = kospi['Close'] > kospi['Close'].rolling(window=20).mean()

    kosdaq = fdr.DataReader('KQ11')
    kosdaq['RSI'] = ta.rsi(kosdaq['Close'], length=14)
    adx_data = ta.adx(high=kosdaq['High'], low=kosdaq['Low'], close=kosdaq['Close'], length=14, mamode='EMA')
    kosdaq['ADX'] = adx_data['ADX_14']
    kosdaq['DI'] = adx_data['DMP_14'] > adx_data['DMN_14']
    kosdaq['MA20_Up'] = kosdaq['Close'] > kosdaq['Close'].rolling(window=20).mean()

    result_file = "woo2_backtest_results.csv"

    # 병렬 처리로 데이터 분석
    result_data = parallel_process_stocks(all_stocks)
    result_data = rs.calculate_relative_strength(result_data)
    filtered_data = woo1.filter_common_stocks(result_data)
    result_data = woo2.buy_and_sell(filtered_data, kospi, kosdaq)
    # final_data = result_data[buy_condition(result_data)]
    result_data.to_csv(result_file, index=False, encoding='utf-8-sig')
  except Exception as e:
    print(f"Error in main execution: {e}")

  finally:
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"총 소요시간: {elapsed_time:.2f}초")
