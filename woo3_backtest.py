import json
import os
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import backtrader as bt
import pandas as pd


class DynamicBuyStrategy(bt.Strategy):
  """
  Dynamic buy strategy with adaptive sell logic based on consecutive buy count.
  """
  params = (
    ('rsi_threshold', 35),
    ('rsi_second_buy', 30),
    ('printlog', True),
  )

  def __init__(self):
    # Indicators
    self.rsi = bt.indicators.RSI_SMA(self.data.close, period=14)
    self.ma_10 = bt.indicators.SMA(self.data.close, period=10)
    self.ma_20 = bt.indicators.SMA(self.data.close, period=20)

    # Bullish detection (Close > MA_20)
    self.bullish = self.data.close > self.ma_20

    # MA cross detection
    self.ma_10_cross = bt.indicators.CrossOver(self.data.close, self.ma_10)
    self.ma_20_cross = bt.indicators.CrossOver(self.data.close, self.ma_20)

    # Trade tracking variables
    self.order = None
    self.buy_price = None
    self.buy_date = None

    # Group tracking
    self.current_buy_group_flag = False
    self.current_group_buy_count = 0
    self.group_consecutive_buys = 0
    self.last_buy_price = None
    self.group_first_buy_price = None

    # Statistics
    self.trade_returns = []
    self.holding_periods = []
    self.buy_count = 0

    # Results storage
    self.trades_log = []

  def notify_order(self, order):
    if order.status in [order.Submitted, order.Accepted]:
      return

    if order.status in [order.Completed]:
      if order.isbuy():
        self.buy_price = order.executed.price
        self.buy_date = self.data.datetime.date(0)

        if self.params.printlog:
          print(f'{self.data.datetime.date(0)} BUY EXECUTED, Price: {order.executed.price:.2f}, '
                f'Size: {order.executed.size:.2f}, RSI: {self.rsi[0]:.2f}')

      elif order.issell():
        holding_period = (self.data.datetime.date(0) - self.buy_date).days
        trade_return = (order.executed.price / self.buy_price - 1) * order.executed.size

        self.trade_returns.append(trade_return)
        self.holding_periods.append(holding_period)

        if self.params.printlog:
          print(f'{self.data.datetime.date(0)} SELL EXECUTED, Price: {order.executed.price:.2f}, '
                f'Return: {trade_return*100:.2f}%, Holding: {holding_period} days')

        # Log trade details
        self.trades_log.append({
          'buy_date': self.buy_date,
          'sell_date': self.data.datetime.date(0),
          'buy_price': self.buy_price,
          'sell_price': order.executed.price,
          'return': trade_return,
          'holding_period': holding_period,
          'consecutive_buys': self.group_consecutive_buys
        })

        # Reset group tracking after sell
        self.current_buy_group_flag = False
        self.current_group_buy_count = 0
        self.group_consecutive_buys = 0
        self.last_buy_price = None
        self.group_first_buy_price = None

    self.order = None

  def buy_condition(self):
    """Check if buy condition is met."""
    change_rate = (self.data.close[0] / self.data.close[-1] - 1) * 100
    return (self.rsi[0] <= self.params.rsi_threshold and
            not self.bullish[0] and
            change_rate < 0)

  def sell_condition_technical_bounce(self):
    """Technical bounce sell condition - MA_10 cross."""
    return self.ma_10_cross[0] > 0 and self.bullish[0]

  def sell_condition_snap_back(self):
    """Snap back sell condition - MA_20 cross."""
    return self.ma_20_cross[0] > 0 and self.bullish[0]

  def count_potential_buys(self, start_idx):
    """Count potential consecutive buys from start index."""
    count = 1
    temp_last_price = self.data.close[0]
    next_buy_order = 2

    # Look ahead in historical data (simulation only)
    # In live trading, this would need to be adjusted
    for i in range(1, min(200, len(self.data))):
      if start_idx + i >= len(self.data):
        break

      future_close = self.data.close[-i]
      future_rsi = self.rsi[-i]

      if future_close >= temp_last_price:
        continue

      threshold = 30 if next_buy_order == 2 else self.params.rsi_threshold
      if future_rsi <= threshold:
        count += 1
        temp_last_price = future_close
        next_buy_order += 1

    return count

  def next(self):
    # Skip if order is pending
    if self.order:
      return

    # Check if we have a position
    if not self.position:
      # Check buy conditions
      if self.buy_condition():
        is_first_buy = not self.current_buy_group_flag

        # Price condition check (not for first buy)
        if not is_first_buy:
          if self.last_buy_price is None or self.data.close[0] >= self.last_buy_price:
            return

        # RSI condition verification
        current_rsi = self.rsi[0]
        if is_first_buy:
          required_rsi = self.params.rsi_threshold
        else:
          check_order = self.current_group_buy_count + 1
          required_rsi = 30 if check_order == 2 else self.params.rsi_threshold

        if current_rsi > required_rsi:
          return

        # Calculate position size
        change_rate = (self.data.close[0] / self.data.close[-1] - 1) * 100

        if current_rsi <= 20:
          position_size = 3
        elif current_rsi <= 30:
          position_size = 2
        else:
          position_size = 1

        if change_rate < -5:
          position_size += 1

        # Execute buy
        self.order = self.buy(size=position_size)
        self.last_buy_price = self.data.close[0]
        self.current_group_buy_count += 1
        self.buy_count += 1

        # Group initialization
        if is_first_buy:
          self.current_buy_group_flag = True
          self.group_first_buy_price = self.data.close[0]

          # Estimate consecutive buys (simplified)
          self.group_consecutive_buys = self.current_group_buy_count

    else:
      # Check sell conditions based on consecutive buys
      if self.group_consecutive_buys >= 5:
        # Use snap back condition (MA_20 cross)
        if self.sell_condition_snap_back():
          self.order = self.sell(size=self.position.size)
      else:
        # Use technical bounce condition (MA_10 cross)
        if self.sell_condition_technical_bounce():
          self.order = self.sell(size=self.position.size)

  def stop(self):
    """Called when backtest ends."""
    avg_return = sum(self.trade_returns) / len(self.trade_returns) if self.trade_returns else 0
    avg_holding = sum(self.holding_periods) / len(self.holding_periods) if self.holding_periods else 0

    if self.params.printlog:
      print(f'\n=== Strategy Results ===')
      print(f'Total Trades: {len(self.trade_returns)}')
      print(f'Average Return: {avg_return*100:.2f}%')
      print(f'Average Holding Period: {avg_holding:.2f} days')
      print(f'Total Buy Count: {self.buy_count}')


