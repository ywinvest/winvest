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
  """Perform backtest with dynamic RSI thresholds (35 -> 30 -> 35)."""
  df = indicators.calculate_indicators(data.copy())

  df['Weight'] = 0.0

  # 1차 필터: RSI 35 이하인 모든 잠재적 매수 시점을 가져옴
  buys = df[buy_condition(df)]

  returns = []
  holding_periods = []
  buy_count = 0  # 실제 매수 횟수 (건너뛴 것 제외)

  current_buy_group_flag = False
  sell_date_full = buys.index[0]
  last_buy_price = None

  # 현재 그룹 내에서 내가 몇 번째 매수를 하고 있는지 추적
  current_group_buy_count = 0
  group_consecutive_buys = 0

  # --- 내부 함수: 연속 매수 횟수 미리 계산 (Look-ahead Logic) ---
  def count_potential_buys(start_date, end_date, initial_price):
    """
    미래 데이터를 조회하여 35 -> 30 -> 35 규칙에 따라 몇 번 더 살 수 있는지 계산
    """
    # 매도 날짜가 없으면 데이터 끝까지
    if end_date:
      group_data = df.loc[start_date:end_date]
    else:
      group_data = df.loc[start_date:]

    # 가장 느슨한 조건(35)으로 일단 후보군을 추림
    potential_candidates = group_data[buy_condition(group_data)]

    c_buys = 1 # 첫 매수는 이미 확정
    temp_last_price = initial_price

    # 첫 매수가 1번째이므로, 다음 후보는 2번째부터 시작
    next_buy_order = 2

    for idx in potential_candidates.index:
      if idx <= start_date:
        continue

      current_close = group_data.loc[idx, 'Close']
      current_rsi = group_data.loc[idx, 'RSI']

      # 가격 조건: 이전 매수가보다 낮아야 함
      if current_close >= temp_last_price:
        continue

      # RSI 조건: 2번째는 30 이하, 그 외(3번째 이상)는 35 이하
      threshold = 30 if next_buy_order == 2 else 35

      if current_rsi <= threshold:
        c_buys += 1
        temp_last_price = current_close
        next_buy_order += 1

    return c_buys
  # -------------------------------------------------------

  for buy_date in buys.index:
    # 현재 날짜가 이전 그룹의 전체 매도일 이후라면 새 그룹 시작
    if sell_date_full is not None and buy_date > sell_date_full:
      current_buy_group_flag = False
      last_buy_price = None
      current_group_buy_count = 0
      group_consecutive_buys = 0

    is_first_buy = not current_buy_group_flag

    # [검증] 이전 매수보다 종가가 낮은지 확인 (첫 매수 아닐 때)
    if not is_first_buy:
      current_price = df.loc[buy_date, 'Close']
      if last_buy_price is None or current_price >= last_buy_price:
        continue

    # [중요] 매수 회차별 RSI 조건 검증 (35 -> 30 -> 35)
    current_rsi = df.loc[buy_date, 'RSI']
    required_rsi = 35 # Default

    if is_first_buy:
      required_rsi = 35
    else:
      # 현재가 그룹의 몇 번째 매수인지 확인 (현재 카운트 + 1이 이번 매수 차례)
      check_order = current_group_buy_count + 1
      if check_order == 2:
        required_rsi = 30
      else:
        required_rsi = 35

    # 조건 불만족시 이번 매수 신호는 건너뜀 (예: 2번째인데 RSI가 33인 경우)
    if current_rsi > required_rsi:
      continue

    # --- 실제 매수 실행 ---
    position = df.loc[buy_date, 'Close']
    df.loc[buy_date, 'Action'] = 'Buy'
    last_buy_price = position

    current_group_buy_count += 1
    buy_count += 1 # 전체 매수 횟수 증가

    # 포지션 사이즈 조절 (기존 로직 유지)
    if current_rsi <= 25:
      position_size = 3
    elif current_rsi <= 30:
      position_size = 2
    else:
      position_size = 1

    df.loc[buy_date:, 'Weight'] += position_size
    subsequent_data = df.loc[buy_date:]

    # 첫 매수일 때만 앞으로 일어날 일(연속매수횟수) 예측 계산
    if is_first_buy:
      current_buy_group_flag = True # 그룹 시작 설정

      # 1단계: 기본 매도(10일선) 기준으로 카운트
      temp_sell_partial = subsequent_data[sell_condition_partial(subsequent_data)] if sell_condition_partial else pd.DataFrame()
      temp_sell_date = temp_sell_partial.index[0] if not temp_sell_partial.empty else None

      consecutive_buys = count_potential_buys(buy_date, temp_sell_date, position)

      # 2단계: 연속매수가 5회 이상이면 20일선 기준으로 재계산
      if consecutive_buys >= 3:
        temp_sell_ma20 = subsequent_data[subsequent_data['MA_20_Cross']]
        temp_sell_date_ma20 = temp_sell_ma20.index[0] if not temp_sell_ma20.empty else None

        # 20일선 기준으로 다시 카운트 (35-30-35 규칙 적용됨)
        consecutive_buys = count_potential_buys(buy_date, temp_sell_date_ma20, position)

      group_consecutive_buys = consecutive_buys

    df.loc[buy_date, 'Consecutive Buys'] = group_consecutive_buys

    # 매도 로직 결정 (5회 이상이면 전체 매도만, 아니면 부분+전체)
    if group_consecutive_buys >= 3:
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

      current_weight = df.loc[sell_date_partial, 'Weight']
      df.loc[sell_date_partial:, 'Weight'] = current_weight / 2

    # 전체 매도 처리
    if sell_date_full:
      df.loc[sell_date_full, 'Action'] = 'Full Sell'
      full_price = df.loc[sell_date_full, 'Close']
      full_return = (full_price / position - 1) * position_size
      df.loc[buy_date, 'Full Return'] = full_return
      returns.append(full_return)
      holding_periods.append((sell_date_full - buy_date).days)

      current_weight = df.loc[sell_date_full, 'Weight']
      df.loc[sell_date_full:, 'Weight'] -= current_weight

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

    # buy_condition에는 가장 넓은 범위(RSI 35) 함수 전달
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
    print(f"{name}: Average Return: {metrics['Average Return']:.2f}%, Average Holding Period: {metrics['Average Holding Period']:.2f} days, Buy Count: {metrics['Buy Count']}")