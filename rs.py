import FinanceDataReader as fdr
import pandas as pd
from datetime import datetime, timedelta
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# 1. 데이터 수집 기간 설정
end_date = datetime(2025, 6, 27)
start_date = end_date - timedelta(days=40)  # 1개월 + 여유분
end_date_str = end_date.strftime('%Y%m%d')
start_date_str = start_date.strftime('%Y%m%d')

# 2. 코스피 상장 종목 리스트
krx_marcap = fdr.StockListing('KRX-MARCAP')
tickers = krx_marcap[krx_marcap['Market'] == 'KOSPI']['Code'].astype(str).str.zfill(6).unique().tolist()

# 3. 실제 거래일 목록 가져오기
trading_days = fdr.DataReader('005930', start_date, end_date).index
trading_days = pd.to_datetime(trading_days)

# 4. 1개월 전 날짜 계산 (정확히 30일 전)
one_month_ago = end_date - timedelta(days=30)
one_month_ago_str = one_month_ago.strftime('%Y%m%d')
# 가장 가까운 이전 거래일 찾기
trading_days_before = trading_days[trading_days <= one_month_ago]
if trading_days_before.empty:
  print("No trading days available before one month ago.")
  exit()
one_month_ago_date = trading_days_before[-1].strftime('%Y%m%d')

# 5. 코스피 전체 시가총액 계산 (최종일과 1개월 전)
kospi_marketcap = pd.DataFrame()
for date in [end_date_str, one_month_ago_date]:
  try:
    df_marcap = fdr.StockListing('KRX-MARCAP', start=date, end=date)
    df_kospi = df_marcap[df_marcap['Market'] == 'KOSPI']
    total_marketcap = df_kospi['Marcap'].sum()
    kospi_marketcap.loc[date, 'MarketCap'] = total_marketcap
  except Exception as e:
    print(f"Error processing date {date}: {e}")

# 코스피 시가총액 상승률 계산
if len(kospi_marketcap) >= 2:
  kospi_current = kospi_marketcap.loc[end_date_str, 'MarketCap'] if end_date_str in kospi_marketcap.index else np.nan
  kospi_1m_ago = kospi_marketcap.loc[one_month_ago_date, 'MarketCap'] if one_month_ago_date in kospi_marketcap.index else np.nan
  kospi_return = (kospi_current / kospi_1m_ago - 1) * 100 if kospi_1m_ago != 0 else np.nan
else:
  kospi_return = np.nan
  print("Insufficient data for KOSPI market cap return.")

# 6. 종목별 시가총액 및 상대강도 계산
results = []
for ticker in tickers:  # 테스트용 50개 제한, 전체는 [:50] 제거
  try:
    # 종목별 시가총액 데이터 (최종일과 1개월 전)
    df_marcap = fdr.StockListing('KRX-MARCAP', start=start_date_str, end=end_date_str)
    df_marcap = df_marcap[df_marcap['Code'] == ticker]
    if df_marcap.empty:
      print(f"No marcap data for {ticker}")
      continue

    # 최종일과 1개월 전 데이터 추출
    df_marcap['Date'] = pd.to_datetime(df_marcap['Date'])
    df_current = df_marcap[df_marcap['Date'] == end_date_str]
    df_1m_ago = df_marcap[df_marcap['Date'] == one_month_ago_date]

    if df_current.empty or df_1m_ago.empty:
      print(f"Missing data for {ticker} on {end_date_str} or {one_month_ago_date}")
      continue

    current_marcap = df_current['Marcap'].iloc[0]
    marcap_1m_ago = df_1m_ago['Marcap'].iloc[0]

    # 종목 시가총액 상승률
    stock_return = (current_marcap / marcap_1m_ago - 1) * 100 if marcap_1m_ago != 0 else np.nan

    # 상대강도 계산
    relative_strength = stock_return / kospi_return if kospi_return != 0 else np.nan

    # 결과 저장
    result = pd.DataFrame({
      'Ticker': [ticker],
      'Stock_Return': [stock_return],
      'Kospi_Return': [kospi_return],
      'Relative_Strength': [relative_strength]
    })
    results.append(result)

  except Exception as e:
    print(f"Error processing {ticker}: {e}")

# 7. 결과 데이터프레임 생성
if results:
  result_df = pd.concat(results, ignore_index=True)
else:
  print("No valid results generated.")
  result_df = pd.DataFrame(columns=['Ticker', 'Stock_Return', 'Kospi_Return', 'Relative_Strength', 'RS_Scaled'])

# 8. 상대강도 정규화 (0~99)
rs_values = result_df['Relative_Strength'].dropna()
if not rs_values.empty and rs_values.max() != rs_values.min():
  rs_min = rs_values.min()
  rs_max = rs_values.max()
  result_df['RS_Scaled'] = np.clip(((rs_values - rs_min) / (rs_max - rs_min) * 99), 0, 99).round().astype(int)
else:
  result_df['RS_Scaled'] = 0

# 9. 결과 출력
result_df = result_df[['Ticker', 'Stock_Return', 'Kospi_Return', 'Relative_Strength', 'RS_Scaled']]
result_df = result_df.dropna().sort_values(by='RS_Scaled', ascending=False)
if not result_df.empty:
  print("\n코스피 종목별 TraderLion 상대강도 상위 10개 (시가총액 기준, 0~99 스케일):")
  print(result_df.head(10))
else:
  print("No valid data to display.")

# 10. 결과 저장
result_df.to_csv('kospi_traderlion_relative_strength.csv', index=False)
print("결과가 'kospi_traderlion_relative_strength.csv' 파일로 저장되었습니다.")