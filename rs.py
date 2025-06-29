import FinanceDataReader as fdr
import pandas as pd
from datetime import datetime, timedelta
import numpy as np

# 1. 데이터 수집 기간 설정 (오늘로부터 1개월 전까지)
end_date = datetime.today()
start_date = end_date - timedelta(days=40)  # 약 1개월 + 여유분

# 2. 코스피 상장 종목 리스트 가져오기
kospi = fdr.StockListing('KOSPI')
tickers = kospi['Symbol'].tolist()

# 3. 코스피 지수 데이터 가져오기
kospi_index = fdr.DataReader('KS11', start_date, end_date)

# 4. 코스피 지수 1개월 상승률 계산
kospi_index['Price_1M_Ago'] = kospi_index['Close'].shift(20)  # 약 1개월(20 거래일) 전
kospi_index['Kospi_Return'] = (kospi_index['Close'] / kospi_index['Price_1M_Ago'] - 1) * 100

# 5. 종목별 상대강도 계산 및 정규화
results = []
for ticker in tickers[:50]:  # 테스트를 위해 50개 종목으로 제한, 전체 종목은 제거 가능
  try:
    # 종목 데이터 가져오기
    df = fdr.DataReader(ticker, start_date, end_date)

    # 1개월 전 종가
    df['Price_1M_Ago'] = df['Close'].shift(20)  # 약 1개월(20 거래일) 전

    # 종목 1개월 상승률 계산
    df['Stock_Return'] = (df['Close'] / df['Price_1M_Ago'] - 1) * 100

    # 코스피 상승률과 병합
    df = df.join(kospi_index['Kospi_Return'])

    # 상대강도 계산 (TraderLion 방식: 종목 상승률 / 코스피 상승률)
    df['Relative_Strength'] = df['Stock_Return'] / df['Kospi_Return']

    # 최신 데이터만 추출
    latest = df[['Stock_Return', 'Kospi_Return', 'Relative_Strength']].iloc[-1]
    latest = latest.to_frame().T
    latest['Ticker'] = ticker
    results.append(latest)

  except Exception as e:
    print(f"Error processing {ticker}: {e}")

# 6. 결과 데이터프레임 생성
result_df = pd.concat(results, ignore_index=True)

# 7. 상대강도 정규화 (0~99 정수값)
# Min-Max 정규화: (x - min) / (max - min) * 99
rs_values = result_df['Relative_Strength'].dropna()
if not rs_values.empty:
  rs_min = rs_values.min()
  rs_max = rs_values.max()
  result_df['RS_Scaled'] = ((rs_values - rs_min) / (rs_max - rs_min) * 99).round().astype(int)
else:
  result_df['RS_Scaled'] = 0  # 데이터가 없을 경우 기본값

# 8. 결과 출력 (상대강도 상위 10개 종목)
result_df = result_df[['Ticker', 'Stock_Return', 'Kospi_Return', 'Relative_Strength', 'RS_Scaled']]
result_df = result_df.dropna().sort_values(by='RS_Scaled', ascending=False)
print("\n코스피 종목별 TraderLion 상대강도 상위 10개 (0~99 스케일):")
print(result_df.head(10))

# 9. 결과 저장 (CSV 파일)
result_df.to_csv('kospi_traderlion_relative_strength.csv', index=False)
print("결과가 'kospi_traderlion_relative_strength.csv' 파일로 저장되었습니다.")