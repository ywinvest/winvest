import concurrent.futures
import os
import time
from datetime import datetime
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv

from slack_utils import SlackMessageBuilder, send_slack_message


def calculate_indicators(df):
  # df['MA5'] = df['Close'].rolling(window=5).mean()
  # df['MA10'] = df['Close'].rolling(window=10).mean()
  df['MA20'] = df['Close'].rolling(window=20).mean()
  df['MA60'] = df['Close'].rolling(window=60).mean()
  df['MA120'] = df['Close'].rolling(window=120).mean()
  df['MA240'] = df['Close'].rolling(window=240).mean()
  df['MA20_Cross'] = (df['Close'].gt(df['MA20'], axis=0)) & (df['Close'].shift(1).le(df['MA20'].shift(1), axis=0))
  df['MA20_Break'] = (df['Close'].lt(df['MA20'], axis=0)) & (df['Close'].shift(1).ge(df['MA20'].shift(1), axis=0))
  df['Bullish'] = df['Close'] > df['Open']
  df['Volume_Change'] = df['Volume'] / df['Volume'].shift(1) - 1
  # df['High_Change'] = (df['High'] / df['Close'].shift(1) - 1) * 100
  # df['Pre_Change'] = df['Change'].shift(1)
  # # df['Pre_Bullish'] = df['Close'].shift(1) > df['Open'].shift(1)
  # df['Pre_High_Change'] = df['High_Change'].shift(1)
  # df['Pre_Volume_Change'] = df['Volume'].shift(1) / df['Volume'].shift(2)
  # df['Crossover'] = (df['MA5'] > df['MA20']) & (df['MA5'].shift(1) <= df['MA20'].shift(1))
  # df['Crossover_Count'] = df['Crossover'].rolling(window=30, min_periods=1).sum()
  df['Pre39WeekHigh'] = df['High'].shift(1).rolling(window='273D', min_periods=1).max()

  df['Pre52WeekHigh'] = df['High'].shift(1).rolling(window='364D', min_periods=1).max()

  # 39주 신고가 돌파 여부
  is_39weekhigh_break = df['Close'] > df['Pre39WeekHigh']
  # 52주 신고가 돌파 여부
  is_52weekhigh_break = df['Close'] > df['Pre52WeekHigh']

  # 연속적인 신고가 돌파를 그룹화하여 첫 돌파만 선택
  # 돌파가 시작되는 지점을 그룹화 기준으로 사용
  # breaks = (~is_52weekhigh_break).cumsum()  # 돌파가 끊기는 지점으로 그룹화
  # is_first_break = is_52weekhigh_break & (~is_52weekhigh_break.shift(1).fillna(False))
  # df['First_52WeekHigh_Break'] = is_first_break.groupby(breaks).cumsum() == 1
  # df['First_52WeekHigh_Break'] = df['First_52WeekHigh_Break'].where(is_52weekhigh_break, False)
  # 39주 신고가 첫 돌파여부
  df['First_39WeekHigh_Break'] = is_39weekhigh_break & (~is_39weekhigh_break.shift(1, fill_value=False))
  # 52주 신고가 첫 돌파여부
  df['First_52WeekHigh_Break'] = is_52weekhigh_break & (~is_52weekhigh_break.shift(1, fill_value=False))
  # 첫 돌파 이후 10일 동안 추가 돌파 무시
  # df['First_52WeekHigh_Break'] = df['First_52WeekHigh_Break'].where(
  #     ~df['First_52WeekHigh_Break'].rolling(window=10, min_periods=1).sum().shift(1).fillna(0).astype(bool),
  #     False
  # )

  # 이동평균선 추세 상승 여부 (기울기 > 0)
  # df['MA20_Uptrend'] = df['MA20'] > df['MA20'].shift(1)
  # df['MA60_Uptrend'] = df['MA60'] > df['MA60'].shift(1)
  # df['MA120_Uptrend'] = df['MA120'] > df['MA120'].shift(1)
  df['MA20_Slope'] = df['MA20'].pct_change(fill_method=None)
  df['MA60_Slope'] = df['MA60'].pct_change(fill_method=None)
  df['MA120_Slope'] = df['MA120'].pct_change(fill_method=None)
  df['MA240_Slope'] = df['MA240'].pct_change(fill_method=None)

  # 벡터화된 연속 상승 일수 계산
  def calculate_uptrend_days_vec(uptrend_series):
    """벡터화 방식으로 연속 상승 일수를 계산"""
    # 상승 추세가 끊기는 지점을 그룹화 기준으로 사용
    breaks = (~uptrend_series).cumsum()
    # 각 그룹 내에서 연속된 True의 개수 계산
    uptrend_days = uptrend_series.groupby(breaks).cumsum()
    # 상승 추세가 아닌 경우(False)는 0으로 설정
    uptrend_days = uptrend_days.where(uptrend_series, 0)
    return uptrend_days

  # 각 MA에 대해 추세 상승 유지 일수 추가
  df['MA20_Uptrend_Days'] = calculate_uptrend_days_vec(df['MA20_Slope'] > 0)
  df['MA60_Uptrend_Days'] = calculate_uptrend_days_vec(df['MA60_Slope'] > 0)
  df['MA120_Uptrend_Days'] = calculate_uptrend_days_vec(df['MA120_Slope'] > 0)
  df['MA240_Uptrend_Days'] = calculate_uptrend_days_vec(df['MA240_Slope'] > 0)

  df['MA20_Gap'] = df['Close'] / df['MA20'] - 1

  first_day_close = df['Close'].iloc[0]
  for period_days in [21, 63, 126, 252]:
    period_str = f"{period_days // 21}M"
    return_col = f'Return_{period_str}'
    base_price = df['Close'].shift(period_days)
    base_price.fillna(first_day_close, inplace=True)
    df[return_col] = df['Close'] / base_price - 1

  df['Weighted_Return'] = (df['Return_1M'] * 0.4 +
                           df['Return_3M'] * 0.3 +
                           df['Return_6M'] * 0.2 +
                           df['Return_12M'] * 0.1)
  return df


