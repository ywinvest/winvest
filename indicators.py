import pandas_ta as ta

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

  df.dropna(inplace=True)
  return df
