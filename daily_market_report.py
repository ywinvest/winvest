import concurrent.futures
import time
import os
from datetime import datetime, timedelta
from functools import partial

import pandas as pd
import FinanceDataReader as fdr
from dotenv import load_dotenv

# 로컬 모듈 임포트
import rs
import krx_auth
import market  # 분리된 시장 분석 모듈

# 시장 신호 매핑 딕셔너리
SIGNAL_MAP = {
  "green": "양호🟢",
  "yellow": "주의🟡",
  "red": "경고🔴"
}

def get_market_status(market_code):
  """시장 지수(종가, 등락률) 및 어제/오늘 신호 전환 여부 파악하여 문자열로 반환"""
  start_date = (datetime.today() - timedelta(days=100)).strftime('%Y-%m-%d')
  df = fdr.DataReader(market_code, start_date)
  df = market.add_indicators(df.dropna())

  # 당일 데이터 추출
  today_data = df.iloc[-1]
  today_close = today_data['Close']
  today_change = today_data['Change']

  # 당일 및 전일 신호 평가 (green, yellow, red 반환)
  today_signal_raw = market.get_signal(
      today_data['MA20_Up'], today_data['ADX'], today_data['DI'], today_data['MA5_Up']
  )
  yesterday_data = df.iloc[-2]
  yesterday_signal_raw = market.get_signal(
      yesterday_data['MA20_Up'], yesterday_data['ADX'], yesterday_data['DI'], yesterday_data['MA5_Up']
  )

  # UI용 텍스트 변환
  today_signal = SIGNAL_MAP[today_signal_raw]
  yesterday_signal = SIGNAL_MAP[yesterday_signal_raw]

  # 신호 유지/전환 메시지 생성
  if today_signal == yesterday_signal:
    status_msg = f"{today_signal} 유지"
  else:
    status_msg = f"{yesterday_signal} ➡ {today_signal} 전환"

  return f"{today_close:,.2f} ({today_change * 100:+.2f}%), 시스템 신호: {status_msg}", today_change

def format_market_cap(marcap):
  """시가총액을 조 또는 억 단위로 보기 좋게 포맷팅"""
  if pd.isna(marcap) or marcap == 0:
    return "시총정보없음"
  if marcap >= 1e12:  # 1조 이상
    return f"{marcap/1e12:.1f}조"
  else:  # 억 단위
    return f"{marcap/1e8:.0f}억"

def filter_common_stocks(df):
  # 스팩 제외
  exclude_pattern = r'스팩'
  return df[(~df['Name'].str.contains(exclude_pattern, na=False, regex=True))
            & (~df['Code'].str.endswith(("5", "7", "9", "K", "L", "M", "N", "O"))) # 우선주, 일부 ETN/ETF 등 제외
            & (df['Marcap'] >= 200_000_000_000)
            ]

def process_stock(row, start_date):
  """종목별 개별 주가 데이터 수집 및 RS 기초 지표 계산"""
  try:
    code = row['Code']
    market = row['Market']
    name = row['Name']
    chages_ratio = row['ChagesRatio']  # 원본 등락률
    marcap = row['Marcap']  # 시가총액

    df = fdr.DataReader(code, start_date)
    if df.empty:
      return None

    # rs.py의 지표 계산 함수 호출
    df = rs.calculate_indicators(df)

    df['Code'] = code
    df['Name'] = name
    df['Market'] = market
    df['ChagesRatio'] = chages_ratio
    df['Marcap'] = marcap

    return df.iloc[[-1]]
  except Exception:
    return None

def get_pykrx_market_listing(market):
  """FinanceDataReader의 StockListing을 대체하는 pykrx 기반 데이터 수집 함수"""
  from pykrx import stock
  from pykrx.website.krx.market.wrap import get_market_ticker_and_name
  from datetime import datetime
  import pandas as pd

  date = datetime.today().strftime('%Y%m%d')
  
  df_ohlcv = stock.get_market_ohlcv(date, market=market)
  sr_name = get_market_ticker_and_name(date, market=market)
  
  # 병합
  df = pd.concat([df_ohlcv, sr_name], axis=1, join='inner')
  
  # 인덱스 초기화 및 컬럼명 FDR 형식으로 변환
  df = df.reset_index().rename(columns={
      '티커': 'Code',
      '종목명': 'Name',
      '등락률': 'ChagesRatio',
      '시가총액': 'Marcap',
      '거래대금': 'Amount'
  })
  
  df['Market'] = market
  return df

