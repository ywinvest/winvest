import concurrent.futures
import os
import time
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
import pandas_ta as ta
import requests
from dotenv import load_dotenv
from pykrx.website.comm import webio

import rs
import woo1
import woo2

# 1. 공유 세션 생성 및 pykrx에 주입
_session = requests.Session()

def _session_post_read(self, **params):
  return _session.post(self.url, headers=self.headers, data=params)

def _session_get_read(self, **params):
  return _session.get(self.url, headers=self.headers, params=params)

webio.Post.read = _session_post_read
webio.Get.read = _session_get_read

def login_krx(login_id: str, login_pw: str) -> bool:
  """
  KRX data.krx.co.kr 로그인 후 세션 쿠키(JSESSIONID)를 갱신합니다.

  로그인 흐름:
    1. GET MDCCOMS001.cmd  → 초기 JSESSIONID 발급
    2. GET login.jsp       → iframe 세션 초기화
    3. POST MDCCOMS001D1.cmd → 실제 로그인
    4. CD011(중복 로그인) → skipDup=Y 추가 후 재전송
  """
  _LOGIN_PAGE = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
  _LOGIN_JSP  = "https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
  _LOGIN_URL  = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
  _UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
  )

  # 초기 세션 발급
  _session.get(_LOGIN_PAGE, headers={"User-Agent": _UA}, timeout=15)
  _session.get(_LOGIN_JSP, headers={"User-Agent": _UA, "Referer": _LOGIN_PAGE}, timeout=15)

  payload = {
    "mbrNm": "", "telNo": "", "di": "", "certType": "",
    "mbrId": login_id, "pw": login_pw,
  }
  headers = {"User-Agent": _UA, "Referer": _LOGIN_PAGE}

  # 로그인 POST
  resp = _session.post(_LOGIN_URL, data=payload, headers=headers, timeout=15)
  data = resp.json()
  error_code = data.get("_error_code", "")

  # CD011 중복 로그인 처리
  if error_code == "CD011":
    payload["skipDup"] = "Y"
    resp = _session.post(_LOGIN_URL, data=payload, headers=headers, timeout=15)
    data = resp.json()
    error_code = data.get("_error_code", "")

  return error_code == "CD001"  # CD001 = 정상


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
    # 0. 가장 먼저 KRX 로그인을 수행하여 _session에 쿠키를 확보합니다.
    # (data.krx.co.kr 에 가입된 실제 아이디와 비밀번호로 변경하세요)

    krx_id = os.getenv("KRX_ID")
    krx_pw = os.getenv("KRX_PW")

    print("0. KRX 정보데이터시스템 로그인 진행 중...")
    if not login_krx(krx_id, krx_pw):
      print("❌ KRX 로그인에 실패했습니다. 아이디와 비밀번호를 확인하세요.")
      exit()
    print("✅ KRX 로그인 성공! 세션 쿠키가 확보되었습니다.")

    # 1. woo2.py의 공통 함수를 호출하여 전 종목 기본 정보 및 시가총액 가져오기
    all_stocks = woo2.get_all_stocks()
    print(f"\n✅ 종목 정보 수집 완료! 총 {len(all_stocks)}개 종목")

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

    # 2. woo2.py의 공통 함수를 호출하여 지수 데이터 가져오기 (2003년 1월 1일부터)
    kospi, kosdaq = woo2.get_index_data("20150615")

    # kospi = fdr.DataReader('KS11')
    kospi['RSI'] = ta.rsi(kospi['Close'], length=14)
    adx_data = ta.adx(high=kospi['High'], low=kospi['Low'], close=kospi['Close'], length=14, mamode='EMA')
    kospi['ADX'] = adx_data['ADX_14']
    kospi['DI'] = adx_data['DMP_14'] > adx_data['DMN_14']
    kospi['MA5_Up'] = kospi['Close'] > kospi['Close'].rolling(window=5).mean()
    kospi['MA20_Up'] = kospi['Close'] > kospi['Close'].rolling(window=20).mean()
    kospi['MA60_Up'] = kospi['Close'] > kospi['Close'].rolling(window=60).mean()
    kospi['MA120_Up'] = kospi['Close'] > kospi['Close'].rolling(window=120).mean()

    # kosdaq = fdr.DataReader('KQ11')
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
