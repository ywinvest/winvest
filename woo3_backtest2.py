import json
import os
from datetime import datetime, timedelta

import backtrader as bt
import FinanceDataReader as fdr
import pandas as pd

# RSI 임계값
DEFAULT_RSI_THRESHOLD = 35


class CloseOrderExecutor(bt.observers.Broker):
  """당일 종가 체결을 위한 커스텀 Executor"""
  pass


class InstantBroker(bt.brokers.BackBroker):
  """
  당일 종가에 즉시 체결되는 커스텀 브로커
  백테스트 전용 - 실전에서는 애프터장 활용
  """

  def __init__(self):
    super(InstantBroker, self).__init__()

  def _execute(self, order, ago=0, price=None):
    """주문을 당일 종가에 즉시 체결"""
    # 현재 데이터의 종가 가져오기
    if price is None:
      price = order.data.close[ago]

    # 체결 수량
    size = order.size

    # 수수료 계산
    commission = self.getcommissioninfo(order.data).getcommission(size, price)

    # 주문 체결 처리 (올바른 인자 순서)
    order.execute(
        dt=order.data.datetime[ago],
        size=size,
        price=price,
        closed=0,
        closedvalue=0.0,
        closedcomm=0.0,
        opened=size,
        openedvalue=abs(size) * price,
        openedcomm=commission,
        margin=0.0,
        pnl=0.0,
        psize=0,
        pprice=0.0
    )

    order.completed()
    self.notify(order)
    self._bracketize(order, cancel=True)

    return order

  def next(self):
    """매 틱마다 실행 - 주문을 당일 종가에 체결"""
    # 대기 중인 모든 주문 처리
    for order in list(self.orders):
      if order.status == order.Submitted:
        # 당일 종가로 즉시 체결
        self._execute(order, ago=0)


