import FinanceDataReader as fdr
import pandas as pd
from scipy.stats import linregress

def analyze_low_trend_with_slope(ticker, start_date, end_date, window=20):
  # 주식 데이터 다운로드
  df = fdr.DataReader(ticker, start_date, end_date)

  # Low 기울기 계산용 데이터 준비
  df['Index'] = range(len(df))  # 인덱스를 숫자로 변환
  slopes = []

  # 지정된 기간(window)마다 기울기 계산
  for i in range(len(df) - window + 1):
    window_data = df.iloc[i:i+window]
    slope, _, _, _, _ = linregress(window_data['Index'], window_data['Low'])
    slopes.append(slope)

  # NaN 처리: 앞쪽에 기울기 데이터를 맞추기 위해 빈 값 추가
  slopes = [None] * (window - 1) + slopes
  df['Slope'] = slopes

  # 기울기가 양수인지 음수인지 판단
  df['Slope_Trend'] = df['Slope'].apply(lambda x: 'Positive' if x > 0 else 'Negative' if x < 0 else 'Flat')

  return df[['Low', 'Slope', 'Slope_Trend']]

# 예제 실행
ticker = "314140"  # 삼성전자
start_date = "2022-01-01"
end_date = "2023-01-02"
window = 5  # 기울기를 계산할 구간 크기

low_trend_df = analyze_low_trend_with_slope(ticker, start_date, end_date, window)
print(low_trend_df.tail(20))
