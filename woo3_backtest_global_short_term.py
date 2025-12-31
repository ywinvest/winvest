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
  return df['MA_10_Cross']  & df['Bullish'] # & (df['ADX'] > 20) & df['DI']

def sell_condition_snap_back(df):
  """스냅백 매도 조건 - 20일선 돌파 (매수 회수가 많을 때)."""
  return (df['Close'] > df['MA_20'])  & df['Bullish'] & (df['ADX'] > 25) & df['DI']

def backtest(data, ticker):
  """Backtest with group-level batch selling (all positions sold at once)."""
  df = indicators.calculate_indicators(data.copy())

  df['Weight'] = 0.0

  buys = df[buy_condition(df)]

  returns = []
  holding_periods = []
  buy_count = 0

  sell_date = None

  # 그룹 내 누적 데이터
  group_positions = []  # [(buy_date, buy_price, position_size), ...]
  group_buy_count = 0
  last_buy_price = None

  # 현재 그룹의 매도 조건 함수
  current_sell_condition = sell_condition_technical_bounce

  # --- 그룹 일괄 매도 및 정산 함수 ---
  def execute_group_sell(sell_date, sell_price):
    nonlocal group_positions, returns, holding_periods

    if not group_positions:
      return

    total_weighted_return = 0
    total_weight = 0

    for buy_date, buy_price, position_size in group_positions:
      trade_return = (sell_price / buy_price - 1) * position_size

      df.loc[buy_date, 'Return'] = trade_return
      df.loc[buy_date, 'Sell Price'] = sell_price
      df.loc[buy_date, 'Sell Date'] = sell_date

      returns.append(trade_return)
      holding_periods.append((sell_date - buy_date).days)

      total_weighted_return += trade_return
      total_weight += position_size

      # Weight 누적
      df.loc[sell_date, 'Weight'] += position_size

    # 그룹 평균 수익률 계산 및 기록
    group_avg_return = total_weighted_return / len(group_positions) if group_positions else 0
    df.loc[sell_date, 'Group Return'] = group_avg_return
    df.loc[sell_date, 'Group Buys'] = group_buy_count
    df.loc[sell_date, 'Action'] = 'Sell'

  for i, buy_date in enumerate(buys.index):
    is_first_buy = len(group_positions) == 0
    rsi = df.loc[buy_date, 'RSI']

    should_buy = True

    # [조건 1] 첫 매수가 아닌데 가격이 올랐으면 매수 스킵
    if not is_first_buy:
      current_price = df.loc[buy_date, 'Close']
      if last_buy_price is None or current_price >= last_buy_price:
        should_buy = False

    # [조건 2] RSI 조건이 안 맞으면 매수 스킵
    if should_buy and not is_first_buy:
      rsi = df.loc[buy_date, 'RSI']
      rsi_threshold = 30 if group_buy_count == 1 else DEFAULT_RSI_THRESHOLD
      if rsi > rsi_threshold:
        should_buy = False

    if should_buy:
      # --- 매수 실행 ---
      buy_price = df.loc[buy_date, 'Close']
      change_rate = df.loc[buy_date, 'Change_Rate']

      df.loc[buy_date, 'Action'] = 'Buy'
      last_buy_price = buy_price
      group_buy_count += 1
      buy_count += 1

      if group_buy_count < 4:
        position_size = 1
      else:
        position_size = 2
        # 두 번째 매수 이후에만 RSI 20 이하 조건 체크
        if rsi <= 20:
          position_size += 1

      if change_rate < -5:
        position_size += 1

      # if rsi <= 20:
      #   position_size = 3
      # elif rsi <= 30:
      #   position_size = 2
      # else:
      #   position_size = 1
      #
      # if change_rate < -5:
      #   position_size += 1

      df.loc[buy_date, 'Weight'] = position_size

      # 그룹 포지션에 추가
      group_positions.append((buy_date, buy_price, position_size))

      # 5회 이상 매수 시 즉시 매도 조건 변경
      if group_buy_count >= 4:
        current_sell_condition = sell_condition_snap_back

      # 매도 날짜 재계산 (현재 시점부터, 선택된 조건 함수 사용)
      subsequent_data = df.loc[buy_date:]
      sell_signals = subsequent_data[current_sell_condition(subsequent_data)]
      sell_date = sell_signals.index[0] if not sell_signals.empty else None

    # 매도 신호가 다음 매수 전에 발생하는지 확인
    next_buy_date = buys.index[i + 1] if i + 1 < len(buys.index) else None

    # 매도 신호가 있고, (다음 매수가 없거나 다음 매수 전에 발생)하면 즉시 그룹 청산
    if sell_date is not None and (next_buy_date is None or sell_date <= next_buy_date):
      sell_price = df.loc[sell_date, 'Close']
      execute_group_sell(sell_date, sell_price)
      last_buy_price = None
      group_buy_count = 0
      group_positions = []
      current_sell_condition = sell_condition_technical_bounce

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