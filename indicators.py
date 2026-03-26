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

  # --- [추가] Connors RSI (CRSI) 계산 ---
  # 1. RSI (3)
  df['RSI_3'] = ta.rsi(df['Close'], length=3)

  # 2. Streak RSI (2)
  diff = df['Close'].diff()
  sign = np.sign(diff).fillna(0)
  streak = sign.groupby((sign != sign.shift()).cumsum()).cumsum()
  df['Streak_RSI_2'] = ta.rsi(streak, length=2)

  # 3. Percent Rank (100)
  roc = df['Close'].pct_change()
  # 최근 100일 동안 현재의 등락률이 하위 몇 %에 위치하는지 계산
  df['Percent_Rank_100'] = roc.rolling(window=100).apply(lambda x: (x <= x[-1]).mean() * 100, raw=True)

  # 4. 최종 CRSI (3가지 요소의 평균)
  df['CRSI'] = (df['RSI_3'] + df['Streak_RSI_2'] + df['Percent_Rank_100']) / 3

  df.dropna(inplace=True)
  return df
