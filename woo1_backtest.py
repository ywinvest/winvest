import concurrent.futures
import time
from datetime import timedelta
from functools import partial

import FinanceDataReader as fdr
import pandas as pd

import woo1

PARTIAL_TARGET_RETURN = 1.08
FULL_TARTET_RETURN = 1.10

# 매도 조건 함수들
def sell_condition_partial(df):
  return df['High'] >= df['Buy'] * PARTIAL_TARGET_RETURN

def sell_condition_full(df):
  return df['High'] >= df['Buy'] * FULL_TARTET_RETURN

def sell_condition_stop_loss(df):
  return df['Close'] < df['MA20']

def parallel_process_stocks(all_stocks):
  process_func = partial(process_stock)
  results = []

  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(process_func, row) for _, row in all_stocks.iterrows()]
    for future in concurrent.futures.as_completed(futures):
      result = future.result()
      if result is not None:
        results.append(result)

  return pd.concat(results) if results else pd.DataFrame()

def process_stock(row):
  ticker = None
  if hasattr(row, 'Code'):
    ticker = row['Code']
  elif hasattr(row, 'Symbol'):
    ticker = row['Symbol']
  name = row['Name']
  marcap = None
  if hasattr(row, 'Marcap'):
    marcap = row['Marcap']
  try:
    # 종목 데이터 가져오기
    df = fdr.DataReader(ticker, "2004")
    df = woo1.calculate_indicators(df)

    # 매수 조건에 해당하는 데이터 필터링
    buys = df[woo1.buy_condition(df)]
    buys = buys[~buys.index.year.isin([2004])]  # 2020년 데이터 제외

    if not buys.empty:
      for buy_date in buys.index:
        df['Buy'] = buys.loc[buy_date, 'Close']
        subsequent_data = df.loc[buy_date + timedelta(days=1):]

        buy_price = df.loc[buy_date, 'Buy']

        partial_sell_date = None
        full_sell_date = None
        partial_sell_price = None
        full_sell_price = None

        if not subsequent_data.empty:
          # 매수 다음 거래일 조건 확인
          next_day = subsequent_data.iloc[0]
          next_date = next_day.name

          # 시가가 10% 이상 형성되면 시가에 부분매도 및 전량매도
          if next_day['Open'] >= buy_price * FULL_TARTET_RETURN:
            partial_sell_date = next_date
            partial_sell_price = next_day['Open']
            full_sell_date = next_date
            full_sell_price = next_day['Open']
          # 시가가 5% 이상 형성되면 시가에 부분매도
          elif next_day['Open'] >= buy_price * PARTIAL_TARGET_RETURN:
            partial_sell_date = next_date
            partial_sell_price = next_day['Open']

          # 시가에 부분매도만 성공 시
          if partial_sell_date and not full_sell_date:
            # 고가가 10% 이상이면 10%에 전량매도
            if next_day['High'] >= buy_price * FULL_TARTET_RETURN:
              full_sell_date = next_date
              full_sell_price = buy_price * FULL_TARTET_RETURN

          # 시가에 매도 실패 시
          if not partial_sell_date and not full_sell_date:
            # 고가가 10% 이상이면 5%에 부분매도 및 10%에 전량매도
            if next_day['High'] >= buy_price * FULL_TARTET_RETURN:
              partial_sell_date = next_date
              partial_sell_price = buy_price * PARTIAL_TARGET_RETURN
              full_sell_date = next_date
              full_sell_price = buy_price * FULL_TARTET_RETURN
            # 고가가 5% 이상이면 5%에 부분매도
            elif next_day['High'] >= buy_price * PARTIAL_TARGET_RETURN:
              partial_sell_date = next_date
              partial_sell_price = buy_price * PARTIAL_TARGET_RETURN

          # 다음 거래일에 부분매도만 성공 시
          if partial_sell_date and not full_sell_date:
            remaining_data = subsequent_data.loc[next_date + timedelta(days=1):]

            # 두 조건의 발생일을 계산
            long_bullish = remaining_data[(remaining_data['Close'] / remaining_data['Open'] - 1) >= 0.10]
            stop_loss = remaining_data[sell_condition_stop_loss(remaining_data)]

            # 먼저 발생하는 조건 처리
            if not long_bullish.empty and not stop_loss.empty:
              if long_bullish.index[0] < stop_loss.index[0]:  # 장대양봉 먼저 발생
                full_sell_date = long_bullish.index[0]
                full_sell_price = remaining_data.loc[full_sell_date, 'Close']
              else:  # 20일선 이탈 먼저 발생
                full_sell_date = stop_loss.index[0]
                full_sell_price = remaining_data.loc[full_sell_date, 'Close']
            elif not long_bullish.empty:  # 장대양봉만 발생
              full_sell_date = long_bullish.index[0]
              full_sell_price = remaining_data.loc[full_sell_date, 'Close']
            elif not stop_loss.empty:  # 20일선 이탈만 발생
              full_sell_date = stop_loss.index[0]
              full_sell_price = remaining_data.loc[full_sell_date, 'Close']
            else:
              print(f"{name} no sell. {buy_date}, {buy_price}")
          # 다음 거래일에 매도 실패 시
          elif not partial_sell_date and not full_sell_date:
            remaining_data = subsequent_data.loc[next_date + timedelta(days=1):]

            # 각 조건이 처음 발생하는 날짜 찾기
            target_open_sell = remaining_data[remaining_data['Open'] >= buy_price * PARTIAL_TARGET_RETURN]
            target_high_sell = remaining_data[(remaining_data['Open'] < buy_price * PARTIAL_TARGET_RETURN) & (remaining_data['High'] >= buy_price * PARTIAL_TARGET_RETURN)]
            stop_loss = remaining_data[(remaining_data['Close'] < df.loc[buy_date, 'Open']) & (remaining_data['Close'] < remaining_data['MA20'])]

            # 각 조건의 첫 발생일 저장 (발생하지 않으면 None)
            open_sell_date = target_open_sell.index[0] if not target_open_sell.empty else None
            high_sell_date = target_high_sell.index[0] if not target_high_sell.empty else None
            stop_loss_date = stop_loss.index[0] if not stop_loss.empty else None

            # 발생한 날짜들 중 가장 빠른 날짜와 해당 조건 찾기
            valid_dates = [(d, 'open') for d in [open_sell_date] if d is not None] + \
                          [(d, 'high') for d in [high_sell_date] if d is not None] + \
                          [(d, 'stop') for d in [stop_loss_date] if d is not None]

            if valid_dates:
              earliest_date, condition = min(valid_dates, key=lambda x: x[0])

              if condition == 'open':
                # 시가 5% 이상 시 시가에 부분매도
                partial_sell_date = earliest_date
                partial_sell_price = remaining_data.loc[earliest_date, 'Open']
              elif condition == 'high':
                # 고가 5% 이상 시 5%에 부분매도
                partial_sell_date = earliest_date
                partial_sell_price = buy_price * PARTIAL_TARGET_RETURN
              else:  # condition == 'stop'
                # 손절 시 종가에 전량 매도
                partial_sell_date = earliest_date
                partial_sell_price = remaining_data.loc[earliest_date, 'Close']
                full_sell_date = earliest_date
                full_sell_price = remaining_data.loc[earliest_date, 'Close']
            else:
              print(f"{name} no sell condition met. {buy_date}, {buy_price}")

            # 2.3 부분매도 후 장대양봉 확인과 20일선 이탈 조건 중 먼저 발생하는 조건 처리
            if partial_sell_date and not full_sell_date:
              subsequent_after_partial = remaining_data.loc[partial_sell_date + timedelta(days=1):]

              # 두 조건의 발생일 계산
              strong_bullish = subsequent_after_partial[
                (subsequent_after_partial['Close'] / subsequent_after_partial['Open'] - 1) >= 0.10
                ]
              stop_loss = subsequent_after_partial[
                sell_condition_stop_loss(subsequent_after_partial)
              ]

              # 먼저 발생하는 조건 처리
              if not strong_bullish.empty and not stop_loss.empty:
                if strong_bullish.index[0] < stop_loss.index[0]:  # 장대양봉 먼저 발생
                  full_sell_date = strong_bullish.index[0]
                  full_sell_price = subsequent_after_partial.loc[full_sell_date, 'Close']
                else:  # 20일선 이탈 먼저 발생
                  full_sell_date = stop_loss.index[0]
                  full_sell_price = subsequent_after_partial.loc[full_sell_date, 'Close']
              elif not strong_bullish.empty:  # 장대양봉만 발생
                full_sell_date = strong_bullish.index[0]
                full_sell_price = subsequent_after_partial.loc[full_sell_date, 'Close']
              elif not stop_loss.empty:  # 20일선 이탈만 발생
                full_sell_date = stop_loss.index[0]
                full_sell_price = subsequent_after_partial.loc[full_sell_date, 'Close']
              # 여기까지 오면 문제있는 로직
              else:
                print(f"{name} no sell. {buy_date}, {buy_price}")
          # else:
          #   print(f"{name} full sell complete. {buy_date}, {buy_price}")
        else:
          print(f"{name} buy in {buy_date}")
        # 매도 정보를 해당 행에 추가
        buys.loc[buy_date, 'Ticker'] = ticker
        buys.loc[buy_date, 'Name'] = name
        buys.loc[buy_date, 'Marcap'] = marcap
        buys.loc[buy_date, 'Buy_Date'] = buy_date
        buys.loc[buy_date, 'Buy_Price'] = buy_price
        buys.loc[buy_date, 'Partial_Sell_Date'] = partial_sell_date
        buys.loc[buy_date, 'Partial_Sell_Price'] = partial_sell_price
        buys.loc[buy_date, 'Full_Sell_Date'] = full_sell_date
        buys.loc[buy_date, 'Full_Sell_Price'] = full_sell_price

        # 보유기간 계산 (영업일 기준)
        if partial_sell_date:
          buys.loc[buy_date, 'Partial_Holding_Days'] = len(pd.bdate_range(buy_date, partial_sell_date))
          # 부분매도 수익률 계산 (%)
          buys.loc[buy_date, 'Partial_Return'] = ((partial_sell_price / buy_price) - 1)
        else:
          buys.loc[buy_date, 'Partial_Holding_Days'] = None
          buys.loc[buy_date, 'Partial_Return'] = None

        if full_sell_date:
          buys.loc[buy_date, 'Full_Holding_Days'] = len(pd.bdate_range(buy_date, full_sell_date))
          # 전량매도 수익률 계산 (%)
          buys.loc[buy_date, 'Full_Return'] = ((full_sell_price / buy_price) - 1)
        else:
          buys.loc[buy_date, 'Full_Holding_Days'] = None
          buys.loc[buy_date, 'Full_Return'] = None
      return buys
    return None
  except Exception as e:
    print(f"Error processing {ticker}: {e}")
    return None


if __name__ == "__main__":
  start_time = time.time()
  try:
    # delisting = fdr.StockListing('KRX-DELISTING') # 3천+ 종목 - 상장폐지 종목 전체
    # admin = fdr.StockListing('KRX-ADMIN') # 50+ 종목 - KRX 관리종목

    # 종목 리스트 가져오기 및 필터링
    all_stocks = pd.concat([
      woo1.filter_common_stocks(fdr.StockListing('KOSPI').tail(-100)),
      woo1.filter_common_stocks(fdr.StockListing('KOSDAQ'))
    ], ignore_index=True)

    # 병렬 처리로 데이터 분석
    result_data = parallel_process_stocks(all_stocks)
    result_data.to_csv('filtered_stocks.csv', index=False, encoding='utf-8-sig')
  except Exception as e:
    print(f"Error in main execution: {e}")

  finally:
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"총 소요시간: {elapsed_time:.2f}초")
