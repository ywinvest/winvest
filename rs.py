def calculate_indicators(df):
  first_day_close = df['Close'].iloc[0]
  for period_days in [21, 63, 126, 252]:
    period_str = f"{period_days // 21}M"
    return_col = f'Return_{period_str}'
    base_price = df['Close'].shift(period_days)
    base_price.fillna(first_day_close, inplace=True)
    df[return_col] = df['Close'] / base_price - 1

  # df['Weighted_Return'] = (df['Return_1M'] * 0.4 +
  #                          df['Return_3M'] * 0.2 +
  #                          df['Return_6M'] * 0.2 +
  #                          df['Return_12M'] * 0.1)
  return df


def calculate_relative_strength(df):
  grouped = df.groupby([df.index])

  for period in ["1M", "3M", "6M", "12M"]:
    return_col = f'Return_{period}'
    rs_col = f'RS_{period}'

    df[rs_col] = grouped[return_col].rank(pct=True) * 98 + 1
    df[rs_col] = df[rs_col].fillna(1).astype(int).clip(1, 99)

  base_score = (
      # df['RS_1M'] * 0.2 +
      df['RS_3M'] * 0.5 +
      df['RS_6M'] * 0.3 +
      df['RS_12M'] * 0.2
  )

  df['RS_Score'] = base_score
  df['RS'] = base_score.round(0)

  return df