def calculate_relative_strength(df):
  grouped = df.groupby([df.index])
  for period in ["1M", "3M", "6M", "12M"]:
    return_col = f'Return_{period}'
    rs_col = f'RS_{period}'

    df[rs_col] = grouped[return_col].rank(pct=True) * 98 + 1
    df[rs_col] = df[rs_col].fillna(1).astype(int).clip(1, 99)

  df['RS'] = grouped['Weighted_Return'].rank(pct=True) * 98 + 1
  df['RS'] = df['RS'].fillna(1).astype(int).clip(1, 99)

  return df

def calculate_trading_days(df, start_date, end_date):
  """
  실제 거래일 기준으로 보유기간을 계산하는 함수

  Args:
      df (pandas.DataFrame): 주가 데이터
      start_date (datetime): 시작일
      end_date (datetime): 종료일

  Returns:
      int: 실제 거래일 수
  """
  if pd.isna(end_date):
    return None

  # start_date와 end_date 사이의 실제 거래일만 필터링
  trading_days = df.loc[start_date:end_date].index
  return len(trading_days) - 1  # 매수일 제외

def filter_common_stocks(df):
  # 스팩 제외
  exclude_pattern = r'스팩'
  return df[(~df['Name'].str.contains(exclude_pattern, na=False, regex=True))
            & (~df['Code'].str.endswith(("5", "7", "9", "K", "L", "M", "N", "O"))) # 우선주, 일부 ETN/ETF 등 제외
            & (df['Marcap'] >= 200_000_000_000)
            # & (df['Name'].str.contains("나무기술", na=False, regex=True))
            ]

