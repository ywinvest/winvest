import json
import os
from datetime import datetime, timedelta

import FinanceDataReader as fdr

import indicators

DEFAULT_RSI_THRESHOLD = 35

# 초기 필터링용 조건
def buy_condition(df):
  """Broad buy condition for global indices (RSI <= 35)."""
  return (df['RSI'] <= DEFAULT_RSI_THRESHOLD) & (~df['Bullish']) & (df['Change_Rate'] < 0)

def sell_condition_technical_bounce(df):
  """기술적 반등 매도 조건 - 10일선 돌파 (매수 회수가 적을 때)."""
  return df['MA_10_Cross'] & df['Bullish']

def sell_condition_snap_back(df):
  """스냅백 매도 조건 - 20일선 돌파 (매수 회수가 많을 때)."""
  return df['MA_20_Cross'] & df['Bullish']

def backtest(data, ticker):
  """Backtest with dynamic Full Sell logic based on consecutive buy count."""
  df = indicators.calculate_indicators(data.copy())

  df['Weight'] = 0.0

  buys = df[buy_condition(df)]

  returns = []
  holding_periods = []
  buy_count = 0

  current_buy_group_flag = False
  sell_date_full = buys.index[0] if not buys.empty else None
  last_buy_price = None

  current_group_buy_count = 0
  group_consecutive_buys = 0

  group_returns = []
  group_sell_date = None

  # --- 내부 함수: 연속 매수 횟수 미리 계산 ---
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
      threshold = 30 if next_buy_order == 2 else DEFAULT_RSI_THRESHOLD
      if current_rsi <= threshold:
        c_buys += 1
        temp_last_price = current_close
        next_buy_order += 1
    return c_buys

  # --- 그룹 정산(Flush) 함수 ---
  def flush_group_metrics():
    nonlocal group_returns, group_sell_date

    if group_sell_date and group_returns:
      avg_return = sum(group_returns) / len(group_returns)
      df.loc[group_sell_date, 'Group Return'] = avg_return

    group_returns = []
    group_sell_date = None

  for buy_date in buys.index:
    # 새 그룹 시작 여부 확인
    if sell_date_full is not None and buy_date > sell_date_full:
      # 이전 그룹 정산(Flush) 수행
      flush_group_metrics()

      # 상태 초기화
      current_buy_group_flag = False
      last_buy_price = None
      current_group_buy_count = 0
      group_consecutive_buys = 0

    is_first_buy = not current_buy_group_flag

    # 가격 조건 확인
    if not is_first_buy:
      current_price = df.loc[buy_date, 'Close']
      if last_buy_price is None or current_price >= last_buy_price:
        continue

    # RSI 조건 검증
    current_rsi = df.loc[buy_date, 'RSI']
    required_rsi = DEFAULT_RSI_THRESHOLD
    if is_first_buy:
      required_rsi = DEFAULT_RSI_THRESHOLD
    else:
      check_order = current_group_buy_count + 1
      if check_order == 2:
        required_rsi = 30
      else:
        required_rsi = DEFAULT_RSI_THRESHOLD

    if current_rsi > required_rsi:
      continue

    # --- 매수 실행 ---
    position = df.loc[buy_date, 'Close']
    change_rate = df.loc[buy_date, 'Change_Rate']
    df.loc[buy_date, 'Action'] = 'Buy'
    last_buy_price = position
    current_group_buy_count += 1
    buy_count += 1

    if current_rsi <= 20:
      position_size = 3
    elif current_rsi <= 25:
      position_size = 2
    else:
      position_size = 1

    if change_rate < -5:
      position_size += 1

    df.loc[buy_date, 'Weight'] = position_size

    subsequent_data = df.loc[buy_date:]

    # 그룹 초기 설정
    if is_first_buy:
      current_buy_group_flag = True

      temp_sell_partial = subsequent_data[sell_condition_technical_bounce(subsequent_data)]
      temp_sell_date = temp_sell_partial.index[0] if not temp_sell_partial.empty else None

      consecutive_buys = count_potential_buys(buy_date, temp_sell_date, position)

      if consecutive_buys >= 5:
        temp_sell_ma20 = subsequent_data[sell_condition_snap_back(subsequent_data)]
        temp_sell_date_ma20 = temp_sell_ma20.index[0] if not temp_sell_ma20.empty else None
        consecutive_buys = count_potential_buys(buy_date, temp_sell_date_ma20, position)

      group_consecutive_buys = consecutive_buys

    df.loc[buy_date, 'Consecutive Buys'] = group_consecutive_buys

    # 매도 로직 결정 - 한번에 매도
    if group_consecutive_buys >= 5:
      # 5회 이상: 스냅백 매도 (20일선 돌파)
      sell_full_new = subsequent_data[sell_condition_snap_back(subsequent_data)]
      sell_date_full = sell_full_new.index[0] if not sell_full_new.empty else None
    else:
      # 5회 미만: 기술적 반등 매도 (10일선 돌파)
      sell_full = subsequent_data[sell_condition_technical_bounce(subsequent_data)]
      sell_date_full = sell_full.index[0] if not sell_full.empty else None

    # --- 전체 매도 처리 ---
    if sell_date_full:
      df.loc[sell_date_full, 'Action'] = 'Sell'
      sell_price = df.loc[sell_date_full, 'Close']
      trade_return = (sell_price / position - 1) * position_size

      df.loc[buy_date, 'Return'] = trade_return
      returns.append(trade_return)
      holding_periods.append((sell_date_full - buy_date).days)

      # Weight 누적
      df.loc[sell_date_full, 'Weight'] += position_size

      # 그룹 통계 수집
      group_returns.append(trade_return)
      group_sell_date = sell_date_full

  # 루프 종료 후 마지막 그룹 정산(Flush)
  flush_group_metrics()

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

    avg_return, avg_holding_period, buy_count = backtest(data, ticker)

    results[name] = {
      "Average Return": avg_return * 100,
      "Average Holding Period": avg_holding_period,
      "Buy Count": buy_count
    }

  print("\nBacktest Results:")
  for name, metrics in results.items():
    print(f"{name}: Average Return: {metrics['Average Return']:.2f}%, Average Holding Period: {metrics['Average Holding Period']:.2f} days, Buy Count: {metrics['Buy Count']}")