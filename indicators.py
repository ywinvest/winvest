import pandas_ta as ta
import numpy as np

def calculate_indicators(df):
  """Calculate technical indicators."""
  df['RSI'] = ta.rsi(df['Close'], length=14).round(2)
  df['MA_10'] = df['Close'].rolling(window=10).mean()
  df['MA_20'] = df['Close'].rolling(window=20).mean()
  df['MA_60'] = df['Close'].rolling(window=60).mean()
  df['Bullish'] = df['Close'] > df['Open']
  df['Change_Rate'] = (df['Close'].pct_change(fill_method=None) * 100).round(2)
  df['MA_10_Trend'] = df['MA_10'].diff().gt(0)
  df['MA_20_Trend'] = df['MA_20'].diff().gt(0)

  df['RSI_Low_Point'] = (df['RSI'] <= 35) & (df['RSI'] < df['RSI'].rolling(window='5D').min().shift(1))

  df['MA_10_Cross'] = (df['Close'].gt(df['MA_10'], axis=0)) & (df['Close'].shift(1).le(df['MA_10'].shift(1), axis=0))
  df['MA_20_Cross'] = (df['Close'].gt(df['MA_20'], axis=0)) & (df['Close'].shift(1).le(df['MA_20'].shift(1), axis=0))
  df['MA_60_Cross'] = (df['Close'].gt(df['MA_60'], axis=0)) & (df['Close'].shift(1).le(df['MA_60'].shift(1), axis=0))
  df['MA_10_Break'] = (df['Close'].lt(df['MA_10'], axis=0)) & (df['Close'].shift(1).ge(df['MA_10'].shift(1), axis=0))
  df['MA_20_Break'] = (df['Close'].lt(df['MA_20'], axis=0)) & (df['Close'].shift(1).ge(df['MA_20'].shift(1), axis=0))

  df['High_5D'] = df['High'].rolling(window=5, min_periods=1).max()

  adx_data = ta.adx(high=df['High'], low=df['Low'], close=df['Close'], length=14, mamode='EMA')
  df['ADX'] = adx_data['ADX_14']
  df['DMP'] = adx_data['DMP_14']
  df['DMN'] = adx_data['DMN_14']
  df['DI'] = df['DMP'] > df['DMN']
  df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14).round(2)
  df['ATR_22'] = ta.atr(df['High'], df['Low'], df['Close'], length=22).round(2)

  # --- [추가] ATR 변동성 기반 동적 RSI 임계치 계산 ---
  # 1. 과거 60일 평균 변동성(장기 기준점) 계산
  df['ATR_MA_60'] = df['ATR'].rolling(window=60).mean()

  # 2. 변동성 비율 (현재 변동성 / 평균 변동성)
  # 1.0이면 평상시, 1.5면 변동성 50% 증가(위험), 0.5면 변동성 축소
  df['Volatility_Ratio'] = df['ATR'] / df['ATR_MA_60']

  # 3. 동적 임계치 산정
  # 공식: 기본 임계치(40) - (변동성 비율 * 민감도 가중치(10))
  # (예시: 비율 1.0 -> RSI 30 / 비율 1.5 -> RSI 25 / 비율 2.0 -> RSI 20)
  base_threshold = 40
  volatility_weight = 10

  df['Dynamic_RSI_Threshold'] = base_threshold - (df['Volatility_Ratio'] * volatility_weight)

  # 4. 임계치의 비정상적 발산을 막기 위한 상/하한선 클리핑 (최소 15 ~ 최대 40)
  df['Dynamic_RSI_Threshold'] = df['Dynamic_RSI_Threshold'].clip(lower=15, upper=40).round(1)
  # -------------------------------------------------

  df.dropna(inplace=True)
  return df