def run_backtest(ticker, name, data, start_date, end_date):
  """Run backtest for a single ticker using Backtrader."""

  # Prepare data for Backtrader
  df = data.copy()
  df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
  df.columns = ['open', 'high', 'low', 'close', 'volume']

  # Create Backtrader data feed
  bt_data = bt.feeds.PandasData(
      dataname=df,
      fromdate=start_date,
      todate=end_date
  )

  # Create cerebro instance
  cerebro = bt.Cerebro()

  # Add data
  cerebro.adddata(bt_data)

  # Add strategy
  cerebro.addstrategy(DynamicBuyStrategy)

  # Set initial capital
  cerebro.broker.setcash(100000.0)

  # Set commission
  cerebro.broker.setcommission(commission=0.001)

  # Add analyzers
  cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
  cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
  cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
  cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

  print(f'\n{"="*60}')
  print(f'Starting Portfolio Value for {name}: {cerebro.broker.getvalue():.2f}')

  # Run backtest
  results = cerebro.run()
  strat = results[0]

  print(f'Final Portfolio Value for {name}: {cerebro.broker.getvalue():.2f}')
  print(f'{"="*60}\n')

  # Extract results
  returns_analyzer = strat.analyzers.returns.get_analysis()
  sharpe_analyzer = strat.analyzers.sharpe.get_analysis()
  drawdown_analyzer = strat.analyzers.drawdown.get_analysis()
  trades_analyzer = strat.analyzers.trades.get_analysis()

  results_dict = {
    'Total Return': returns_analyzer.get('rtot', 0) * 100,
    'Average Return': (sum(strat.trade_returns) / len(strat.trade_returns) * 100) if strat.trade_returns else 0,
    'Average Holding Period': (sum(strat.holding_periods) / len(strat.holding_periods)) if strat.holding_periods else 0,
    'Buy Count': strat.buy_count,
    'Total Trades': trades_analyzer.get('total', {}).get('total', 0),
    'Sharpe Ratio': sharpe_analyzer.get('sharperatio', 0) if sharpe_analyzer.get('sharperatio') else 0,
    'Max Drawdown': drawdown_analyzer.get('max', {}).get('drawdown', 0)
  }

  # Save trades log
  output_dir = 'global/backtrader-results'
  os.makedirs(output_dir, exist_ok=True)

  if strat.trades_log:
    trades_df = pd.DataFrame(strat.trades_log)
    trades_df.to_csv(os.path.join(output_dir, f'{ticker}_trades.csv'), index=False)

  # Plot if needed (optional - requires matplotlib)
  # cerebro.plot()

  return results_dict


if __name__ == "__main__":
  with open('config-woo3.json', 'r') as config_file:
    config = json.load(config_file)

  tickers = config["global"]["tickers"]
  all_results = {}

  end_date = datetime.today()
  start_date = end_date - timedelta(days=30 * 365)

  for ticker, name in tickers.items():
    print(f"\nProcessing {ticker} ({name})...")

    data = fdr.DataReader(ticker, start=start_date.strftime('%Y-%m-%d'),
                          end=end_date.strftime('%Y-%m-%d'))

    if data.empty:
      print(f"No data found for {ticker}, skipping.")
      continue

    results = run_backtest(ticker, name, data, start_date, end_date)
    all_results[name] = results

  # Print summary
  print("\n" + "="*80)
  print("BACKTEST SUMMARY RESULTS")
  print("="*80)
  for name, metrics in all_results.items():
    print(f"\n{name}:")
    print(f"  Total Return: {metrics['Total Return']:.2f}%")
    print(f"  Average Return per Trade: {metrics['Average Return']:.2f}%")
    print(f"  Average Holding Period: {metrics['Average Holding Period']:.2f} days")
    print(f"  Buy Count: {metrics['Buy Count']}")
    print(f"  Total Trades: {metrics['Total Trades']}")
    print(f"  Sharpe Ratio: {metrics['Sharpe Ratio']:.2f}")
    print(f"  Max Drawdown: {metrics['Max Drawdown']:.2f}%")