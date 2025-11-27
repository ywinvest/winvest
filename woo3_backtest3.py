import json
import os
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
import vectorbt as vbt

# --- 설정 ---
DEFAULT_RSI_THRESHOLD = 35

# CSV 출력 경로 설정
OUTPUT_DIR = 'global/vbt_backtest_results'

def get_indicators(data):
  """지표 계산 및 캔들 정보 추가"""
  close = data['Close']
  open_price = data['Open']

  rsi = vbt.RSI.run(close, window=14).rsi
  ma10 = vbt.MA.run(close, window=10).ma
  ma20 = vbt.MA.run(close, window=20).ma
  # Change Rate는 퍼센트 단위로 변환
  change_rate = close.pct_change() * 100

  # === [수정된 부분] ===
  # 'Bullish' 대신 is_green_candle (양봉) 사용
  is_green_candle = close > open_price
  # =====================

  return rsi, ma10, ma20, change_rate, is_green_candle

def generate_signals(close, rsi, ma10, ma20, change_rate, is_green_candle):
  """
  State-dependent 로직을 처리하여 Entry/Exit 신호 및 사이즈(Weight) 배열 생성
  """
  n = len(close)
  entries = np.full(n, False)
  exits = np.full(n, False)
  sizes = np.full(n, 0.0) # 매수 시 진입 크기(Weight)

  # 상태 변수
  in_position = False
  group_buy_count = 0
  last_buy_price = None

  # Numpy 배열로 변환
  close_np = close.values
  rsi_np = rsi.values
  ma10_np = ma10.values
  ma20_np = ma20.values
  change_np = change_rate.values
  is_green_np = is_green_candle.values

  for i in range(1, n):
    # 1. 매도(청산) 로직 확인
    if in_position:
      # 매수 횟수가 5회 이상이면 Snap Back(20일선), 아니면 Tech Bounce(10일선)

      # 원본: sell_condition_technical_bounce: df['MA_10_Cross'] & df['Bullish']
      # 원본: sell_condition_snap_back: df['MA_20_Cross'] & df['Bullish']
      # 'Bullish'는 양봉이므로, 매도 조건은 '현재 양봉이면서 이평선을 돌파했을 때'로 해석됩니다.

      # 이평선 돌파를 Cross-Over로 단순화하고, 'Bullish'는 is_green_candle로 대체
      if group_buy_count >= 5:
        # 20일선 돌파 & 양봉
        sell_signal = (close_np[i] > ma20_np[i]) and (is_green_np[i])
      else:
        # 10일선 돌파 & 양봉
        sell_signal = (close_np[i] > ma10_np[i]) and (is_green_np[i])

      if sell_signal:
        exits[i] = True
        # 상태 초기화
        in_position = False
        group_buy_count = 0
        last_buy_price = None
        continue # 매도한 날은 매수하지 않음

    # 2. 매수 로직 확인

    # 원본: buy_condition: (df['RSI'] <= 35) & (~df['Bullish']) & (df['Change_Rate'] < 0)

    # 매수 조건 A: RSI 조건 (RSI < 30 또는 35)
    current_rsi_threshold = 30 if group_buy_count == 1 else DEFAULT_RSI_THRESHOLD
    cond_rsi = rsi_np[i] <= current_rsi_threshold

    # 매수 조건 B: ~Bullish (음봉) & 당일 하락 (Change < 0)
    cond_candle = (~is_green_np[i]) and (change_np[i] < 0)

    should_buy = cond_rsi and cond_candle

    # 매수 조건 C: 가격 피라미딩 (첫 매수가 아니면, 이전 매수가보다 낮아야 함)
    if should_buy and group_buy_count > 0:
      if last_buy_price is not None and close_np[i] >= last_buy_price:
        should_buy = False

    if should_buy:
      entries[i] = True

      # 사이즈(Weight) 계산
      pos_size = 1
      if rsi_np[i] <= 20:
        pos_size = 3
      elif rsi_np[i] <= 30:
        pos_size = 2

      if change_np[i] < -5:
        pos_size += 1

      sizes[i] = pos_size

      # 상태 업데이트
      in_position = True
      group_buy_count += 1
      last_buy_price = close_np[i]

  return entries, exits, sizes