def buy_condition(df):
  # 벡터화된 연산 사용
  conditions = pd.Series(True, index=df.index)
  # conditions &= (df['MA60_Uptrend'])
  # conditions &= (df['MA120_Uptrend'])
  # conditions &= (df['MA20_Cross'])
  # conditions &= (df['Close'] > df['Pre52WeekHigh'])
  kospi_or_kosdaq_global = df['Market'].isin(['KOSPI', 'KOSDAQ GLOBAL'])
  kosdaq = df['Market'] == 'KOSDAQ'

  conditions &= (
      ((kospi_or_kosdaq_global) & df['Pre52WeekHigh'].ne(0) & df['First_52WeekHigh_Break']) |
      ((kosdaq) & df['Pre39WeekHigh'].ne(0) & df['First_39WeekHigh_Break'])
  )
  # conditions &= (df['MA20_Uptrend'] == True)
  # conditions &= (df['MA60_Uptrend'] == True)
  # conditions &= (df['MA120_Uptrend'] == True)
  conditions &= (df['MA20_Slope'] > 0)
  conditions &= (df['MA60_Slope'] > 0)
  conditions &= (df['MA120_Slope'] > 0)
  conditions &= (df['MA240_Slope'] > 0)
  conditions &= (df['Change'] < 0.295)
  conditions &= (df['Volume'] > 0)
  conditions &= (df['Volume'].shift(1) > 0)
  # conditions &= (df['MA120_Uptrend_Days'] < 400) # 120일 상승 추세 장기 연속 제외
  # conditions &= ((df['Close'] - df['Open'])/df['Close'] > -0.05) # 긴 음봉 제외
  # conditions &= (df['MA20_Gap'] < 0.3)
  return conditions

