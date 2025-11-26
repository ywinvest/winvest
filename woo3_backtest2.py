import datetime
import backtrader as bt
import FinanceDataReader as fdr
import pandas as pd

# ----------------------------------------
# 1. 전략 클래스 정의
# ----------------------------------------
class RSIMultiBuyStrategy(bt.Strategy):
  params = (
    ('rsi_period', 14),
    ('ma_fast', 10),
    ('ma_slow', 20),
    ('rsi_threshold', 35),
  )

  def __init__(self):
    # 지표 계산
    self.rsi = bt.indicators.RSI(self.data.close, period=self.params.rsi_period)
    self.sma10 = bt.indicators.SMA(self.data.close, period=self.params.ma_fast)
    self.sma20 = bt.indicators.SMA(self.data.close, period=self.params.ma_slow)

    # 캔들 분석용 (Bullish 여부 등)
    self.close = self.data.close
    self.open = self.data.open

    # 내부 상태 변수
    self.order = None
    self.buy_price_history = [] # 이번 그룹의 매수 가격들
    self.group_buy_count = 0    # 이번 그룹의 매수 횟수

  def log(self, txt, dt=None):
    '''로깅 함수'''
    dt = dt or self.datas[0].datetime.date(0)
    # print(f'{dt.isoformat()}, {txt}') # 필요시 주석 해제하여 로그 확인

  def next(self):
    # 1. 현재 캔들 정보
    current_close = self.close[0]
    current_open = self.open[0]
    current_rsi = self.rsi[0]

    # 전일 대비 등락률 계산 (%)
    if len(self.close) > 1:
      prev_close = self.close[-1]
      change_rate = ((current_close - prev_close) / prev_close) * 100
    else:
      change_rate = 0

    # Bullish(양봉) 여부
    is_bullish = current_close >= current_open

    # ----------------------------------------
    # 2. 매도 로직 (청산)
    # ----------------------------------------
    if self.position:
      # 매수 횟수가 5회 미만이면 10일선, 5회 이상이면 20일선 사용
      # 원본 로직: 스냅백(5회 이상) vs 기술적 반등(5회 미만)
      target_ma = self.sma20[0] if self.group_buy_count >= 5 else self.sma10[0]

      # 매도 조건: 양봉이면서 이동평균선 돌파 (Close가 MA보다 위)
      # 원본: df['MA_Cross'] & df['Bullish']
      # 여기서는 당일 종가가 MA보다 높고 양봉이면 매도 (종가 매도 원칙)
      if is_bullish and current_close > target_ma:
        self.close() # 보유 전량 매도
        self.log(f'SELL ALL Executed, Price: {current_close:.2f}, Count: {self.group_buy_count}')

        # 그룹 상태 초기화
        self.buy_price_history = []
        self.group_buy_count = 0
        return

    # ----------------------------------------
    # 3. 매수 로직 (진입 & 물타기)
    # ----------------------------------------

    # 3-1. 매수 기본 조건
    # (RSI <= 35) & (~Bullish) & (Change_Rate < 0)
    # 단, 2번째 매수부터는 RSI 조건이 30으로 강화될 수 있음 (원본 로직 반영)

    required_rsi = self.params.rsi_threshold
    if self.group_buy_count == 1: # 이미 1번 샀고 2번째 살 차례라면
      required_rsi = 30

    condition_met = (
        (current_rsi <= required_rsi) and
        (not is_bullish) and
        (change_rate < 0)
    )

    if not condition_met:
      return

    # 3-2. 가격 조건 (물타기 시 평단가 고려)
    # 원본: current_price >= last_buy_price 이면 매수 안함
    if self.group_buy_count > 0:
      last_buy_price = self.buy_price_history[-1]
      if current_close >= last_buy_price:
        return

    # 3-3. 비중(Weight) 계산
    position_size = 1
    if current_rsi <= 20:
      position_size = 3
    elif current_rsi <= 30:
      position_size = 2

    if change_rate < -5:
      position_size += 1

    # 3-4. 매수 실행 (종가 매수)
    # Backtrader의 buy()는 기본적으로 1주를 삽니다. size 파라미터로 조절.
    # 여기서는 Weight를 주식 수(size)로 단순화하여 처리합니다.
    self.buy(size=position_size)

    self.group_buy_count += 1
    self.buy_price_history.append(current_close)
    self.log(f'BUY Executed, Price: {current_close:.2f}, RSI: {current_rsi:.2f}, Size: {position_size}, Total Count: {self.group_buy_count}')


# ----------------------------------------
# 4. 실행 및 설정
# ----------------------------------------
def run_backtest(ticker, start_date, end_date):
  cerebro = bt.Cerebro()

  # 데이터 가져오기 (FinanceDataReader -> Pandas -> Backtrader)
  df = fdr.DataReader(ticker, start=start_date, end=end_date)

  if df.empty:
    print(f"No data for {ticker}")
    return

  # Backtrader용 데이터 피드로 변환
  data = bt.feeds.PandasData(dataname=df)
  cerebro.adddata(data)

  # 전략 추가
  cerebro.addstrategy(RSIMultiBuyStrategy)

  # 브로커 설정
  cerebro.broker.setcash(10000000) # 초기 자본금 (천만원)

  # *** 핵심: 종가 매매 설정 ***
  # set_coc(True): Cheat-On-Close.
  # 신호가 나온 당일 종가(Close)로 체결을 시킵니다.
  cerebro.broker.set_coc(True)

  print(f'\nStarting Portfolio Value for {ticker}: {cerebro.broker.getvalue():.2f}')

  # 분석기 추가 (승률, 수익률 등)
  cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trade_analyzer')

  # 실행
  results = cerebro.run()
  strat = results[0]

  # 결과 출력
  final_value = cerebro.broker.getvalue()
  print(f'Final Portfolio Value for {ticker}: {final_value:.2f}')

  # 거래 통계
  trade_analysis = strat.analyzers.trade_analyzer.get_analysis()

  # 거래가 있었는지 확인
  if trade_analysis.get('total', {}).get('total', 0) > 0:
    total_trades = trade_analysis.total.total

    # 'won' 키가 없거나 'total' 값이 없을 경우 0으로 기본값 설정
    won_data = trade_analysis.get('won', {})
    win_trades = won_data.get('total', 0)

    win_rate = (win_trades / total_trades) * 100
    pnl_net = trade_analysis.pnl.net.total

    print(f"Total Trades: {total_trades}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Net Profit: {pnl_net:.2f}")
  else:
    print("No trades occurred.")

# 메인 실행 블록
if __name__ == '__main__':
  # 예시 설정
  tickers = {
    "IXIC": "Nasdaq",
  }

  end_date = datetime.datetime.now().strftime('%Y-%m-%d')
  start_date = (datetime.datetime.now() - datetime.timedelta(days=365*30)).strftime('%Y-%m-%d')

  for ticker, name in tickers.items():
    print(f"Processing {ticker} ({name})...")
    run_backtest(ticker, start_date, end_date)