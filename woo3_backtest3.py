import json
import os
from collections import namedtuple
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
import vectorbt as vbt
from numba import njit

import indicators

DEFAULT_RSI_THRESHOLD = 35

# -----------------------------------------------------------------------------
# 1. 데이터 준비 헬퍼 함수 (Helper Function)
# -----------------------------------------------------------------------------
def prepare_strategy_data(df):
  """
  DataFrame의 모든 컬럼을 소문자 필드명을 가진 NamedTuple로 변환하여 반환합니다.
  Numba(@njit) 함수인 strategy_nb에 데이터를 한 번에 넘기기 위해 사용됩니다.

  예: df['RSI'] -> data.rsi, df['MA_10_Cross'] -> data.ma_10_cross
  """
  # 1. 컬럼명을 소문자로 변환 (strategy_nb에서 data.rsi 처럼 접근하기 위함)
  # 공백이나 특수문자가 있다면 _로 치환하는 등의 처리가 필요할 수 있으나,
  # 일반적인 지표 이름(영어)이라 가정하고 소문자 변환만 수행합니다.
  field_names = [col.lower() for col in df.columns]

  # 2. 동적으로 NamedTuple 클래스 정의 (Type Name: 'StrategyData')
  StrategyData = namedtuple('StrategyData', field_names)

  # 3. 각 컬럼을 vectorbt 호환 2D 배열로 변환
  # (vbt.to_2d_array는 Series를 (N, 1) 형태의 NumPy 배열로 변환해줍니다)
  data_values = [vbt.to_2d_array(df[col]) for col in df.columns]

  # 4. NamedTuple 인스턴스 생성 및 반환
  return StrategyData(*data_values)


# -----------------------------------------------------------------------------
# 2. 로직 함수 분리 (Signal Logic) - @njit (Pure Functions)
# -----------------------------------------------------------------------------

@njit
def check_sell_signal_nb(i, col, price, data, buy_count):
  """
  매도 조건 판단 함수
  True 반환 시 매도
  """
  # 1. 스냅백 매도 조건 (매수 횟수 4회 이상일 때)
  if buy_count >= 4:
    # 조건: 20일선 위 & 상승추세 & ADX>25 & DI
    # data.ma_20 처럼 소문자로 접근 (prepare_strategy_data에서 변환됨)
    is_snap_back = (price > data.ma_20[i, col]) and \
                   data.bullish[i, col] and \
                   (data.adx[i, col] > 25) and \
                   data.di[i, col]
    return is_snap_back

  # 2. 기술적 반등 매도 조건 (매수 횟수 적을 때)
  else:
    # 조건: 10일선 돌파 & 상승추세
    is_tech_bounce = data.ma_10_cross[i, col] and data.bullish[i, col]
    return is_tech_bounce

@njit
def check_buy_signal_nb(i, col, price, data, buy_count, last_buy_price):
  """
  매수 조건 판단 함수
  True 반환 시 매수 진행
  """
  # 기본 조건: RSI 과매도(35이하) & 비추세(Bearish) & 가격 하락
  base_condition = (data.rsi[i, col] <= DEFAULT_RSI_THRESHOLD) and \
                   (not data.bullish[i, col]) and \
                   (data.change_rate[i, col] < 0)

  if not base_condition:
    return False

  # 신규 진입인 경우 (buy_count == 0)
  if buy_count == 0:
    return True

  # 추가 매수(물타기)인 경우
  else:
    # 조건 1: 가격이 직전 매수가보다 낮아야 함 (평단 관리)
    if price >= last_buy_price:
      return False

    # 조건 2: 물타기 시 RSI 기준 강화
    # 첫 물타기(2회차, buy_count==1)는 RSI 30 이하, 그 외는 35 이하(base_condition)
    if buy_count == 1:
      if data.rsi[i, col] > 30:
        return False

    return True

# -----------------------------------------------------------------------------
# 3. 메인 실행 함수 (Execution Logic) - @njit
# -----------------------------------------------------------------------------

