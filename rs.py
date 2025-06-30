import FinanceDataReader as fdr
import pandas as pd
from pykrx import stock
from datetime import datetime, timedelta
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# 1. 데이터 수집 기간 설정
end_date = datetime.today()
start_date = end_date - timedelta(days=40)  # 약 1개월 + 여유분
end_date_str = end_date.strftime('%Y%m%d')
start_date_str = start_date.strftime('%Y%m%d')

# 2. 코스피 상장 종목 리스트 가져오기
kospi = fdr.StockListing('KOSPI')
tickers = kospi['Code'].astype(str).str.zfill(6).tolist()  # 6자리 문자열로 포맷팅

# 3. 코스피 거래일 목록 가져오기 (데이터 누락 방지)
# trading_days = stock.get_nearest_business_day_in_a_week(start_date_str, end_date_str)
# trading_days = pd.to_datetime([day for day in trading_days if start_date_str <= day <= end_date_str])

# 4. 코스피 전체 시가총액 계산
kospi_marketcap = pd.DataFrame()
for date in pd.date_range(start_date, end_date, freq='B'):  # 영업일 기준
  date_str = date.strftime('%Y%m%d')
  try:
    marketcap = stock.get_market_cap_by_ticker(date_str, market='KOSPI')
    total_marketcap = marketcap['시가총액'].sum()
    kospi_marketcap.loc[date, 'MarketCap'] = total_marketcap
  except Exception as e:
    print(f"Error processing date {date_str}: {e}")

# 5. 코스피 시가총액 1개월 상승률 계산
kospi_marketcap['MarketCap_1M_Ago'] = kospi_marketcap['MarketCap'].shift(20)  # 약 1개월(20 거래일) 전
kospi_marketcap['Kospi_Return'] = (kospi_marketcap['MarketCap'] / kospi_marketcap['MarketCap_1M_Ago'] - 1) * 100

# 6. 종목별 시가총액 및 상대강도 계산
results = []
for ticker in tickers:
  try:
    # 종목 시가총액 데이터 가져오기
    df = stock.get_market_cap(start_date_str, end_date_str, ticker)
    if df.empty:
      print(f"No data for {ticker}")
      continue

    # 시가총액 1개월 전 데이터
    df['MarketCap_1M_Ago'] = df['시가총액'].shift(20)

    # 종목 시가총액 상승률 계산
    df['Stock_Return'] = (df['시가총액'] / df['MarketCap_1M_Ago'] - 1) * 100

    # 코스피 시가총액 상승률과 병합 (인덱스 정합성 확인)
    df = df.join(kospi_marketcap['Kospi_Return'], how='left')

    # 상대강도 계산 (TraderLion 방식)
    df['Relative_Strength'] = np.where(df['Kospi_Return'] != 0, df['Stock_Return'] / df['Kospi_Return'], np.nan)

    # 최신 데이터만 추출
    latest = df[['Stock_Return', 'Kospi_Return', 'Relative_Strength']].iloc[-1]
    latest = latest.to_frame().T
    latest['Ticker'] = ticker
    results.append(latest)

  except Exception as e:
    print(f"Error processing {ticker}: {e}")

# 7. 결과 데이터프레임 생성
if results:
  result_df = pd.concat(results, ignore_index=True)
else:
  print("No valid results generated.")
  result_df = pd.DataFrame(columns=['Ticker', 'Stock_Return', 'Kospi_Return', 'Relative_Strength', 'RS_Scaled'])

# 8. 상대강도 정규화 (0~99 정수값)
rs_values = result_df['Relative_Strength'].dropna()
if not rs_values.empty:
  rs_min = rs_values.min()
  rs_max = rs_values.max()
  if rs_max != rs_min:  # 분모가 0이 되는 경우 방지
    result_df['RS_Scaled'] = np.clip(((rs_values - rs_min) / (rs_max - rs_min) * 99), 0, 99).round().astype(int)
  else:
    result_df['RS_Scaled'] = 0
else:
  result_df['RS_Scaled'] = 0

# 9. 결과 출력 (상대강도 상위 10개 종목)
result_df = result_df[['Ticker', 'Stock_Return', 'Kospi_Return', 'Relative_Strength', 'RS_Scaled']]
result_df = result_df.dropna().sort_values(by='RS_Scaled', ascending=False)
if not result_df.empty:
  print("\n코스피 종목별 TraderLion 상대강도 상위 10개 (시가총액 기준, 0~99 스케일):")
  print(result_df.head(10))
else:
  print("No valid data to display.")

# 10. 결과 저장 (CSV 파일)
result_df.to_csv('kospi_traderlion_relative_strength.csv', index=False)
print("결과가 'kospi_traderlion_relative_strength.csv' 파일로 저장되었습니다.")