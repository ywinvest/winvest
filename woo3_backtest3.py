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
  """vectorbt 기반 글로벌 단기 매매 전략"""

  def __init__(self, data, ticker):
    self.data = data
    self.ticker = ticker
    self.df = indicators.calculate_indicators(data.copy())

  def generate_signals(self):
    """매수/매도 신호 생성"""
    df = self.df

    # 초기화
    entries = pd.Series(False, index=df.index)
    exits = pd.Series(False, index=df.index)
    size = pd.Series(0.0, index=df.index)

    # 상태 변수
    group_positions = []
    group_buy_count = 0
    last_buy_price = None
    sell_date_idx = None
    use_snapback = False

    for i in range(len(df)):
      current_date = df.index[i]

      # 매도 신호 확인
      if sell_date_idx is not None and i >= sell_date_idx:
        if group_positions:
          exits.iloc[i] = True
          # 그룹 전체 청산
          group_positions = []
          group_buy_count = 0
          last_buy_price = None
          use_snapback = False
          sell_date_idx = None

      # 매수 조건 확인
      buy_cond = (df['RSI'].iloc[i] <= DEFAULT_RSI_THRESHOLD and
                  not df['Bullish'].iloc[i] and
                  df['Change_Rate'].iloc[i] < 0)

      if buy_cond:
        should_buy = True
        position_size = 1

        # 첫 매수가 아닌 경우 추가 검증
        if group_positions:
          current_price = df['Close'].iloc[i]

          # 조건 1: 가격이 올랐으면 스킵
          if last_buy_price is not None and current_price >= last_buy_price:
            should_buy = False

          # 조건 2: RSI 조건
          if should_buy:
            rsi = df['RSI'].iloc[i]
            rsi_threshold = 30 if group_buy_count == 1 else DEFAULT_RSI_THRESHOLD
            if rsi > rsi_threshold:
              should_buy = False

        if should_buy:
          # 포지션 사이즈 계산
          rsi = df['RSI'].iloc[i]
          change_rate = df['Change_Rate'].iloc[i]

          if rsi <= 20:
            position_size = 3
          elif rsi <= 30:
            position_size = 2
          else:
            position_size = 1

          if change_rate < -5:
            position_size += 1

          # 매수 실행
          entries.iloc[i] = True
          size.iloc[i] = position_size

          buy_price = df['Close'].iloc[i]
          group_positions.append((i, buy_price, position_size))
          group_buy_count += 1
          last_buy_price = buy_price

          # 5회 이상 매수 시 스냅백 조건으로 전환
          if group_buy_count >= 5:
            use_snapback = True

          # 매도 날짜 계산
          if use_snapback:
            # 스냅백: MA_20 돌파
            sell_mask = df['MA_20_Cross'].iloc[i:] & df['Bullish'].iloc[i:]
          else:
            # 기술적 반등: MA_10 돌파
            sell_mask = df['MA_10_Cross'].iloc[i:] & df['Bullish'].iloc[i:]

          if sell_mask.any():
            sell_date = sell_mask.idxmax()
            sell_date_idx = df.index.get_loc(sell_date)

    return entries, exits, size

  def run_backtest(self, init_cash=10000, fees=0.001):
    """vectorbt를 사용한 백테스트 실행"""
    entries, exits, size = self.generate_signals()

    # vectorbt Portfolio 생성
    portfolio = vbt.Portfolio.from_signals(
        close=self.df['Close'],
        entries=entries,
        exits=exits,
        size=size,
        size_type='amount',
        init_cash=init_cash,
        fees=fees,
        freq='1D'
    )

    return portfolio

  def get_results(self, portfolio):
    """백테스트 결과 추출"""
    trades = portfolio.trades.records_readable

    if len(trades) == 0:
      return {
        'avg_return': 0,
        'avg_holding_period': 0,
        'buy_count': 0,
        'total_return': 0,
        'win_rate': 0,
        'max_drawdown': 0
      }

    # 수익률 계산
    returns = trades['Return'].values
    avg_return = returns.mean() if len(returns) > 0 else 0

    # 보유 기간 계산 (일 단위)
    holding_periods = (trades['Exit Date'] - trades['Entry Date']).dt.days
    avg_holding_period = holding_periods.mean() if len(holding_periods) > 0 else 0

    # 기타 통계
    buy_count = len(trades)
    total_return = portfolio.total_return()
    win_rate = (returns > 0).sum() / len(returns) if len(returns) > 0 else 0
    max_drawdown = portfolio.max_drawdown()

    return {
      'avg_return': avg_return * 100,
      'avg_holding_period': avg_holding_period,
      'buy_count': buy_count,
      'total_return': total_return * 100,
      'win_rate': win_rate * 100,
      'max_drawdown': max_drawdown * 100,
      'sharpe_ratio': portfolio.sharpe_ratio(),
      'trades': trades
    }

  def save_results(self, portfolio, output_dir='global/buy-and-sell'):
    """결과 저장"""
    os.makedirs(output_dir, exist_ok=True)

    # 거래 내역 저장
    trades = portfolio.trades.records_readable
    trades.to_csv(os.path.join(output_dir, f'{self.ticker}_trades.csv'))

    # 포트폴리오 가치 저장
    portfolio_value = portfolio.value()
    portfolio_value.to_csv(os.path.join(output_dir, f'{self.ticker}_portfolio_value.csv'))

    # 상세 데이터프레임 저장 (신호 포함)
    entries, exits, size = self.generate_signals()
    result_df = self.df.copy()
    result_df['Entry'] = entries
    result_df['Exit'] = exits
    result_df['Size'] = size
    result_df.to_csv(os.path.join(output_dir, f'{self.ticker}_backtest_results.csv'))


def run_backtest_for_ticker(ticker, name, start_date_str, end_date_str):
  """개별 티커에 대한 백테스트 실행"""
  print(f"Processing {ticker} ({name})...")

  data = fdr.DataReader(ticker, start=start_date_str, end=end_date_str)

  if data.empty:
    print(f"No data found for {ticker}, skipping.")
    return None

  # 전략 실행
  strategy = GlobalShortTermStrategy(data, ticker)
  portfolio = strategy.run_backtest()
  results = strategy.get_results(portfolio)

  # 결과 저장
  strategy.save_results(portfolio)

  return results


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
    result = run_backtest_for_ticker(ticker, name, start_date_str, end_date_str)

    if result:
      results[name] = result

  # 결과 출력
  print("\n" + "="*80)
  print("Backtest Results Summary")
  print("="*80)

  for name, metrics in results.items():
    print(f"\n{name}:")
    print(f"  Average Return per Trade: {metrics['avg_return']:.2f}%")
    print(f"  Total Return: {metrics['total_return']:.2f}%")
    print(f"  Win Rate: {metrics['win_rate']:.2f}%")
    print(f"  Average Holding Period: {metrics['avg_holding_period']:.2f} days")
    print(f"  Buy Count: {metrics['buy_count']}")
    print(f"  Max Drawdown: {metrics['max_drawdown']:.2f}%")
    print(f"  Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")

  # 결과를 JSON으로 저장
  output_dir = 'global/buy-and-sell'
  os.makedirs(output_dir, exist_ok=True)

  summary = {
    name: {k: float(v) if not isinstance(v, (int, pd.DataFrame)) else v
           for k, v in metrics.items() if k != 'trades'}
    for name, metrics in results.items()
  }

  with open(os.path.join(output_dir, 'summary_results.json'), 'w') as f:
    json.dump(summary, f, indent=2)