@njit
def strategy_nb(c, data, buy_count_state, last_price_state, max_positions, init_cash_val):
  """
  vectorbt가 매 스텝마다 호출하는 메인 함수.
  """
  i = c.i
  col = c.col

  current_price = c.val_price_now
  current_pos = c.position_now
  cash_now = c.cash_now

  # 상태 변수 로드 (State Loading)
  buy_count = buy_count_state[col]
  last_buy_price = last_price_state[col]

  # --- 1. 매도 판단 (Sell Logic) ---
  if current_pos > 0:
    if check_sell_signal_nb(i, col, current_price, data, buy_count):
      # 상태 초기화
      buy_count_state[col] = 0
      last_price_state[col] = 0.0

      # 전량 매도 주문
      return vbt.OrderResult(
          size=-current_pos,
          size_type=vbt.SizeType.Amount,
          price=current_price,
          fees=0.0,
          slippage=0.0
      )

  # --- 2. 매수 판단 (Buy Logic) ---
  # check_buy_signal_nb 함수를 통해 매수 여부만 먼저 확인
  if check_buy_signal_nb(i, col, current_price, data, buy_count, last_buy_price):

    # 가중치(Weight) 계산 로직
    new_buy_count = buy_count + 1
    weight = 1

    # 4회차 이상 (공격적 물타기 구간)
    if new_buy_count >= 4:
      weight = 2
      if data.rsi[i, col] <= 20:
        weight += 1
    # 초기 구간 (< 4회)
    else:
      weight = 1

    # 하락폭이 크면(-5% 이상) 가중치 추가 (모든 구간 적용)
    if data.change_rate[i, col] < -5:
      weight += 1

    # 투자 금액 계산 (Target Amount)
    base_investment = init_cash_val / max_positions
    target_amount = base_investment * weight

    # 가용 현금 내에서만 매수
    if target_amount > cash_now:
      target_amount = cash_now

    # 매수 실행
    if target_amount > 0:
      # 상태 업데이트
      buy_count_state[col] = new_buy_count
      last_price_state[col] = current_price

      # 수량 계산하여 주문
      return vbt.OrderResult(
          size=target_amount / current_price,
          size_type=vbt.SizeType.Amount,
          price=current_price,
          fees=0.0,
          slippage=0.0
      )

  return vbt.NoOrder

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
    return df['MA_10_Cross'] & df['Bullish'] # & (df['ADX'] > 20) & df['DI']

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
        buy_price = df.loc[buy_date, 'Close']
        change_rate = df.loc[buy_date, 'Change_Rate']

        last_buy_price = buy_price
        group_buy_count += 1

        if group_buy_count < 4:
          weight = 1
        else:
          weight = 2
          # 4회 이상 매수 시에만 RSI 20 이하 조건 체크
          if rsi <= 20:
            weight += 1
          # 4회 이상 매수 시 즉시 매도 조건 변경
          current_sell_condition = self.sell_condition_snap_back

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

        # 매수할 수량 계산 (금액 / 종가)
        position_size = investment_amount / buy_price

        # 매수 실행
        orders.loc[buy_date] += position_size
        group_position_size += position_size

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
          orders.loc[sell_date] += -group_position_size

          # 상태 초기화
          group_buy_count = 0
          group_position_size = 0
          last_buy_price = None
          current_sell_condition = self.sell_condition_technical_bounce

    return orders

  def run_backtest(self, init_cash=10000000, fees=0, max_positions=20):
    # 1. 데이터 준비 (Prepare Data)
    # DataFrame을 NamedTuple(StrategyData)로 변환
    market_data = prepare_strategy_data(self.df)

    # 2. 상태 관리 배열 초기화 (Initialize State)
    # market_data 내 임의의 필드(예: close)를 사용하여 shape 확인
    n_cols = market_data.close.shape[1]

    buy_count_state = np.zeros(n_cols, dtype=np.int_)
    last_price_state = np.zeros(n_cols, dtype=np.float_)

    # 3. 백테스트 실행 (Run Simulation)
    portfolio = vbt.Portfolio.from_order_func(
        self.df['Close'],
        strategy_nb,                 # 모듈 레벨의 Numba 함수 전달

        # *order_args 전달 (strategy_nb의 인자 순서와 일치해야 함)
        market_data,      # 1. 데이터 뭉치 (NamedTuple)
        buy_count_state,             # 2. 상태 변수 1
        last_price_state,            # 3. 상태 변수 2
        max_positions,               # 4. 설정값 1
        float(init_cash),            # 5. 설정값 2

        # **kwargs 설정
        init_cash=init_cash,
        fees=fees,
        freq='1D'
    )
    return portfolio

  def get_results(self, portfolio):
    """결과 지표 계산"""
    trades = portfolio.trades.records_readable

    if len(trades) == 0:
      return {
        'avg_return': 0, 'avg_holding_period': 0, 'buy_count': 0,
        'total_return': 0, 'win_rate': 0, 'max_drawdown': 0,
        'sharpe_ratio': 0, 'trades': pd.DataFrame()
      }

    returns = trades['Return'].values
    holding_periods = (trades['Exit Timestamp'] - trades['Entry Timestamp']).dt.days

    return {
      'avg_return': returns.mean() * 100,
      'avg_holding_period': holding_periods.mean() if len(holding_periods) > 0 else 0,
      'buy_count': len(trades),
      'total_return': portfolio.total_return() * 100,
      'win_rate': (returns > 0).sum() / len(returns) * 100 if len(returns) > 0 else 0,
      'max_drawdown': portfolio.max_drawdown() * 100,
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

    # 2. 통합 Daily Result 생성 (기존 backtest_results.csv 포맷 재현)
    # 원본 데이터프레임 복사
    daily_df = self.df.copy()

    # vectorbt 포트폴리오 상태 병합 (인덱스가 날짜로 동일하다고 가정)
    daily_df['Cash'] = portfolio.cash()          # 현금 잔고
    daily_df['Holdings'] = portfolio.assets()    # 보유 수량
    daily_df['Total_Value'] = portfolio.value()  # 총 자산 가치

    # 매수/매도 액션 및 수량 계산
    # asset_flow: 자산(수량)의 변화량. (+: 매수, -: 매도)
    asset_flow = portfolio.asset_flow()
    daily_df['Order_Amt'] = asset_flow

    # Action 컬럼 생성 (Buy/Sell/Wait)
    daily_df['Action'] = daily_df['Order_Amt'].apply(
        lambda x: 'Buy' if x > 0 else ('Sell' if x < 0 else '')
    )

    if not orders.empty:
      # 원본 보존을 위해 복사 및 날짜 정규화 (시간 제거, join을 위해)
      orders_df = orders.copy()
      orders_df['Timestamp'] = pd.to_datetime(orders_df['Timestamp']).dt.normalize()

      # 'Type' 컬럼 생성 (Side가 없거나 부정확할 경우를 대비해 Size로 판단)
      # vectorbt의 기본 Side 컬럼을 우선 사용하되, 없으면 Size로 추론
      if 'Side' in orders_df.columns:
        orders_df['Type'] = orders_df['Side'] # 'Buy', 'Sell'
      else:
        orders_df['Type'] = orders_df['Size'].apply(lambda x: 'Buy' if x > 0 else 'Sell')

      # 1) 그룹 ID 생성: 매도(Sell)가 발생한 직후 그룹 ID를 변경
      # 로직: 'Sell' 행은 현재 그룹의 종료이므로, 그 다음 행부터 ID가 증가해야 함
      # (Shift하여 Sell이었던 곳 다음을 True로 만들고 누적 합)
      orders_df['Group_ID'] = (orders_df['Type'] == 'Sell').shift(1).fillna(False).cumsum()

      # 2) 그룹별 청산(Exit) 정보 추출
      # 각 그룹의 'Sell' 행에서 가격(청산가) 추출
      exit_prices = orders_df[orders_df['Type'] == 'Sell'].set_index('Group_ID')['Price']
      exit_prices.name = 'Exit_Price'

      # 3) 개별 매수 건 수익률 계산 (Return)
      # 매수(Buy) 행만 필터링
      buys_df = orders_df[orders_df['Type'] == 'Buy'].copy()

      # 청산가(Exit_Price)를 Group_ID 기준으로 매핑
      buys_df = buys_df.join(exit_prices, on='Group_ID')

      # 수익률 계산: (청산가 - 매수가) / 매수가
      buys_df['Return'] = (buys_df['Exit_Price'] - buys_df['Price']) / buys_df['Price']

      # 날짜별 매핑 (하루에 여러 매수 건이 있을 경우 평균)
      daily_returns = buys_df.groupby('Timestamp')['Return'].mean()

      # 4) 그룹 전체 수익률 계산 (Group_Return)
      # 그룹별 평균 진입 단가 계산 (가중 평균)
      buys_df['Cost_Sum'] = buys_df['Price'] * buys_df['Size']
      group_stats = buys_df.groupby('Group_ID')[['Cost_Sum', 'Size']].sum()
      group_avg_price = group_stats['Cost_Sum'] / group_stats['Size']

      # 매도(Sell) 행만 필터링
      sells_df = orders_df[orders_df['Type'] == 'Sell'].copy()

      # 평균 진입가 매핑
      sells_df['Avg_Entry_Price'] = sells_df['Group_ID'].map(group_avg_price)

      # 수익률 계산: (매도가 - 평단가) / 평단가
      sells_df['Group_Return'] = (sells_df['Price'] - sells_df['Avg_Entry_Price']) / sells_df['Avg_Entry_Price']

      # 날짜별 매핑
      daily_group_returns = sells_df.set_index('Timestamp')['Group_Return']

      # 5) Daily DF에 병합 (Left Join)
      daily_df = daily_df.join(daily_returns, how='left')
      daily_df = daily_df.join(daily_group_returns, how='left')

    else:
      daily_df['Return'] = None
      daily_df['Group_Return'] = None

    # # 주요 컬럼 순서 재배치 (가독성을 위해)
    # # 보고 싶은 보조지표들을 앞쪽에 배치
    # cols_order = [
    #   'Close', 'Change_Rate', 'RSI', 'Bullish', 'MA_10', 'MA_20', 'ADX', 'DI', # 주요 지표
    #   'Action', 'Order_Amt', 'Exec_Price', # 거래 정보
    #   'Holdings', 'Cash', 'Total_Value'    # 계좌 정보
    # ]
    #
    # # 기존 df에 있지만 위 리스트에 없는 컬럼들도 뒤에 붙여줌
    # remaining_cols = [c for c in daily_df.columns if c not in cols_order]
    # final_df = daily_df[cols_order + remaining_cols]

    # 저장
    daily_df.to_csv(os.path.join(output_dir, f'{self.ticker}_backtest_results.csv'))
    print(f"  [Results Saved] {output_dir}/{self.ticker}_backtest_results.csv")

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