def main():
  start_time = time.time()

  # .env 로드 및 KRX 로그인 (인증 우회)
  load_dotenv()
  krx_id = os.getenv("KRX_ID")
  krx_pw = os.getenv("KRX_PW")

  if not krx_id or not krx_pw:
    print("❌ 오류: .env 파일에서 KRX_ID/PW를 확인할 수 없습니다.")
    return

  print("KRX 로그인 진행 중...")
  krx_auth.login_krx(krx_id, krx_pw)

  print("0. 시장 지수 및 시스템 신호 산출 중...")
  try:
    kospi_status, kospi_change = get_market_status('KS11')
    kosdaq_status, kosdaq_change = get_market_status('KQ11')
  except Exception as e:
    kospi_status = f"데이터 수집 실패 ({e})"
    kospi_change = 0.0
    kosdaq_status = f"데이터 수집 실패 ({e})"
    kosdaq_change = 0.0

  # ---------------------------------------------------------
  # 1. KOSPI/KOSDAQ 리스팅 (상한가 및 거래대금 추출)
  # ---------------------------------------------------------
  print("1. 시장 데이터 수집 중...")
  df_kospi_list = get_pykrx_market_listing('KOSPI')
  df_kosdaq_list = get_pykrx_market_listing('KOSDAQ')
  df_all_market = pd.concat([df_kospi_list, df_kosdaq_list], ignore_index=True)

  # 거래대금 TOP 10
  top10_trade_val = df_all_market.sort_values(by="Amount", ascending=False).head(10)
  trade_val_list = [f"{i+1}위. {row['Name']} ({row['ChagesRatio']}%, {format_market_cap(row['Marcap'])})" for i, (_, row) in enumerate(top10_trade_val.iterrows())]

  # 상한가 종목
  limit_up_df = df_all_market[df_all_market['ChagesRatio'] >= 29.5].sort_values(by='ChagesRatio', ascending=False)
  limit_up_list = [f"- {row['Name']} ({row['ChagesRatio']}%, {format_market_cap(row['Marcap'])})" for _, row in limit_up_df.iterrows()]
  if not limit_up_list: limit_up_list = ["- 상한가 종목 없음"]

  # ---------------------------------------------------------
  # 2. ETF 데이터 추출 및 필터링 (Category == 2)
  # ---------------------------------------------------------
  print("2. 국내 섹터 ETF 리스트 수집 중 (카테고리 2 필터링)...")
  df_etf = fdr.StockListing('ETF/KR')
  filtered_etf = df_etf[(df_etf['Category'] == 2) & (~df_etf['Name'].str.contains('인버스|레버리지', na=False))].copy()

  target_rate = max(0.0, kospi_change * 100)

  etf_over_target = filtered_etf[filtered_etf['ChangeRate'] > target_rate].sort_values(by='ChangeRate', ascending=False)
  etf_list = [f"- {row['Name']} ({row['ChangeRate']}%)" for _, row in etf_over_target.iterrows()]
  # 조건에 맞는 ETF가 없을 경우의 메시지 분기 처리
  if not etf_list:
    if kospi_change > 0:
      etf_list = [f"- 코스피 수익률({kospi_change * 100:+.2f}%)을 상회한 주도 섹터 ETF 없음"]
    else:
      etf_list = ["- 0% 이상 상승한 주도 섹터 ETF 없음"]

  # ---------------------------------------------------------
  # 3. RS 스코어 TOP 5 추출
  # ---------------------------------------------------------
  print("3. RS(상대강도) 분석 진행 중 (병렬 처리)...")
  start_date_str = (datetime.today() - timedelta(days=540)).strftime('%Y-%m-%d')

  results = []
  process_func = partial(process_stock, start_date=start_date_str)
  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(process_func, row) for _, row in df_all_market.iterrows()]
    for future in concurrent.futures.as_completed(futures):
      res = future.result()
      if res is not None: results.append(res)

  if results:
    final_df = rs.calculate_relative_strength(pd.concat(results))
    final_df = filter_common_stocks(final_df)

    sort_columns = ['RS', 'RS_1M', 'RS_3M', 'RS_6M', 'RS_12M']
    kospi_rs_df = final_df[final_df['Market'] == 'KOSPI'].sort_values(by=sort_columns, ascending=False).head(5)
    kosdaq_rs_df = final_df[final_df['Market'].str.contains('KOSDAQ')].sort_values(by=sort_columns, ascending=False).head(5)

    # [수정] RS 종목 (종목코드, RS점수, 등락률 ➡ 시가총액 순)
    kospi_rs_list = [f"{i+1}위. {row['Name']} ({row['Code']}, RS: {row['RS']}, {row['ChagesRatio']}%, {format_market_cap(row['Marcap'])})" for i, (_, row) in enumerate(kospi_rs_df.iterrows())]
    kosdaq_rs_list = [f"{i+1}위. {row['Name']} ({row['Code']}, RS: {row['RS']}, {row['ChagesRatio']}%, {format_market_cap(row['Marcap'])})" for i, (_, row) in enumerate(kosdaq_rs_df.iterrows())]
  else:
    kospi_rs_list = ["데이터 분석 실패"]; kosdaq_rs_list = ["데이터 분석 실패"]

  # ---------------------------------------------------------
  # 4. Gemini 프롬프트 입력용 결과 출력
  # ---------------------------------------------------------
  prompt_text = f"""[시스템 신호 상태]
- 코스피: {kospi_status}
- 코스닥: {kosdaq_status}

[코스피 RS TOP 5]
{chr(10).join(kospi_rs_list)}

[코스닥 RS TOP 5]
{chr(10).join(kosdaq_rs_list)}

[거래대금 TOP 10]
{chr(10).join(trade_val_list)}

[상한가 종목]
{chr(10).join(limit_up_list)}

[상승률 0% 이상 ETF 리스트]
{chr(10).join(etf_list)}
"""
  print("\n" + "="*60)
  print("📊 Gemini 프롬프트 데이터 생성 완료 (Daily Market Report)")
  print("="*60 + "\n")
  print(prompt_text)

if __name__ == '__main__':
  main()