class RSIMAStrategy(bt.Strategy):
  """
  RSI 기반 매수, 이동평균선 돌파 매도 전략
  - Look-ahead 로직 제거
  - 실전형: 현재까지 매수 횟수가 5회 이상이면 목표를 20일선으로 변경
  - 당일 종가 체결 (커스텀 브로커 사용)
  """

  params = (
    ('rsi_period', 14),
    ('ma10_period', 10),
    ('ma20_period', 20),
    ('printlog', True),
  )

  def __init__(self):
    # 지표 계산
    self.rsi = bt.indicators.RSI(self.data.close, period=self.params.rsi_period)
    self.ma10 = bt.indicators.SMA(self.data.close, period=self.params.ma10_period)
    self.ma20 = bt.indicators.SMA(self.data.close, period=self.params.ma20_period)

    # 이동평균선 교차 지표
    self.ma10_cross = bt.indicators.CrossOver(self.data.close, self.ma10)
    self.ma20_cross = bt.indicators.CrossOver(self.data.close, self.ma20)

    # 변화율 계산
    self.change_rate = (self.data.close - self.data.close(-1)) / self.data.close(-1) * 100

    # 상태 변수
    self.last_buy_price = None
    self.current_group_buy_count = 0
    self.total_position_size = 0
    self.weighted_avg_buy_price = 0
    self.sell_target = 'MA10'

    # 매수 그룹별 추적
    self.current_group_entries = []

    # 통계 수집
    self.trade_results = []
    self.buy_dates = []

    # 주문 관리
    self.order = None

  def log(self, txt, dt=None):
    """로깅 함수"""
    if self.params.printlog:
      dt = dt or self.datas[0].datetime.date(0)
      print(f'{dt.isoformat()}: {txt}')

  def notify_order(self, order):
    """주문 상태 알림"""
    if order.status in [order.Submitted, order.Accepted]:
      return

    if order.status in [order.Completed]:
      if order.isbuy():
        self.log(f'BUY EXECUTED, Price: {order.executed.price:.2f}, '
                 f'Size: {order.executed.size:.0f}, '
                 f'Cost: {order.executed.value:.2f}, '
                 f'Comm: {order.executed.comm:.2f}')
      elif order.issell():
        self.log(f'SELL EXECUTED, Price: {order.executed.price:.2f}, '
                 f'Size: {order.executed.size:.0f}, '
                 f'Value: {order.executed.value:.2f}, '
                 f'Comm: {order.executed.comm:.2f}')

    elif order.status in [order.Canceled, order.Margin, order.Rejected]:
      self.log(f'Order Canceled/Margin/Rejected - Status: {order.status}')

    self.order = None

  def notify_trade(self, trade):
    """거래 완료 알림"""
    if not trade.isclosed:
      return

    entry_date = bt.num2date(trade.dtopen).date()
    exit_date = bt.num2date(trade.dtclose).date()
    holding_days = (exit_date - entry_date).days

    trade_size = abs(trade.size) if trade.size != 0 else 1
    trade_value = abs(trade.price * trade_size)

    pnl_pct = (trade.pnl / trade_value * 100) if trade_value != 0 else 0

    self.log(f'TRADE CLOSED - PnL: {trade.pnl:.2f}, PnL%: {pnl_pct:.2f}%, '
             f'Holding: {holding_days} days')

    self.trade_results.append({
      'entry_date': entry_date,
      'exit_date': exit_date,
      'entry_price': trade.price,
      'exit_price': trade.price + (trade.pnl / trade_size if trade_size != 0 else 0),
      'size': trade_size,
      'pnl': trade.pnl,
      'pnl_pct': pnl_pct,
      'holding_days': holding_days
    })

  def check_buy_condition(self):
    """매수 조건 확인"""
    bullish = self.data.close[0] > self.ma10[0]

    return (self.rsi[0] <= DEFAULT_RSI_THRESHOLD and
            not bullish and
            self.change_rate[0] < 0)

  def check_sell_condition(self):
    """매도 조건 확인"""
    bullish = self.data.close[0] > self.ma10[0]

    if self.sell_target == 'MA10':
      return self.ma10_cross[0] > 0 and bullish
    else:
      return self.ma20_cross[0] > 0 and bullish

  def calculate_position_size(self, rsi, change_rate):
    """포지션 크기 계산"""
    if rsi <= 20:
      position_size = 3
    elif rsi <= 30:
      position_size = 2
    else:
      position_size = 1

    if change_rate < -5:
      position_size += 1

    return position_size

  def next(self):
    """매 봉마다 실행 - 당일 종가 데이터로 시그널 감지 및 즉시 체결"""
    if self.order:
      return

    current_date = self.datas[0].datetime.date(0)

    # 포지션이 있을 때 매도 조건 확인
    if self.position and self.check_sell_condition():
      self.log(f'SELL SIGNAL - Target: {self.sell_target}, '
               f'Buy Count: {self.current_group_buy_count}, '
               f'Position Size: {self.position.size}')

      # 전체 포지션 매도 (커스텀 브로커가 당일 종가에 체결)
      self.order = self.close()

      # 상태 초기화
      self.last_buy_price = None
      self.current_group_buy_count = 0
      self.total_position_size = 0
      self.weighted_avg_buy_price = 0
      self.sell_target = 'MA10'
      self.current_group_entries = []
      return

    # 매수 조건 확인
    if self.check_buy_condition():
      is_first_buy = self.current_group_buy_count == 0
      current_price = self.data.close[0]
      current_rsi = self.rsi[0]
      current_change = self.change_rate[0]

      # 추가 매수 시 가격 조건 확인
      if not is_first_buy:
        if current_price >= self.last_buy_price:
          return

      # RSI 조건 검증
      if is_first_buy:
        required_rsi = DEFAULT_RSI_THRESHOLD
      else:
        check_order = self.current_group_buy_count + 1
        if check_order == 2:
          required_rsi = 30
        else:
          required_rsi = DEFAULT_RSI_THRESHOLD

      if current_rsi > required_rsi:
        return

      # 포지션 크기 계산
      position_size = self.calculate_position_size(current_rsi, current_change)

      self.log(f'BUY SIGNAL - RSI: {current_rsi:.2f}, '
               f'Change: {current_change:.2f}%, '
               f'Size: {position_size}, '
               f'Order: {self.current_group_buy_count + 1}')

      # 매수 실행 (커스텀 브로커가 당일 종가에 체결)
      self.order = self.buy(size=position_size)

      # 상태 업데이트
      self.last_buy_price = current_price
      self.current_group_buy_count += 1
      self.buy_dates.append(current_date)

      self.current_group_entries.append((current_date, current_price, position_size))

      # 가중 평균 매수가 계산
      prev_total_value = self.weighted_avg_buy_price * self.total_position_size
      new_value = current_price * position_size
      self.total_position_size += position_size
      self.weighted_avg_buy_price = (prev_total_value + new_value) / self.total_position_size

      # 첫 매수일 때는 10일선 목표로 시작
      if self.current_group_buy_count == 1:
        self.sell_target = 'MA10'

      # 실전형 로직: 매수 횟수가 5회 이상이면 즉시 20일선으로 변경
      if self.current_group_buy_count >= 5:
        if self.sell_target != 'MA20':
          self.log(f'>>> SELL TARGET CHANGED: MA10 -> MA20 '
                   f'(Buy count reached {self.current_group_buy_count})')
          self.sell_target = 'MA20'


class PandasData(bt.feeds.PandasData):
  """FinanceDataReader 데이터를 위한 커스텀 데이터 피드"""
  params = (
    ('datetime', None),
    ('open', 'Open'),
    ('high', 'High'),
    ('low', 'Low'),
    ('close', 'Close'),
    ('volume', 'Volume'),
    ('openinterest', -1),
  )


