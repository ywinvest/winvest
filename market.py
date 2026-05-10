import pandas_ta as ta


def add_indicators(df):
  """시장 지수 DataFrame에 보조 지표 열을 추가하여 반환"""
  df['RSI'] = ta.rsi(df['Close'], length=14)
  adx_data = ta.adx(high=df['High'], low=df['Low'], close=df['Close'], length=14, mamode='EMA')
  df['ADX'] = adx_data['ADX_14']
  df['DI'] = adx_data['DMP_14'] > adx_data['DMN_14']
  df['MA5_Up'] = df['Close'] > df['Close'].rolling(window=5).mean()
  df['MA20_Up'] = df['Close'] > df['Close'].rolling(window=20).mean()
  df['MA60_Up'] = df['Close'] > df['Close'].rolling(window=60).mean()
  df['MA120_Up'] = df['Close'] > df['Close'].rolling(window=120).mean()
  return df

def get_signal(ma20_up, adx, di, ma5_up):
  """공통 시장 상태 평가 로직 (green, yellow, red)"""
  if ma20_up and 20 <= adx and di:
    if 25 <= adx and ma5_up:
      return "green"
    elif 20 <= adx < 25 or not ma5_up:
      return "yellow"
  return "red"