def run_backtest(data, ticker, name):

  close = data['Close']

  # 지표 계산
  rsi, ma10, ma20, change_rate, is_green_candle = get_indicators(data)

  # 신호 생성 (Custom Loop)
  entries, exits, sizes = generate_signals(close, rsi, ma10, ma20, change_rate, is_green_candle)

  # vectorbt 포트폴리오 실행
  pf = vbt.Portfolio.from_signals(
      close,
      entries,
      exits,
      size=sizes,
      size_type='Amount',
      accumulate=True,
      upon_long_exit='close',
      init_cash='auto',
      freq='1D',
      fees=0.001
  )

  # --- 결과 집계 및 CSV 출력 ---
  os.makedirs(OUTPUT_DIR, exist_ok=True)

  # 백테스트 결과 DataFrame 생성 (기존 코드와 유사하게 매매 시점 정보 포함)
  # vbt.trades를 사용하여 매매 정보를 추출하고 원본 코드와 유사하게 포맷합니다.
  trades_df = pf.trades.records_long.copy()

  # 매매가 없는 경우 빈 데이터프레임 저장 후 종료
  if trades_df.empty:
    empty_df = pd.DataFrame(columns=['Buy Date', 'Sell Date', 'Buy Price', 'Sell Price', 'Return (%)', 'Holding Period (Days)', 'Size'])
    empty_df.to_csv(os.path.join(OUTPUT_DIR, f'{ticker}_backtest_results.csv'), index=False)
    return pf, 0, 0, 0

  # Entry/Exit 인덱스를 날짜로 변환
  trades_df['Buy Date'] = close.index[trades_df['entry_idx']]
  trades_df['Sell Date'] = close.index[trades_df['exit_idx']]

  # 가격 및 수익률
  trades_df['Buy Price'] = trades_df['entry_price']
  trades_df['Sell Price'] = trades_df['exit_price']
  trades_df['Return (%)'] = trades_df['pnl_perc']
  trades_df['Size'] = trades_df['size']
  trades_df['Holding Period (Days)'] = (trades_df['exit_date'] - trades_df['entry_date']).dt.days

  # 필요한 컬럼만 선택하여 저장
  output_df = trades_df[['Buy Date', 'Sell Date', 'Buy Price', 'Sell Price', 'Return (%)', 'Holding Period (Days)', 'Size']]
  output_df.to_csv(os.path.join(OUTPUT_DIR, f'{ticker}_backtest_results.csv'), index=False)

  # 최종 지표 계산
  avg_return = output_df['Return (%)'].mean()
  avg_holding_period = output_df['Holding Period (Days)'].mean()
  buy_count = len(output_df) # 총 매수(체결) 횟수

  return pf, avg_return, avg_holding_period, buy_count


if __name__ == "__main__":
  try:
    with open('config-woo3.json', 'r') as config_file:
      config = json.load(config_file)
    tickers = config["global"]["tickers"]
  except FileNotFoundError:
    tickers = {"SPY": "S&P 500", "QQQ": "Nasdaq 100"}
    print("Config file not found. Using default tickers.")

  end_date = datetime.today()
  start_date = end_date - timedelta(days=30 * 365)

  results = {}

  print(f"Backtest Results (Using vectorbt, Results saved to '{OUTPUT_DIR}'):")
  print(f"{'Ticker':<10} | {'Name':<15} | {'Avg. Return':<13} | {'Avg. Hold Days':<14} | {'Buy Count':<10}")
  print("-" * 75)

  for ticker, name in tickers.items():
    print(f"Processing {ticker} ({name})...")
    data = fdr.DataReader(ticker, start=start_date, end=end_date)

    if data.empty:
      print(f"No data found for {ticker}, skipping.")
      continue

    pf, avg_return, avg_holding_period, buy_count = run_backtest(data, ticker, name)

    results[name] = {
      "Average Return": avg_return,
      "Average Holding Period": avg_holding_period,
      "Buy Count": buy_count
    }

    print(f"{ticker:<10} | {name:<15} | {avg_return:>12.2f}% | {avg_holding_period:>13.1f} | {buy_count:>10}")

  print("\nBacktest Summary:")
  for name, metrics in results.items():
    print(f"{name}: Average Return: {metrics['Average Return']:.2f}%, Average Holding Period: {metrics['Average Holding Period']:.2f} days, Buy Count: {metrics['Buy Count']}")