def buy_and_sell(df, kospi_df, kosdaq_df):
  # 매수 신호가 발생한 모든 거래를 가져옵니다.
  buy_signals = df[buy_condition(df)].copy()
  buy_signals = buy_signals[buy_signals.index >= '2015-06-15']

  if buy_signals.empty:
    return pd.DataFrame()

  trades = []
  # 종목별로 순회하며 처리합니다.
  for code, stock_group in df.groupby('Code'):
    # 해당 종목의 매수 신호만 필터링합니다.
    stock_buy_signals = buy_signals[buy_signals['Code'] == code]
    if stock_buy_signals.empty:
      continue

    prev_sell_date = pd.Timestamp.min

    for buy_date, buy_row in stock_buy_signals.iterrows():
      # 이전 거래가 끝나기 전의 신호는 무시합니다.
      if buy_date <= prev_sell_date:
        continue

      # --- RSI 및 시가총액 조건 검사 (수정된 로직) ---
      market = buy_row['Market']
      index_rsi = None
      index_ma60_up = None
      index_adx = None
      index_di = None
      index_distribution_day = None
      index_cum_dist_days = None

      rsi_source_df = None
      if market == 'KOSPI':
        rsi_source_df = kospi_df
      elif market in ['KOSDAQ', 'KOSDAQ GLOBAL']:
        rsi_source_df = kosdaq_df

      if rsi_source_df is not None and buy_date in rsi_source_df.index:
        rsi_val = rsi_source_df.loc[buy_date, 'RSI']
        index_rsi = rsi_val.iloc[0] if isinstance(rsi_val, pd.Series) else rsi_val
        # ma60_up_val = rsi_source_df.loc[buy_date, 'MA60_Up']
        # index_ma60_up = ma60_up_val.iloc[0] if isinstance(ma60_up_val, pd.Series) else ma60_up_val
        adx_val = rsi_source_df.loc[buy_date, 'ADX']
        index_adx = adx_val.iloc[0] if isinstance(adx_val, pd.Series) else adx_val
        di_val = rsi_source_df.loc[buy_date, 'DI']
        index_di = di_val.iloc[0] if isinstance(di_val, pd.Series) else di_val

        distribution_day_val = rsi_source_df.loc[buy_date, 'Distribution_Day']
        index_distribution_day = distribution_day_val.iloc[0] if isinstance(distribution_day_val, pd.Series) else distribution_day_val

        cum_dist_days_val = rsi_source_df.loc[buy_date, 'Cum_Dist_Days']
        index_cum_dist_days = cum_dist_days_val.iloc[0] if isinstance(cum_dist_days_val, pd.Series) else cum_dist_days_val

      # if index_rsi is None or index_rsi > 80 or index_rsi < 30:
      #   continue

      buy_price = buy_row['Close']
      current_price = stock_group['Close'].iloc[-1]
      estimated_marcap = buy_row['Marcap'] * (buy_price / current_price)

      if estimated_marcap < 2e+11:
        continue

      # 매수일 이후의 데이터만 사용합니다.
      trade_data = stock_group.loc[buy_date:].iloc[1:]

      # 매도 조건 초기화
      sell_date, sell_price = None, None
      full_sell_date, full_sell_price = None, None

      if not trade_data.empty:
        # 익절/손절 가격 정의
        take_profit_price = buy_price * 1.3
        stop_loss_price = buy_price * 0.92
        trailing_stop_loss_price = buy_price * 1.1

        # 1차 매도 (분할 익절 또는 전체 손절)
        take_profit_dates = trade_data.index[trade_data['High'] >= take_profit_price]
        stop_loss_dates = trade_data.index[trade_data['Close'] < stop_loss_price]

        first_take_profit_date = take_profit_dates[0] if not take_profit_dates.empty else None
        first_stop_loss_date = stop_loss_dates[0] if not stop_loss_dates.empty else None

        # 어떤 매도 조건이 먼저 충족되었는지 확인
        if first_stop_loss_date and (first_take_profit_date is None or first_stop_loss_date < first_take_profit_date):
          # 손절 조건이 먼저 발생하면 즉시 전체 매도
          sell_date = first_stop_loss_date
          sell_price = trade_data.loc[sell_date, 'Close']
          full_sell_date, full_sell_price = sell_date, sell_price
        elif first_take_profit_date:
          # 익절 조건이 먼저 발생하면 1차 분할 매도
          sell_date = first_take_profit_date
          sell_price = take_profit_price

          # 2차 매도 (남은 물량) 조건 탐색
          after_partial_sell_data = trade_data.loc[sell_date:].iloc[1:]
          if not after_partial_sell_data.empty:
            # 2차 매도 조건: 20일선 하향 돌파 등
            second_sell_cond = (
                (after_partial_sell_data['Close'] < after_partial_sell_data['MA20']) &
                (after_partial_sell_data['MA20_Slope'] < 0) &
                (after_partial_sell_data['MA20_Gap'] < -0.05) &
                (after_partial_sell_data['Bullish'] == False) &
                (after_partial_sell_data['Change'] < -0.02)
            )
            second_stop_loss_cond = (
              (after_partial_sell_data['Close'] < trailing_stop_loss_price)
            )
            second_sell_dates = after_partial_sell_data.index[second_sell_cond]
            second_stop_loss_dates = after_partial_sell_data.index[second_stop_loss_cond]

            final_sell_date = second_sell_dates[0] if not second_sell_dates.empty else None
            final_stop_loss_date = second_stop_loss_dates[0] if not second_stop_loss_dates.empty else None

            if final_stop_loss_date and (final_sell_date is None or final_stop_loss_date < final_sell_date):
              full_sell_date = final_stop_loss_date
              full_sell_price = after_partial_sell_data.loc[full_sell_date, 'Close']
            elif final_sell_date:
              full_sell_date = final_sell_date
              full_sell_price = after_partial_sell_data.loc[full_sell_date, 'Close']

      # 최종 거래 결과 기록
      trade_info = buy_row.to_dict()
      trade_info.update({
        'Buy_Date': buy_date,
        'Buy_Price': buy_price,
        'Estimated_Marcap': estimated_marcap,
        'Index_RSI': index_rsi,
        # 'Index_MA60_Up': index_ma60_up,
        'Index_ADX': index_adx,
        'Index_DI': index_di,
        'Index_Dist_Day': index_distribution_day,
        'Index_Cum_Dist_Days': index_cum_dist_days,
        'Sell_Date': sell_date,
        'Sell_Price': sell_price,
        'Full_Sell_Date': full_sell_date,
        'Full_Sell_Price': full_sell_price,
        'Return': (sell_price / buy_price - 1) if sell_price else (current_price / buy_price - 1),
        'Full_Return': (full_sell_price / buy_price - 1) if full_sell_price else ((current_price / buy_price - 1) if sell_date else None),
        'Holding_Days': calculate_trading_days(stock_group, buy_date, sell_date),
        'Full_Holding_Days': calculate_trading_days(stock_group, buy_date, full_sell_date),
      })
      trades.append(trade_info)

      # 다음 거래가 이 거래의 종료일 이후에 시작되도록 설정
      if full_sell_date:
        prev_sell_date = full_sell_date
      else: # 매도가 일어나지 않았다면 이 종목은 더 이상 거래하지 않음
        prev_sell_date = pd.Timestamp.max

  return pd.DataFrame(trades)

