import pandas as pd
import numpy as np

def calculate_rsi(data, periods=14):
  """
  직접 구현한 RSI 계산 함수

  Parameters:
  data (pd.Series): 종가 데이터
  periods (int): RSI 기간 (기본값 14)

  Returns:
  pd.Series: RSI 값
  """
  # 가격 변화 계산
  delta = data.diff()

  # 상승분과 하락분 분리
  gain = (delta.where(delta > 0, 0))
  loss = (-delta.where(delta < 0, 0))

  # 초기 평균 계산
  avg_gain = gain.rolling(window=periods, min_periods=periods).mean()
  avg_loss = loss.rolling(window=periods, min_periods=periods).mean()

  # 그 이후 계산
  for i in range(periods, len(gain)):
    avg_gain.iloc[i] = (avg_gain.iloc[i-1] * (periods-1) + gain.iloc[i]) / periods
    avg_loss.iloc[i] = (avg_loss.iloc[i-1] * (periods-1) + loss.iloc[i]) / periods

  rs = avg_gain / avg_loss
  rsi = 100 - (100 / (1 + rs))

  return rsi

def compare_rsi_calculations(ticker, period="1y"):
  """
  pandas_ta의 RSI와 직접 구현한 RSI를 비교하는 함수

  Parameters:
  ticker (str): 종목 코드
  period (str): 데이터 기간

  Returns:
  pd.DataFrame: 두 방식의 RSI 값 비교
  """
  import yfinance as yf
  import pandas_ta as ta

  # 데이터 가져오기
  stock = yf.Ticker(ticker)
  data = stock.history(period=period)

  # 데이터 전처리
  data = data.sort_index()
  data = data.dropna()

  # RSI 계산
  rsi_ta = ta.stochrsi(data['Close'], length=14)
  rsi_custom = calculate_rsi(data['Close'], periods=14)

  # 결과 비교
  comparison = pd.DataFrame({
    'RSI_pandas_ta': rsi_ta,
    'RSI_custom': rsi_custom,
    'Difference': abs(rsi_ta - rsi_custom)
  })

  return comparison

if __name__ == '__main__':
    print(compare_rsi_calculations('^KS11').head(20))