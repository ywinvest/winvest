import json
import os
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import FinanceDataReader as fdr
import vectorbt as vbt

import indicators

DEFAULT_RSI_THRESHOLD = 35


class GlobalShortTermStrategy:
  """vectorbt를 사용한 글로벌 단기 전략 백테스트"""

  def __init__(self, data, ticker):
    self.data = data
    self.ticker = ticker
    self.df = indicators.calculate_indicators(data.copy())

  def generate_signals(self):
    """매수/매도 신호 생성 (실전형 로직 - look-ahead 제거)"""
    df = self.df
    n = len(df)

    # 신호 배열 초기화
    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)
    size = np.zeros(n, dtype=float)

    # 추적 변수
    in_position = False
    position_count = 0  # 현재 그룹의 총 매수 횟수
    last_buy_price = None
    first_buy_idx = None
    use_ma20 = False  # 20일선 사용 여부

    # 그룹 통계 추적
    group_buy_indices = []
    group_weights = []

    for i in range(n):
      current_price = df['Close'].iloc[i]
      current_rsi = df['RSI'].iloc[i]
      change_rate = df['Change_Rate'].iloc[i]

      # 매도 조건 체크 (포지션이 있을 때만)
      if in_position:
        sell_signal = False

        if use_ma20:
          # 20일선 돌파 (스냅백)
          if df['MA_20_Cross'].iloc[i] and df['Bullish'].iloc[i]:
            sell_signal = True
        else:
          # 10일선 돌파 (기술적 반등)
          if df['MA_10_Cross'].iloc[i] and df['Bullish'].iloc[i]:
            sell_signal = True

        if sell_signal:
          exits[i] = True
          # 그룹 전체 청산
          in_position = False
          position_count = 0
          last_buy_price = None
          first_buy_idx = None
          use_ma20 = False
          group_buy_indices = []
          group_weights = []
          continue

      # 매수 조건 체크
      # 기본 조건: RSI <= 35, 하락 추세, 변동률 < 0
      if current_rsi <= DEFAULT_RSI_THRESHOLD and not df['Bullish'].iloc[i] and change_rate < 0:

        is_first_buy = not in_position

        # 추가 매수 시 가격 조건 확인
        if not is_first_buy:
          if last_buy_price is None or current_price >= last_buy_price:
            continue

        # RSI 조건 검증
        if is_first_buy:
          required_rsi = DEFAULT_RSI_THRESHOLD
        else:
          # 2차 매수는 RSI 30 이하
          if position_count == 1:
            required_rsi = 30
          else:
            required_rsi = DEFAULT_RSI_THRESHOLD

        if current_rsi > required_rsi:
          continue

        # 매수 실행
        entries[i] = True
        last_buy_price = current_price

        # 포지션 사이즈 결정
        position_size = 1
        if current_rsi <= 20:
          position_size = 3
        elif current_rsi <= 30:
          position_size = 2

        if change_rate < -5:
          position_size += 1

        size[i] = position_size

        # 그룹 추적
        group_buy_indices.append(i)
        group_weights.append(position_size)

        if is_first_buy:
          in_position = True
          first_buy_idx = i
          position_count = 1
          use_ma20 = False
        else:
          position_count += 1

          # 실전형 로직: 5회 이상 매수 시 즉시 목표를 20일선으로 변경
          if position_count >= 5:
            use_ma20 = True

    return entries, exits, size, group_buy_indices, group_weights

  def run_backtest(self):
    """vectorbt를 사용한 백테스트 실행"""
    entries, exits, size, group_buy_indices, group_weights = self.generate_signals()

    # vectorbt 포트폴리오 생성
    portfolio = vbt.Portfolio.from_signals(
        close=self.df['Close'],
        entries=entries,
        exits=exits,
        size=size,
        size_type='amount',
        init_cash=100,
        fees=0.0,
        slippage=0.0,
        freq='D'
    )

    # 결과 수집
    trades = portfolio.trades.records_readable

    if len(trades) > 0:
      # Return 컬럼명 찾기 (PnL, Return, Return [%] 등 가능)
      return_col = None
      for col in ['Return', 'PnL', 'Return [%]', 'P&L']:
        if col in trades.columns:
          return_col = col
          break

      if return_col:
        avg_return = trades[return_col].mean()
        # 퍼센트로 표시되지 않은 경우 100을 곱함
        if return_col in ['Return', 'PnL', 'P&L']:
          avg_return = avg_return * 100
      else:
        avg_return = 0

      # Duration 컬럼이 없을 경우 직접 계산
      if 'Duration' in trades.columns:
        avg_holding_period = trades['Duration'].mean()
      else:
        # Entry/Exit 컬럼명 찾기
        entry_col = None
        exit_col = None

        for col in ['Entry Index', 'Entry Idx', 'EntryIdx', 'entry_idx']:
          if col in trades.columns:
            entry_col = col
            break

        for col in ['Exit Index', 'Exit Idx', 'ExitIdx', 'exit_idx']:
          if col in trades.columns:
            exit_col = col
            break

        if entry_col and exit_col:
          holding_periods = []
          for idx, trade in trades.iterrows():
            entry_idx = int(trade[entry_col])
            exit_idx = int(trade[exit_col])
            entry_date = self.df.index[entry_idx]
            exit_date = self.df.index[exit_idx]
            holding_periods.append((exit_date - entry_date).days)
          avg_holding_period = np.mean(holding_periods) if holding_periods else 0
        else:
          # 컬럼을 찾지 못한 경우 0으로 설정
          avg_holding_period = 0

      buy_count = len(trades)
    else:
      avg_return = 0
      avg_holding_period = 0
      buy_count = 0

    # CSV 출력을 위한 데이터프레임 생성
    result_df = self.df.copy()
    result_df['Action'] = ''
    result_df['Weight'] = 0.0
    result_df['Return'] = np.nan
    result_df['Consecutive Buys'] = np.nan
    result_df['Group Return'] = np.nan

    # 매수/매도 액션 기록
    result_df.loc[entries, 'Action'] = 'Buy'
    result_df.loc[exits, 'Action'] = 'Sell'
    result_df.loc[entries, 'Weight'] = size[entries]

    # 거래별 정보 기록
    for idx, trade in trades.iterrows():
      entry_idx = trade['Entry Index']
      exit_idx = trade['Exit Index']

      result_df.iloc[entry_idx, result_df.columns.get_loc('Return')] = trade['Return']

      # Weight 누적 (매도 시)
      if exit_idx < len(result_df):
        current_weight = result_df.iloc[exit_idx, result_df.columns.get_loc('Weight')]
        result_df.iloc[exit_idx, result_df.columns.get_loc('Weight')] = current_weight + trade['Size']

    # 그룹별 연속 매수 횟수 기록 (근사치)
    # vectorbt에서는 그룹 정보를 직접 추적하기 어려우므로 단순화
    buy_indices = np.where(entries)[0]
    consecutive_count = 0
    last_sell_idx = -1

    for i in buy_indices:
      if i > last_sell_idx:
        consecutive_count = 1
      else:
        consecutive_count += 1

      result_df.iloc[i, result_df.columns.get_loc('Consecutive Buys')] = consecutive_count

      # 다음 매도 찾기
      future_exits = np.where(exits[i:])[0]
      if len(future_exits) > 0:
        last_sell_idx = i + future_exits[0]

    # CSV 저장
    output_dir = 'global/vectorbt'
    os.makedirs(output_dir, exist_ok=True)
    result_df.to_csv(os.path.join(output_dir, f'{self.ticker}_backtest_results.csv'))

    return avg_return, avg_holding_period, buy_count, portfolio


def backtest(data, ticker):
  """백테스트 메인 함수 (호환성 유지)"""
  strategy = GlobalShortTermStrategy(data, ticker)
  avg_return, avg_holding_period, buy_count, portfolio = strategy.run_backtest()
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
      "Average Return": avg_return,
      "Average Holding Period": avg_holding_period,
      "Buy Count": buy_count
    }

  print("\nBacktest Results:")
  for name, metrics in results.items():
    print(f"{name}: Average Return: {metrics['Average Return']:.2f}%, "
          f"Average Holding Period: {metrics['Average Holding Period']:.2f} days, "
          f"Buy Count: {metrics['Buy Count']}")