def format_market_cap(marcap):
  """시가총액을 조 또는 억 단위로 포맷팅"""
  if marcap >= 1e12:  # 1조 이상
    return f"{marcap/1e12:.1f}조"
  else:  # 억 단위
    return f"{marcap/1e8:.0f}억"

def truncate_name(name, max_length=10):
  """종목명을 max_length자로 제한하고, 길면 말줄임표 추가"""
  return name[:max_length-1] + '…' if len(name) > max_length else name

def send_to_slack(trades_data, kospi, kosdaq):
  try:
    # 오늘 날짜 가져오기
    today = datetime.today()
    token = os.getenv("SLACK_BOT_TOKEN")
    channel = os.getenv("SLACK_CHANNEL")

    # 오늘 날짜의 매수 신호만 필터링
    today_trades = trades_data[trades_data['Buy_Date'].dt.date == today.date()] if not trades_data.empty else pd.DataFrame()

    builder = SlackMessageBuilder()

    if today_trades.empty:
      builder.add_line("오늘은 매수 후보가 없습니다.")
      send_slack_message(builder.build(), token, channel)
      print("No stocks match the buying conditions today")
      return

    today_trades = today_trades.sort_values(['Market', 'RS'], ascending=[False, False])

    # 시장별 RSI 값 가져오기 (오늘 날짜 기준)
    kospi_rsi = kospi[kospi.index.date == today.date()]['RSI'].iloc[-1] if not kospi[kospi.index.date == today.date()].empty else None
    kosdaq_rsi = kosdaq[kosdaq.index.date == today.date()]['RSI'].iloc[-1] if not kosdaq[kosdaq.index.date == today.date()].empty else None
    kospi_adx = kospi[kospi.index.date == today.date()]['ADX'].iloc[-1] if not kospi[kospi.index.date == today.date()].empty else None
    kosdaq_adx = kosdaq[kosdaq.index.date == today.date()]['ADX'].iloc[-1] if not kosdaq[kosdaq.index.date == today.date()].empty else None
    kospi_di = kospi[kospi.index.date == today.date()]['DI'].iloc[-1] if not kospi[kospi.index.date == today.date()].empty else None
    kosdaq_di = kosdaq[kosdaq.index.date == today.date()]['DI'].iloc[-1] if not kosdaq[kosdaq.index.date == today.date()].empty else None

    builder.add_line(
        f"{today.year}년 {today.month}월 {today.day}일 신고가 돌파 매수 후보",
        bold=True
    )

    for market, group in today_trades.groupby('Market'):
      rsi_emoji = "large_green_circle" if (50 <= (
        kospi_rsi if market == 'KOSPI' else kosdaq_rsi) <= 80) and (
          (kospi_adx if market == 'KOSPI' else kosdaq_adx) > 25) and (
        kospi_di if market == 'KOSPI' else kosdaq_di) else "red_circle"
      rsi_value = kospi_rsi if market == 'KOSPI' else kosdaq_rsi
      adx_value = kospi_adx if market == 'KOSPI' else kosdaq_adx
      builder.add_line(
          f" {market} (RSI: {rsi_value:.2f}, ADX: {adx_value:.2f})",
          emoji=rsi_emoji,
          bold=True
      )
      for _, row in group.iterrows():
        name = row['Name']
        marcap = row['Marcap']
        ma20_gap = row['MA20_Gap']
        rs = row['RS']
        rs_1m = row['RS_1M']
        rs_3m = row['RS_3M']
        rs_6m = row['RS_6M']

        emoji = "question"
        if ma20_gap < 0.3 and rs_1m >= rs_3m and rs_1m >= rs_6m:
          if 80 <= rs <= 95:
            emoji = "first_place_medal"
          elif (75 <= rs <= 89) or (96 <= rs <= 99):
            emoji = "second_place_medal"

        with builder.line() as line:
          line \
            .emoji(emoji) \
            .text(truncate_name(name, 10), code=True) \
            .space() \
            .text(f"Gap20: {ma20_gap * 100:.1f}%") \
            .text(f", RS: {rs} ({rs_1m},{rs_3m},{rs_6m})") \
            .text(f", {format_market_cap(marcap)}")

    # Slack 메시지 전송
    send_slack_message(builder.build(), token, channel)

  except Exception as e:
    print(f"Error sending Slack message: {e}")

