import json
import os
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import backtrader as bt
import pandas as pd


class DynamicBuyStrategy(bt.Strategy):
  """
  Dynamic buy strategy with adaptive sell logic based on consecutive buy count.
  Supports multiple buy orders within the same group.
  Records each individual buy and sell transaction separately.
  """
  params = (
    ('rsi_threshold', 35),
    ('rsi_second_buy', 30),
    ('printlog', True),
  )

  def __init__(self):
    # Indicators
    self.rsi = bt.indicators.RSI(self.data.close, period=14)
    self.ma_10 = bt.indicators.SMA(self.data.close, period=10)
    self.ma_20 = bt.indicators.SMA(self.data.close, period=20)

    # Bullish detection (Close > Open)
    self.bullish = self.data.close > self.data.open

    # MA cross detection
    self.ma_10_cross = bt.indicators.CrossOver(self.data.close, self.ma_10)
    self.ma_20_cross = bt.indicators.CrossOver(self.data.close, self.ma_20)

    # Trade tracking variables
    self.order = None

    # Group tracking
    self.in_position = False  # Custom position flag
    self.current_group_buy_count = 0
    self.group_consecutive_buys = 0
    self.last_buy_price = None
    self.group_first_buy_price = None

    # Track all buys in current group
    self.current_group_buys = []  # List of {date, price, size, rsi}

    # Statistics
    self.trade_returns = []
    self.holding_periods = []
    self.buy_count = 0

    # Results storage - separate logs for buys and sells
    self.transactions_log = []

  def notify_order(self, order):
    if order.status in [order.Submitted, order.Accepted]:
      return

    if order.status in [order.Completed]:
      if order.isbuy():
        buy_date = self.data.datetime.date(0)
        buy_price = order.executed.price
        buy_size = order.executed.size
        buy_rsi = self.rsi[0]

        # Record individual buy transaction
        self.transactions_log.append({
          'Date': buy_date,
          'Action': 'Buy',
          'Price': buy_price,
          'Size': buy_size,
          'RSI': buy_rsi,
          'MA_10': self.ma_10[0],
          'MA_20': self.ma_20[0],
          'Change_Rate': (self.data.close[0] / self.data.close[-1] - 1) * 100,
          'Consecutive_Buys': self.group_consecutive_buys,
          'Group_Buy_Count': self.current_group_buy_count,
          'Return': None,
          'Holding_Period': None
        })

        # Add to current group buys
        self.current_group_buys.append({
          'date': buy_date,
          'price': buy_price,
          'size': buy_size,
          'rsi': buy_rsi
        })

        if self.params.printlog:
          print(f'{buy_date} BUY #{self.current_group_buy_count} EXECUTED, '
                f'Price: {buy_price:.2f}, Size: {buy_size:.2f}, RSI: {buy_rsi:.2f}')

      elif order.issell():
        sell_date = self.data.datetime.date(0)
        sell_price = order.executed.price
        sell_size = order.executed.size

        if self.params.printlog:
          print(f'\n{sell_date} GROUP SELL - {len(self.current_group_buys)} positions')

        # Record individual sell transactions for each buy in the group
        for idx, buy_info in enumerate(self.current_group_buys):
          buy_date = buy_info['date']
          buy_price = buy_info['price']
          buy_size = buy_info['size']

          holding_period = (sell_date - buy_date).days
          # Calculate return correctly: (sell_price - buy_price) / buy_price
          trade_return = (sell_price / buy_price - 1) * 100  # Return in percentage

          self.trade_returns.append(trade_return)
          self.holding_periods.append(holding_period)

          # Record sell transaction
          self.transactions_log.append({
            'Date': sell_date,
            'Action': 'Sell',
            'Price': sell_price,
            'Size': buy_size,
            'RSI': self.rsi[0],
            'MA_10': self.ma_10[0],
            'MA_20': self.ma_20[0],
            'Change_Rate': (self.data.close[0] / self.data.close[-1] - 1) * 100,
            'Consecutive_Buys': self.group_consecutive_buys,
            'Group_Buy_Count': len(self.current_group_buys),
            'Return': trade_return,
            'Holding_Period': holding_period
          })

          if self.params.printlog:
            print(f'  └─ Sell #{idx+1}: Buy@{buy_price:.2f} → Sell@{sell_price:.2f}, '
                  f'Return: {trade_return:.2f}%, Holding: {holding_period} days')

        # Reset group tracking after sell
        self.in_position = False
        self.current_group_buy_count = 0
        self.group_consecutive_buys = 0
        self.last_buy_price = None
        self.group_first_buy_price = None
        self.current_group_buys = []

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

  def next(self):
    # Skip if order is pending
    if self.order:
      return

    # Check SELL conditions first (if we have a position)
    if self.in_position and len(self.current_group_buys) > 0:
      should_sell = False

      # Check sell conditions based on consecutive buys
      if self.group_consecutive_buys >= 5:
        # Use snap back condition (MA_20 cross)
        if self.sell_condition_snap_back():
          should_sell = True
      else:
        # Use technical bounce condition (MA_10 cross)
        if self.sell_condition_technical_bounce():
          should_sell = True

      if should_sell:
        # Sell entire position (all accumulated buys)
        total_size = sum(buy['size'] for buy in self.current_group_buys)
        self.order = self.sell(size=total_size)
        return

    # Check BUY conditions
    if self.buy_condition():
      is_first_buy = not self.in_position

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
        self.in_position = True
        self.group_first_buy_price = self.data.close[0]
        # Set initial consecutive buys estimate
        self.group_consecutive_buys = 1
      else:
        # Update consecutive buys count as we add more
        self.group_consecutive_buys = self.current_group_buy_count

  def stop(self):
    """Called when backtest ends."""
    avg_return = sum(self.trade_returns) / len(self.trade_returns) if self.trade_returns else 0
    avg_holding = sum(self.holding_periods) / len(self.holding_periods) if self.holding_periods else 0

    if self.params.printlog:
      print(f'\n=== Strategy Results ===')
      print(f'Total Trades: {len(self.trade_returns)}')
      print(f'Average Return: {avg_return:.2f}%')
      print(f'Average Holding Period: {avg_holding:.2f} days')
      print(f'Total Buy Count: {self.buy_count}')
      print(f'Total Groups: {len([t for t in self.transactions_log if t["Action"] == "Buy" and t["Group_Buy_Count"] == 1])}')


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
    'Average Return': (sum(strat.trade_returns) / len(strat.trade_returns)) if strat.trade_returns else 0,
    'Average Holding Period': (sum(strat.holding_periods) / len(strat.holding_periods)) if strat.holding_periods else 0,
    'Buy Count': strat.buy_count,
    'Total Trades': trades_analyzer.get('total', {}).get('total', 0),
    'Sharpe Ratio': sharpe_analyzer.get('sharperatio', 0) if sharpe_analyzer.get('sharperatio') else 0,
    'Max Drawdown': drawdown_analyzer.get('max', {}).get('drawdown', 0)
  }

  # Save detailed transactions log (each buy and sell as separate row)
  output_dir = 'global/backtrader-results'
  os.makedirs(output_dir, exist_ok=True)

  if strat.transactions_log:
    transactions_df = pd.DataFrame(strat.transactions_log)
    # Sort by date and action for better readability
    transactions_df = transactions_df.sort_values(by=['Date', 'Action'])
    transactions_df.to_csv(os.path.join(output_dir, f'{ticker}_transactions.csv'), index=False)

    # Print summary statistics
    buys = transactions_df[transactions_df['Action'] == 'Buy']
    sells = transactions_df[transactions_df['Action'] == 'Sell']
    print(f"Total Transactions: {len(transactions_df)} (Buys: {len(buys)}, Sells: {len(sells)})")

    # Count groups
    groups = buys[buys['Group_Buy_Count'] == 1]
    print(f"Number of Buy Groups: {len(groups)}")

    if len(sells) > 0:
      avg_group_size = len(buys) / len(groups) if len(groups) > 0 else 0
      print(f"Average Buys per Group: {avg_group_size:.2f}")

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