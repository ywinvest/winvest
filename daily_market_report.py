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

def format_market_cap(marcap):
  """시가총액을 조 또는 억 단위로 보기 좋게 포맷팅"""
  if pd.isna(marcap) or marcap == 0:
    return "시총정보없음"
  if marcap >= 1e12:  # 1조 이상
    return f"{marcap/1e12:.1f}조"
  else:  # 억 단위
    return f"{marcap/1e8:.0f}억"

def filter_common_stocks(df):
  """매매 부적합 종목(스팩, 우선주 등) 필터링 (RS 계산 후 실행)"""
  exclude_pattern = r'스팩|리츠|ETN|ETF'
  if 'Name' in df.columns:
    return df[(~df['Name'].str.contains(exclude_pattern, na=False, regex=True))
              & (~df['Code'].str.endswith(("5", "7", "9", "K", "L", "M", "N", "O")))]
  return df

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

  # 시스템 신호 상태 (수동 입력 구간)
  kospi_status = "경고 유지"
  kosdaq_status = "경고 유지"

  # ---------------------------------------------------------
  # 1. KOSPI/KOSDAQ 리스팅 (상한가 및 거래대금 추출)
  # ---------------------------------------------------------
  print("1. 시장 데이터 수집 중...")
  df_kospi_list = fdr.StockListing('KOSPI')
  df_kosdaq_list = fdr.StockListing('KOSDAQ')
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

  etf_over_0 = filtered_etf[filtered_etf['ChangeRate'] > 0.0].sort_values(by='ChangeRate', ascending=False)
  etf_list = [f"- {row['Name']} ({row['ChangeRate']}%)" for _, row in etf_over_0.iterrows()]
  if not etf_list: etf_list = ["- 0% 이상 상승한 국내 섹터 ETF 없음"]

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