def process_stock(row, two_years_ago):
  try:
    symbol = row['Code']
    name = row['Name']
    marcap = row['Marcap']
    market = row['Market']

    df = fdr.DataReader(symbol, two_years_ago)
    df = calculate_indicators(df)

    if not df.empty:
      df['Code'] = symbol
      df['Name'] = name
      df['Marcap'] = marcap
      df['Market'] = market
      return df
    return None
  except Exception as e:
    print(f"Error processing {symbol}: {e}")
    return None

def parallel_process_stocks(all_stocks, two_years_ago):
  process_func = partial(process_stock, two_years_ago=two_years_ago)
  results = []

  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(process_func, row) for _, row in all_stocks.iterrows()]
    for future in concurrent.futures.as_completed(futures):
      result = future.result()
      if result is not None:
        results.append(result)

  return pd.concat(results) if results else pd.DataFrame()

if __name__ == "__main__":
  start_time = time.time()

  # .env 파일 로드
  load_dotenv()

  try:
    all_stocks = pd.concat([
      fdr.StockListing('KOSPI'),
      fdr.StockListing('KOSDAQ')
    ], ignore_index=True)

    # 날짜 설정
    today = datetime.today()
    two_years_ago = today.year - 2

    kospi = fdr.DataReader('KS11', two_years_ago)
    kospi['RSI'] = ta.rsi(kospi['Close'], length=14)
    adx_data = ta.adx(high=kospi['High'], low=kospi['Low'], close=kospi['Close'], length=14, mamode='EMA')
    kospi['ADX'] = adx_data['ADX_14']
    kospi['DI'] = adx_data['DMP_14'] > adx_data['DMN_14']
    kospi['Volume_Change'] = kospi['Volume'] / kospi['Volume'].shift(1) - 1
    price_threshold = -0.002
    kospi['Distribution_Day'] = (kospi['Change'] <= price_threshold) & (kospi['Volume_Change'] > 0)
    kospi['Cum_Dist_Days'] = kospi['Distribution_Day'].rolling(window=20, min_periods=1).sum()

    kosdaq = fdr.DataReader('KQ11', two_years_ago)
    kosdaq['RSI'] = ta.rsi(kosdaq['Close'], length=14)
    adx_data = ta.adx(high=kosdaq['High'], low=kosdaq['Low'], close=kosdaq['Close'], length=14, mamode='EMA')
    kosdaq['ADX'] = adx_data['ADX_14']
    kosdaq['DI'] = adx_data['DMP_14'] > adx_data['DMN_14']
    kosdaq['Volume_Change'] = kosdaq['Volume'] / kosdaq['Volume'].shift(1) - 1
    kosdaq['Distribution_Day'] = (kosdaq['Change'] <= price_threshold) & (kosdaq['Volume_Change'] > 0)
    kosdaq['Cum_Dist_Days'] = kosdaq['Distribution_Day'].rolling(window=20, min_periods=1).sum()

    # 병렬 처리로 데이터 분석
    result_data = parallel_process_stocks(all_stocks, two_years_ago)
    result_data = calculate_relative_strength(result_data)
    filtered_data = filter_common_stocks(result_data)

    # buy_and_sell 함수를 사용하여 매수 후보 찾기
    trades_data = buy_and_sell(filtered_data, kospi, kosdaq)

    # Slack 메시지 전송 (오늘 날짜 매수 신호만)
    send_to_slack(trades_data, kospi, kosdaq)
  except Exception as e:
    print(f"Error in main execution: {e}")

  finally:
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"총 소요시간: {elapsed_time:.2f}초")