def run_backtest(ticker, name, data):
  """백테스트 실행"""
  print(f"\n{'='*60}")
  print(f"Processing {ticker} ({name})...")
  print(f"{'='*60}")

  # Cerebro 엔진 생성
  cerebro = bt.Cerebro()

  # *** 커스텀 브로커 설정 (당일 종가 체결) ***
  cerebro.broker = InstantBroker()

  # 전략 추가
  cerebro.addstrategy(RSIMAStrategy, printlog=True)

  # 데이터 추가
  data_feed = PandasData(dataname=data)
  cerebro.adddata(data_feed)

  # 초기 자본금 설정
  cerebro.broker.setcash(100000.0)

  # 수수료 설정 (0.1%)
  cerebro.broker.setcommission(commission=0.001)

  # 시작 포트폴리오 가치
  start_value = cerebro.broker.getvalue()
  print(f'Starting Portfolio Value: {start_value:.2f}')
  print('NOTE: Using custom broker for same-day close execution (backtest only)')

  # 백테스트 실행
  results = cerebro.run()
  strategy = results[0]

  # 종료 포트폴리오 가치
  end_value = cerebro.broker.getvalue()
  print(f'Ending Portfolio Value: {end_value:.2f}')

  total_return = (end_value - start_value) / start_value * 100
  print(f'Total Return: {total_return:.2f}%')

  # 통계 계산
  if strategy.trade_results:
    returns = [t['pnl_pct'] for t in strategy.trade_results]
    holding_periods = [t['holding_days'] for t in strategy.trade_results]

    avg_return = sum(returns) / len(returns)
    avg_holding = sum(holding_periods) / len(holding_periods)
    win_rate = len([r for r in returns if r > 0]) / len(returns) * 100
    total_pnl = sum([t['pnl'] for t in strategy.trade_results])

    print(f'\nTrade Statistics:')
    print(f'Total Trades: {len(strategy.trade_results)}')
    print(f'Total Buy Signals: {len(strategy.buy_dates)}')
    print(f'Total PnL: {total_pnl:.2f}')
    print(f'Average Return per Trade: {avg_return:.2f}%')
    print(f'Average Holding Period: {avg_holding:.2f} days')
    print(f'Win Rate: {win_rate:.2f}%')

    # 결과 저장
    output_dir = 'global/backtrader-results'
    os.makedirs(output_dir, exist_ok=True)

    trades_df = pd.DataFrame(strategy.trade_results)
    trades_df.to_csv(os.path.join(output_dir, f'{ticker}_trades.csv'), index=False)
    print(f'Trade details saved to {output_dir}/{ticker}_trades.csv')

    return {
      'avg_return': avg_return,
      'avg_holding': avg_holding,
      'total_trades': len(strategy.trade_results),
      'buy_count': len(strategy.buy_dates),
      'win_rate': win_rate,
      'total_return': total_return,
      'total_pnl': total_pnl
    }
  else:
    print(f'\nNo trades executed.')
    print(f'Total Buy Signals: {len(strategy.buy_dates)}')

    if len(strategy.buy_dates) > 0:
      print(f'WARNING: Buy signals detected but no completed trades!')

    return {
      'avg_return': 0,
      'avg_holding': 0,
      'total_trades': 0,
      'buy_count': len(strategy.buy_dates),
      'win_rate': 0,
      'total_return': total_return,
      'total_pnl': 0
    }


if __name__ == "__main__":
  # 설정 파일 로드
  with open('config-woo3.json', 'r') as config_file:
    config = json.load(config_file)

  tickers = config["global"]["tickers"]
  results = {}

  # 데이터 기간 설정 (최근 30년)
  end_date = datetime.today()
  start_date = end_date - timedelta(days=30 * 365)

  end_date_str = end_date.strftime('%Y-%m-%d')
  start_date_str = start_date.strftime('%Y-%m-%d')

  # 각 티커별로 백테스트 실행
  for ticker, name in tickers.items():
    try:
      # 데이터 다운로드
      data = fdr.DataReader(ticker, start=start_date_str, end=end_date_str)

      if data.empty:
        print(f"No data found for {ticker}, skipping.")
        continue

      # 백테스트 실행
      result = run_backtest(ticker, name, data)
      results[name] = result

    except Exception as e:
      print(f"Error processing {ticker} ({name}): {str(e)}")
      import traceback
      traceback.print_exc()
      continue

  # 최종 결과 요약
  print("\n" + "="*80)
  print("BACKTEST RESULTS SUMMARY")
  print("="*80)

  for name, metrics in results.items():
    print(f"\n{name}:")
    print(f"  Total Return: {metrics['total_return']:.2f}%")
    print(f"  Total PnL: {metrics['total_pnl']:.2f}")
    print(f"  Average Return per Trade: {metrics['avg_return']:.2f}%")
    print(f"  Average Holding Period: {metrics['avg_holding']:.2f} days")
    print(f"  Total Trades: {metrics['total_trades']}")
    print(f"  Buy Signals: {metrics['buy_count']}")
    print(f"  Win Rate: {metrics['win_rate']:.2f}%")

  # 전체 결과를 CSV로 저장
  output_dir = 'global/backtrader-results'
  os.makedirs(output_dir, exist_ok=True)

  summary_df = pd.DataFrame(results).T
  summary_df.to_csv(os.path.join(output_dir, 'backtest_summary.csv'))
  print(f"\nResults saved to {output_dir}/")