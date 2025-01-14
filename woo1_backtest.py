from datetime import timedelta

import FinanceDataReader as fdr
import pandas as pd
import time

PARTIAL_TARGET_RETURN = 1.08
FULL_TARTET_RETURN = 1.10

# 1. 코스피 및 코스닥 전체 종목 리스트 가져오기
kospi = fdr.StockListing('KOSPI')
kospi = kospi.tail(-100)
kosdaq = fdr.StockListing('KOSDAQ')
# delisting = fdr.StockListing('KRX-DELISTING') # 3천+ 종목 - 상장폐지 종목 전체
admin = fdr.StockListing('KRX-ADMIN') # 50+ 종목 - KRX 관리종목

# 2. 보통주 필터링 (ETN, ETF, 리츠, 선박펀드 제외)
def filter_common_stocks(df):
  return df[
    (~df['Name'].str.contains('ETN|ETF|리츠|선박펀드', na=False)) # ETN, ETF, 리츠, 선박펀드 제외
    & (~df['Name'].str.contains('우|2우|3우|우B|우C', na=False)) # 우선주 제외
    & (~df['Name'].str.contains('스팩', na=False))              # 스팩 제외
    # & (df['Name'].str.contains('금호석유', na=False))              # 테스트
    # & (df['Marcap'] >= 500 * 1e8)                              # 시가총액 500억 이상
    # & (df['Marcap'] < 10 * 1e12)                             # 시가총액 10조 미만
    ]

kospi = filter_common_stocks(kospi)
kosdaq = filter_common_stocks(kosdaq)
# delisting = filter_common_stocks(delisting)
# admin = filter_common_stocks(admin)

# 3. 코스피/코스닥 종목 병합
all_stocks = pd.concat([kospi, kosdaq], ignore_index=True)

# 기술 지표 계산 함수
def calculate_indicators(df):
  df['MA5'] = df['Close'].rolling(window=5).mean()
  df['MA10'] = df['Close'].rolling(window=10).mean()
  df['MA20'] = df['Close'].rolling(window=20).mean()
  df['MA60'] = df['Close'].rolling(window=60).mean()
  df['Bullish'] = df['Close'] > df['Open']
  df['Volume_Change'] = df['Volume'] / df['Volume'].shift(1)
  df['Pre_Change'] = df['Change'].shift(1)
  df['Pre_Bullish'] = df['Close'].shift(1) > df['Open'].shift(1)
  df['Pre_Volume_Change'] = df['Volume'].shift(1) / df['Volume'].shift(2)
  df['High_Change'] = (df['High'] / df['Close'].shift(1) - 1) * 100
  df['Crossover'] = (df['MA5'] > df['MA20']) & (df['MA5'].shift(1) <= df['MA20'].shift(1))
  df['Crossover_Count'] = df['Crossover'].rolling(window=30, min_periods=1).sum()
  df['52WeekLow'] = df['Low'].rolling(window=364, min_periods=1).min()
  df['MA10_Trend'] = df['MA10'].diff().rolling(window=10).apply(lambda x: (x < 0).sum(), raw=True)
  df['MA20_Trend'] = df['MA20'].diff().rolling(window=20).apply(lambda x: (x < 0).sum(), raw=True)
  return df

# 매수 조건 정의 함수
def buy_condition(df):
  # 각 조건 정의
  condition1 = df['Close'] <= df['52WeekLow'] * 1.3
  condition2 = df['Change'] >= 0
  condition3 = df['High_Change'] >= 8
  condition4 = df['Bullish']
  condition5 = df['Volume_Change'] > 3 # 300% 초과
  condition6 = df['Volume_Change'] < 1000 # 100,000% 미만
  condition7 = df['Crossover_Count'] >= 2
  condition8 = df['MA10_Trend'] < 10
  condition9 = df['MA20_Trend'] > 0
  condition10 = ~((df['Pre_Volume_Change'] > 3) & (df['Pre_Change'] > 0)) # 전봉 거래량 300% 초과 + 등락률 0% 초과 제외
  condition11 = df['Close'] >= df['MA20']

  # 모든 조건 결합
  return (
      condition1
      & condition2
      & condition3
      & condition4
      & condition5
      # & condition6
      & condition7
      # & condition8
      # & condition9
      & condition10
      & condition11
  )

# 매도 조건 함수들
def sell_condition_partial(df):
  return df['High'] >= df['Buy'] * PARTIAL_TARGET_RETURN

def sell_condition_full(df):
  return df['High'] >= df['Buy'] * FULL_TARTET_RETURN

def sell_condition_stop_loss(df):
  return df['Close'] < df['MA20']

# 조건에 맞는 종목 필터링 함수
def get_filtered_stocks(all_stocks, start_date, end_date):
  result_data = pd.DataFrame()

  # all_stocks = all_stocks[all_stocks['DelistingDate'].dt.year > 2004]
  print(len(all_stocks))

  for _, row in all_stocks.iterrows():
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
      df = calculate_indicators(df)

      # 매수 조건에 해당하는 데이터 필터링
      buys = df[buy_condition(df)]
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

        # result_data에 병합
        result_data = pd.concat([result_data, buys], ignore_index=True)
    except Exception as e:
      print(f"Error processing {name}, {buy_date}: {e}")

  result_data.to_csv('filtered_stocks.csv', index=False, encoding='utf-8-sig')

  return result_data

# 5. 필터링 수행
start_time = time.time()
start_date = "2020-01-01"
end_date = "2025-01-17"
filtered_stocks = get_filtered_stocks(all_stocks, start_date, end_date)
end_time = time.time()

# 6. 총 소요시간 출력
elapsed_time = end_time - start_time
print(f"총 소요시간: {elapsed_time:.2f}초")
