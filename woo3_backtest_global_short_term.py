import json
import os
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd

import indicators

# 초기 필터링용 조건 (가장 느슨한 조건인 35를 기준으로 잡고, 상세 로직은 backtest 내부에서 처리)
def buy_condition_broad(df):
  """Broad buy condition for global indices (RSI <= 35)."""
  return (df['RSI'] <= 35) & (~df['Bullish']) & (df['Change_Rate'] < 0)

def sell_condition_partial(df):
  """Partial sell condition for global indices."""
  return df['MA_10_Cross']

def sell_condition_full(df):
  """Full sell condition for global indices."""
  return df['MA_20_Cross'] | df['MA_10_Break']

def backtest(data, ticker, buy_condition, sell_condition_partial, sell_condition_full):
  """Perform backtest with dynamic RSI thresholds and Transaction-based Weight logging."""
  df = indicators.calculate_indicators(data.copy())

  # Weight 컬럼 0.0으로 초기화 (이벤트 발생일에만 값을 기록함)
  df['Weight'] = 0.0

  # 1차 필터: RSI 35 이하인 모든 잠재적 매수 시점을 가져옴
  buys = df[buy_condition(df)]

  returns = []
  holding_periods = []
  buy_count = 0

  current_buy_group_flag = False
  sell_date_full = buys.index[0]
  last_buy_price = None

  # 그룹 내 매수 순서 및 연속 매수 횟수 추적
  current_group_buy_count = 0
  group_consecutive_buys = 0

  # [NEW] 현재 그룹의 누적 웨이트를 추적하는 변수 (Dataframe 컬럼 대신 로직으로 관리)
  current_accumulated_weight = 0.0

  # --- 내부 함수: 연속 매수 횟수 미리 계산 (Look-ahead Logic) ---
  def count_potential_buys(start_date, end_date, initial_price):
    if end_date:
      group_data = df.loc[start_date:end_date]
    else:
      group_data = df.loc[start_date:]

    potential_candidates = group_data[buy_condition(group_data)]

    c_buys = 1
    temp_last_price = initial_price
    next_buy_order = 2

    for idx in potential_candidates.index:
      if idx <= start_date:
        continue

      current_close = group_data.loc[idx, 'Close']
      current_rsi = group_data.loc[idx, 'RSI']

      if current_close >= temp_last_price:
        continue

      # RSI 조건: 2번째는 30 이하, 그 외는 35 이하
      threshold = 30 if next_buy_order == 2 else 35

      if current_rsi <= threshold:
        c_buys += 1
        temp_last_price = current_close
        next_buy_order += 1

    return c_buys
  # -------------------------------------------------------

  for buy_date in buys.index:
    # 새 그룹 시작 여부 확인
    if sell_date_full is not None and buy_date > sell_date_full:
      current_buy_group_flag = False
      last_buy_price = None
      current_group_buy_count = 0
      group_consecutive_buys = 0
      current_accumulated_weight = 0.0 # 새 그룹 시작시 누적 웨이트 초기화

    is_first_buy = not current_buy_group_flag

    # 가격 조건 확인 (첫 매수 아닐 때)
    if not is_first_buy:
      current_price = df.loc[buy_date, 'Close']
      if last_buy_price is None or current_price >= last_buy_price:
        continue

    # 매수 회차별 RSI 조건 검증 (35 -> 30 -> 35)
    current_rsi = df.loc[buy_date, 'RSI']
    required_rsi = 35

    if is_first_buy:
      required_rsi = 35
    else:
      check_order = current_group_buy_count + 1
      if check_order == 2:
        required_rsi = 30
      else:
        required_rsi = 35

    if current_rsi > required_rsi:
      continue

    # --- 실제 매수 실행 ---
    position = df.loc[buy_date, 'Close']
    df.loc[buy_date, 'Action'] = 'Buy'
    last_buy_price = position

    current_group_buy_count += 1
    buy_count += 1

    # 포지션 사이즈 결정
    if current_rsi <= 20:
      position_size = 3
    elif current_rsi <= 30:
      position_size = 2
    else:
      position_size = 1

    df.loc[buy_date, 'Weight'] = position_size
    current_accumulated_weight += position_size

    subsequent_data = df.loc[buy_date:]

    # 첫 매수일 때만 연속매수횟수 예측 계산
    if is_first_buy:
      current_buy_group_flag = True

      temp_sell_partial = subsequent_data[sell_condition_partial(subsequent_data)] if sell_condition_partial else pd.DataFrame()
      temp_sell_date = temp_sell_partial.index[0] if not temp_sell_partial.empty else None

      consecutive_buys = count_potential_buys(buy_date, temp_sell_date, position)

      if consecutive_buys >= 5:
        temp_sell_ma20 = subsequent_data[subsequent_data['MA_20_Cross']]
        temp_sell_date_ma20 = temp_sell_ma20.index[0] if not temp_sell_ma20.empty else None
        consecutive_buys = count_potential_buys(buy_date, temp_sell_date_ma20, position)

      group_consecutive_buys = consecutive_buys

    df.loc[buy_date, 'Consecutive Buys'] = group_consecutive_buys

    # 매도 로직 결정
    if group_consecutive_buys >= 5:
      override_condition = lambda d: d['MA_20_Cross']
      sell_full_new = subsequent_data[override_condition(subsequent_data)]
      sell_date_full = sell_full_new.index[0] if not sell_full_new.empty else None
      sell_date_partial = None
    else:
      temp_sell_partial = subsequent_data[sell_condition_partial(subsequent_data)] if sell_condition_partial else pd.DataFrame()
      sell_date_partial = temp_sell_partial.index[0] if not temp_sell_partial.empty else None

      sell_full = subsequent_data.loc[sell_date_partial:] if sell_date_partial else subsequent_data
      sell_full = sell_full[sell_condition_full(sell_full)] if sell_condition_full else pd.DataFrame()
      sell_date_full = sell_full.index[0] if not sell_full.empty else None

    # 부분 매도 처리
    if sell_date_partial:
      df.loc[sell_date_partial, 'Action'] = 'Partial Sell'
      partial_price = df.loc[sell_date_partial, 'Close']
      partial_return = (partial_price / position - 1) * position_size
      df.loc[buy_date, 'Partial Return'] = partial_return
      returns.append(partial_return)
      holding_periods.append((sell_date_partial - buy_date).days)

      sell_weight = current_accumulated_weight / 2
      df.loc[sell_date_partial, 'Weight'] = sell_weight
      current_accumulated_weight -= sell_weight # 누적 잔고 갱신

    # 전체 매도 처리
    if sell_date_full:
      df.loc[sell_date_full, 'Action'] = 'Full Sell'
      full_price = df.loc[sell_date_full, 'Close']
      full_return = (full_price / position - 1) * position_size
      df.loc[buy_date, 'Full Return'] = full_return
      returns.append(full_return)
      holding_periods.append((sell_date_full - buy_date).days)

      sell_weight = current_accumulated_weight
      df.loc[sell_date_full, 'Weight'] = sell_weight
      current_accumulated_weight = 0.0 # 전량 매도했으므로 0

  avg_return = sum(returns) / len(returns) if returns else 0
  avg_holding_period = sum(holding_periods) / len(holding_periods) if holding_periods else 0

  output_dir = 'global/buy-and-sell'
  os.makedirs(output_dir, exist_ok=True)
  df.to_csv(os.path.join(output_dir, f'{ticker}_backtest_results.csv'))

  return avg_return, avg_holding_period, buy_count


if __name__ == "__main__":
  with open('config-woo3.json', 'r') as config_file:
    config = json.load(config_file)

  tickers = config["global"]["tickers"]
  results = {}

  end_date = datetime.today()
  start_date = end_date - timedelta(days=30 * 365)

  end_date_str = end_date.strftime('%Y-%m-%d')
  start_date_str = start_date.strftime('%Y-%m-%d')

  for ticker, name in tickers.items():
    print(f"Processing {ticker} ({name})...")
    data = fdr.DataReader(ticker, start=start_date_str, end=end_date_str)

    if data.empty:
      print(f"No data found for {ticker}, skipping.")
      continue

    avg_return, avg_holding_period, buy_count = backtest(
        data, ticker,
        buy_condition_broad,
        sell_condition_partial=sell_condition_partial,
        sell_condition_full=sell_condition_full
    )

    results[name] = {
      "Average Return": avg_return * 100,
      "Average Holding Period": avg_holding_period,
      "Buy Count": buy_count
    }

  print("\nBacktest Results:")
  for name, metrics in results.items():
    print(
      f"{name}: Average Return: {metrics['Average Return']:.2f}%, Average Holding Period: {metrics['Average Holding Period']:.2f} days, Buy Count: {metrics['Buy Count']}")
