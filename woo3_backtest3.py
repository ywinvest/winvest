import json
import os
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd
import vectorbt as vbt

import indicators

DEFAULT_RSI_THRESHOLD = 35


class GlobalShortTermStrategy:
  """vectorbt 기반 글로벌 단기 매매 전략"""

  def __init__(self, data, ticker):
    self.data = data
    self.ticker = ticker
    self.df = indicators.calculate_indicators(data.copy())

  def buy_condition(self, df):
    """Broad buy condition for global indices (RSI <= 35)."""
    return (df['RSI'] <= DEFAULT_RSI_THRESHOLD) & (~df['Bullish']) & (df['Change_Rate'] < 0)

  def sell_condition_technical_bounce(self, df):
    """기술적 반등 매도 조건 - 10일선 돌파 (매수 회수가 적을 때)."""
    return (df['Close'] > df['MA_10'])  & df['Bullish'] # & (df['ADX'] > 20) & df['DI']

  def sell_condition_snap_back(self, df):
    """스냅백 매도 조건 - 20일선 돌파 (매수 회수가 많을 때)."""
    return (df['Close'] > df['MA_20'])  & df['Bullish'] & (df['ADX'] > 25) & df['DI']

  def generate_orders(self, init_cash=10000000, max_positions=10):
    """매수/매도 주문 생성 (그룹 단위 거래 지원)

    Args:
        init_cash: 초기 자본금
        max_positions: 최대 동시 보유 포지션 수 (기본값: 10)
    """
    df = self.df

    # 주문 배열 초기화 (양수: 매수, 음수: 매도)
    orders = pd.Series(0.0, index=df.index)

    # 초기 매수 후보 필터링 (buy_condition 메서드 사용)
    buy_candidates_mask = self.buy_condition(df)
    buy_candidates = df[buy_candidates_mask]

    # 상태 변수
    group_buy_count = 0
    group_position_size = 0  # 현재 보유 포지션 총량
    last_buy_price = None
    sell_date = None
    current_sell_condition = self.sell_condition_technical_bounce  # 현재 매도 조건 함수

    # 각 매수 시 투자할 기본 금액 계산 (초기 자본을 최대 포지션 수로 분할)
    base_investment = init_cash / max_positions

    for i, buy_date in enumerate(buy_candidates.index):
      should_buy = True
      is_first_buy = group_buy_count == 0

      # 첫 매수가 아닌 경우 추가 검증
      if not is_first_buy:
        current_price = df.loc[buy_date, 'Close']

        # 조건 1: 가격이 올랐으면 스킵
        if last_buy_price is not None and current_price >= last_buy_price:
          should_buy = False

        # 조건 2: RSI 조건
        if should_buy:
          rsi = df.loc[buy_date, 'RSI']
          rsi_threshold = 30 if group_buy_count == 1 else DEFAULT_RSI_THRESHOLD
          if rsi > rsi_threshold:
            should_buy = False

      if should_buy:
        # 포지션 사이즈 가중치 계산
        rsi = df.loc[buy_date, 'RSI']
        change_rate = df.loc[buy_date, 'Change_Rate']

        if group_buy_count < 5:
          weight = 1
        else:
          weight = 2
          # 두 번째 매수 이후에만 RSI 추가 가중치 적용
          if rsi <= 20:
            weight += 1

        if change_rate < -5:
          weight += 1

        # if rsi <= 20:
        #   weight = 3
        # elif rsi <= 30:
        #   weight = 2
        # else:
        #   weight = 1
        #
        # if change_rate < -5:
        #   weight += 1

        # 실제 투자 금액 계산
        investment_amount = base_investment * weight
        buy_price = df.loc[buy_date, 'Close']

        # 매수할 수량 계산 (금액 / 종가)
        position_size = investment_amount / buy_price

        # 매수 실행
        orders.loc[buy_date] = position_size
        group_position_size += position_size

        group_buy_count += 1
        last_buy_price = buy_price

        # 5회 이상 매수 시 스냅백 조건으로 전환
        if group_buy_count >= 5:
          current_sell_condition = self.sell_condition_snap_back

        # 매도 날짜 계산 (current_sell_condition 사용)
        subsequent_data = df.loc[buy_date:]
        sell_mask = current_sell_condition(subsequent_data)

        if sell_mask.any():
          sell_date = sell_mask.idxmax()

      # 매도 신호가 다음 매수 전에 발생하는지 확인
      next_buy_date = buy_candidates.index[i + 1] if i + 1 < len(buy_candidates.index) else None

      # 매도 신호가 있고, (다음 매수가 없거나 다음 매수 전에 발생)하면 즉시 그룹 청산
      if sell_date is not None and (next_buy_date is None or sell_date <= next_buy_date):
        if group_position_size > 0:
          orders.loc[sell_date] = -group_position_size

          # 상태 초기화
          group_buy_count = 0
          group_position_size = 0
          last_buy_price = None
          current_sell_condition = self.sell_condition_technical_bounce

    return orders

  def run_backtest(self, init_cash=10000000, fees=0, max_positions=20):
    """vectorbt를 사용한 백테스트 실행 (from_orders 사용)

    Args:
        init_cash: 초기 자본금
        fees: 거래 수수료 (비율)
        max_positions: 최대 동시 보유 포지션 수
    """
    orders = self.generate_orders(init_cash=init_cash, max_positions=max_positions)

    # vectorbt Portfolio 생성 (from_orders 사용)
    portfolio = vbt.Portfolio.from_orders(
        close=self.df['Close'],
        size=orders,
        size_type='amount',
        direction='longonly',
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
        'max_drawdown': 0,
        'sharpe_ratio': 0
      }

    # 수익률 계산
    returns = trades['Return'].values

    avg_return = returns.mean() if len(returns) > 0 else 0

    holding_periods = (trades['Exit Timestamp'] - trades['Entry Timestamp']).dt.days
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

    # 상세 데이터프레임 저장 (주문 포함)
    # orders = self.generate_orders(init_cash=10000000, max_positions=20)
    # result_df = self.df.copy()
    orders = portfolio.orders.records_readable
    orders.to_csv(os.path.join(output_dir, f'{self.ticker}_orders.csv'))

    # result_df['Orders'] = orders
    # result_df.to_csv(os.path.join(output_dir, f'{self.ticker}_backtest_results.csv'))

  def visualize_results(self, portfolio, output_dir='global/buy-and-sell'):
    """vectorbt 내장 기능을 활용한 간단한 시각화"""
    os.makedirs(output_dir, exist_ok=True)

    # vectorbt의 plot() 메서드로 한 번에 시각화
    # 기본적으로 포트폴리오 가치, 드로다운, 거래 등을 모두 표시
    fig = portfolio.plot(
        subplots=[
          'cum_returns',  # 누적 수익률
          'trades',       # 거래 마커가 포함된 가격 차트
          'drawdowns'     # 드로다운
        ]
    )

    # 레이아웃 조정
    fig.update_layout(
        title_text=f"{self.ticker} Strategy Analysis",
        height=1000,
        showlegend=True
    )

    # 저장
    output_path = os.path.join(output_dir, f'{self.ticker}_analysis.html')
    fig.write_html(output_path)
    print(f"  [Plot Saved] {output_path}")

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

  # 시각화 실행
  strategy.visualize_results(portfolio)

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