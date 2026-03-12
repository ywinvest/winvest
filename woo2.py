import concurrent.futures
import os
import time
from datetime import datetime
from functools import partial

import FinanceDataReader as fdr
import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv

import krx_auth
import rs
from slack_utils import SlackMessageBuilder, send_slack_message

BASE_RISK = 0.08  # 8% base risk (R value)
TRADING_FEE = 0.002  # 0.2% trading fee (commission + slippage)

def calculate_indicators(df):
  # df['MA5'] = df['Close'].rolling(window=5).mean()
  # df['MA10'] = df['Close'].rolling(window=10).mean()
  df['MA20'] = df['Close'].rolling(window=20).mean()
  df['MA60'] = df['Close'].rolling(window=60).mean()
  df['MA120'] = df['Close'].rolling(window=120).mean()
  df['MA240'] = df['Close'].rolling(window=240).mean()
  # df['MA20_Cross'] = (df['Close'].gt(df['MA20'], axis=0)) & (df['Close'].shift(1).le(df['MA20'].shift(1), axis=0))
  # df['MA20_Break'] = (df['Close'].lt(df['MA20'], axis=0)) & (df['Close'].shift(1).ge(df['MA20'].shift(1), axis=0))
  df['Bullish'] = df['Close'] > df['Open']
  df['Volume_Change'] = df['Volume'] / df['Volume'].shift(1) - 1
  # df['High_Change'] = (df['High'] / df['Close'].shift(1) - 1) * 100
  # df['Pre_Change'] = df['Change'].shift(1)
  # # df['Pre_Bullish'] = df['Close'].shift(1) > df['Open'].shift(1)
  # df['Pre_High_Change'] = df['High_Change'].shift(1)
  # df['Pre_Volume_Change'] = df['Volume'].shift(1) / df['Volume'].shift(2)
  # df['Crossover'] = (df['MA5'] > df['MA20']) & (df['MA5'].shift(1) <= df['MA20'].shift(1))
  # df['Crossover_Count'] = df['Crossover'].rolling(window=30, min_periods=1).sum()
  # df['Pre39WeekHigh'] = df['High'].shift(1).rolling(window='273D', min_periods=1).max()

  df['Pre52WeekHigh'] = df['High'].shift(1).rolling(window='364D', min_periods=1).max()

  # 39주 신고가 돌파 여부
  # is_39weekhigh_break = df['Close'] > df['Pre39WeekHigh']
  # 52주 신고가 돌파 여부
  is_52weekhigh_break = df['Close'] > df['Pre52WeekHigh']

  # 연속적인 신고가 돌파를 그룹화하여 첫 돌파만 선택
  # 돌파가 시작되는 지점을 그룹화 기준으로 사용
  # breaks = (~is_52weekhigh_break).cumsum()  # 돌파가 끊기는 지점으로 그룹화
  # is_first_break = is_52weekhigh_break & (~is_52weekhigh_break.shift(1).fillna(False))
  # df['First_52WeekHigh_Break'] = is_first_break.groupby(breaks).cumsum() == 1
  # df['First_52WeekHigh_Break'] = df['First_52WeekHigh_Break'].where(is_52weekhigh_break, False)
  # 39주 신고가 첫 돌파여부
  # df['First_39WeekHigh_Break'] = is_39weekhigh_break & (~is_39weekhigh_break.shift(1, fill_value=False))
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

  df['ATR_14'] = ta.atr(high=df['High'], low=df['Low'], close=df['Close'], length=14)

  rs.calculate_indicators(df)
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
  # kospi_or_kosdaq_global = df['Market'].isin(['KOSPI', 'KOSDAQ GLOBAL'])
  # kosdaq = df['Market'] == 'KOSDAQ'

  # conditions &= (
  #     ((kospi_or_kosdaq_global) & df['Pre52WeekHigh'].ne(0) & df['First_52WeekHigh_Break']) |
  #     ((kosdaq) & df['Pre39WeekHigh'].ne(0) & df['First_39WeekHigh_Break'])
  # )
  conditions &= (df['Pre52WeekHigh'].ne(0) & df['First_52WeekHigh_Break'])
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
  conditions &= (df['MA20_Gap'] < 0.35)
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

      market = buy_row['Market']
      buy_index_rsi = None
      buy_index_ma5_up = None
      buy_index_ma20_up = None
      buy_index_ma60_up = None
      buy_index_ma120_up = None
      buy_index_adx = None
      buy_index_di = None

      buy_kospi_ma5_up = None
      buy_kospi_ma20_up = None
      buy_kospi_adx = None
      buy_kospi_di = None

      buy_kosdaq_ma5_up = None
      buy_kosdaq_ma20_up = None
      buy_kosdaq_adx = None
      buy_kosdaq_di = None

      sell_index_ma5_up = None
      sell_index_ma20_up = None
      sell_index_adx = None
      sell_index_di = None

      source_df = None
      if market == 'KOSPI':
        source_df = kospi_df
      elif market in ['KOSDAQ', 'KOSDAQ GLOBAL']:
        source_df = kosdaq_df

      buy_price = buy_row['Close']
      current_price = stock_group['Close'].iloc[-1]
      estimated_marcap = buy_row['Marcap'] * (buy_price / current_price)

      if estimated_marcap < 2e+11:
        continue

      # 매수일 이후의 데이터만 사용합니다.
      trade_data = stock_group.loc[buy_date:].iloc[1:]

      # 매도 조건 초기화
      sell_date, sell_price = None, None
      full_sell_date, full_sell_price, full_sell_reason = None, None, None

      if not trade_data.empty:
        # 익절/손절 가격 정의
        take_profit_price = buy_price * (1 + (BASE_RISK * 3) + TRADING_FEE) # +24.2%
        stop_loss_price = buy_price * (1 - BASE_RISK) # -8%
        default_trailing_stop_loss_price = buy_price * (1 + BASE_RISK + TRADING_FEE) # +8.2%

        # 1차 매도 각 조건이 처음 발생하는 날짜 찾기
        take_profit_open_dates = trade_data[trade_data['Open'] >= take_profit_price]
        take_profit_high_dates = trade_data[(trade_data['Open'] < take_profit_price) & (trade_data['High'] >= take_profit_price)]
        stop_loss_dates = trade_data[trade_data['Close'] < stop_loss_price]

        # 각 조건의 첫 발생일 저장 (발생하지 않으면 None)
        take_profit_open_date = take_profit_open_dates.index[0] if not take_profit_open_dates.empty else None
        take_profit_high_date = take_profit_high_dates.index[0] if not take_profit_high_dates.empty else None
        stop_loss_date = stop_loss_dates.index[0] if not stop_loss_dates.empty else None

        # 발생한 날짜들 중 가장 빠른 날짜와 해당 조건 찾기
        valid_dates = [(d, 'open') for d in [take_profit_open_date] if d is not None] + \
                      [(d, 'high') for d in [take_profit_high_date] if d is not None] + \
                      [(d, 'stop') for d in [stop_loss_date] if d is not None]

        if valid_dates:
          earliest_date, condition = min(valid_dates, key=lambda x: x[0])

          if condition == 'open':
            sell_date = earliest_date
            sell_price = trade_data.loc[earliest_date, 'Open']
          elif condition == 'high':
            sell_date = earliest_date
            sell_price = take_profit_price
          else:  # condition == 'stop'
            sell_date = earliest_date
            sell_price = trade_data.loc[earliest_date, 'Close']
            full_sell_date = earliest_date
            full_sell_price = trade_data.loc[earliest_date, 'Close']
        # else:
        #   print(f"{name} no sell condition met. {buy_date}, {buy_price}")
        if source_df is not None and buy_date in source_df.index:
          buy_index_rsi = source_df.loc[buy_date, 'RSI']
          buy_index_ma5_up = source_df.loc[buy_date, 'MA5_Up']
          buy_index_ma20_up = source_df.loc[buy_date, 'MA20_Up']
          buy_index_ma60_up = source_df.loc[buy_date, 'MA60_Up']
          buy_index_ma120_up = source_df.loc[buy_date, 'MA120_Up']
          buy_index_adx = source_df.loc[buy_date, 'ADX']
          buy_index_di = source_df.loc[buy_date, 'DI']

          buy_kospi_ma5_up = kospi_df.loc[buy_date, 'MA5_Up']
          buy_kospi_ma20_up = kospi_df.loc[buy_date, 'MA20_Up']
          buy_kospi_adx = kospi_df.loc[buy_date, 'ADX']
          buy_kospi_di = kospi_df.loc[buy_date, 'DI']

          buy_kosdaq_ma5_up = kosdaq_df.loc[buy_date, 'MA5_Up']
          buy_kosdaq_ma20_up = kosdaq_df.loc[buy_date, 'MA20_Up']
          buy_kosdaq_adx = kosdaq_df.loc[buy_date, 'ADX']
          buy_kosdaq_di = kosdaq_df.loc[buy_date, 'DI']

        if source_df is not None and sell_date in source_df.index:
          ma5_up_val = source_df.loc[sell_date, 'MA5_Up']
          sell_index_ma5_up = ma5_up_val.iloc[0] if isinstance(ma5_up_val, pd.Series) else ma5_up_val
          ma20_up_val = source_df.loc[sell_date, 'MA20_Up']
          sell_index_ma20_up = ma20_up_val.iloc[0] if isinstance(ma20_up_val, pd.Series) else ma20_up_val
          adx_val = source_df.loc[sell_date, 'ADX']
          sell_index_adx = adx_val.iloc[0] if isinstance(adx_val, pd.Series) else adx_val
          di_val = source_df.loc[sell_date, 'DI']
          sell_index_di = di_val.iloc[0] if isinstance(di_val, pd.Series) else di_val

        if sell_date and not full_sell_date:
          is_market_weak = not sell_index_ma5_up
          trailing_stop_loss_price = buy_price * (1 + (BASE_RISK * 2) + TRADING_FEE) if is_market_weak else default_trailing_stop_loss_price # +16.2%

          # 2차 매도 (남은 물량) 조건 탐색
          after_partial_sell_data = trade_data.loc[sell_date:].iloc[1:]
          if not after_partial_sell_data.empty:
            # # 1. 거래량 실린 장대 음봉 (오닐식 청산)
            # volume_spike_drop = (
            #     (
            #         (after_partial_sell_data['Volume'] > after_partial_sell_data['Volume'].shift(1) * 1.2) |
            #         (after_partial_sell_data['Volume'] > after_partial_sell_data['Volume'].rolling(window=20).mean() * 1.5)
            #     ) &
            #     (after_partial_sell_data['Change'] < -1 * BASE_RISK) & # -8%
            #     (after_partial_sell_data['Close'] / after_partial_sell_data['Open'] - 1 < -1 * BASE_RISK) # -8%
            # )
            # 1. 당일 고점 대비 ATR 14의 3배 하락 종가 이탈 (오닐식 클라이맥스 청산)
            volume_spike_drop = (
                after_partial_sell_data['Close'] < (after_partial_sell_data['High'] - after_partial_sell_data['ATR_14'] * 3)
            )

            # 2. 추세 붕괴 확정
            trend_breakdown_confirm = (
                (after_partial_sell_data['Close'] < after_partial_sell_data['MA20']) &
                (after_partial_sell_data['MA20_Slope'] < 0) &
                (after_partial_sell_data['MA20_Gap'] < -0.05) &
                (after_partial_sell_data['Change'] < -0.01)
            )

            # second_sell_cond = volume_spike_drop | trend_breakdown_confirm
            # second_stop_loss_cond = (
            #   (after_partial_sell_data['Close'] < trailing_stop_loss_price)
            # )
            volume_spike_drop_sell_dates = after_partial_sell_data[volume_spike_drop]
            trend_breakdown_confirm_sell_dates = after_partial_sell_data[trend_breakdown_confirm]
            trailing_stop_sell_dates = after_partial_sell_data[after_partial_sell_data['Close'] < trailing_stop_loss_price]

            volume_spike_drop_sell_date = volume_spike_drop_sell_dates.index[0] if not volume_spike_drop_sell_dates.empty else None
            trend_breakdown_confirm_sell_date = trend_breakdown_confirm_sell_dates.index[0] if not trend_breakdown_confirm_sell_dates.empty else None
            trailing_stop_sell_date = trailing_stop_sell_dates.index[0] if not trailing_stop_sell_dates.empty else None

            # second_sell_dates = after_partial_sell_data.index[second_sell_cond]
            # second_stop_loss_dates = after_partial_sell_data.index[second_stop_loss_cond]
            #
            # final_sell_date = second_sell_dates[0] if not second_sell_dates.empty else None
            # final_stop_loss_date = second_stop_loss_dates[0] if not second_stop_loss_dates.empty else None

            # 발생한 날짜들 중 가장 빠른 날짜와 해당 조건 찾기
            valid_dates = [(d, 'volume') for d in [volume_spike_drop_sell_date] if d is not None] + \
                          [(d, 'trend_break') for d in [trend_breakdown_confirm_sell_date] if d is not None] + \
                          [(d, 'trailing') for d in [trailing_stop_sell_date] if d is not None]

            if valid_dates:
              earliest_date, condition = min(valid_dates, key=lambda x: x[0])

              if condition == 'trailing':
                full_sell_date = earliest_date
                full_sell_price = after_partial_sell_data.loc[earliest_date, 'Close']
                full_sell_reason = 'trailing stop'
              elif condition == 'volume':
                full_sell_date = earliest_date
                full_sell_price = after_partial_sell_data.loc[earliest_date, 'Close']
                full_sell_reason = 'volume spike drop'
              elif condition == 'trend_break':
                full_sell_date = earliest_date
                full_sell_price = after_partial_sell_data.loc[earliest_date, 'Close']
                full_sell_reason = 'trend breakdown'

            # if final_stop_loss_date and (final_sell_date is None or final_stop_loss_date < final_sell_date):
            #   full_sell_date = final_stop_loss_date
            #   full_sell_price = after_partial_sell_data.loc[full_sell_date, 'Close']
            # elif final_sell_date:
            #   full_sell_date = final_sell_date
            #   full_sell_price = after_partial_sell_data.loc[full_sell_date, 'Close']

      # 최종 거래 결과 기록
      trade_info = buy_row.to_dict()
      trade_info.update({
        'Buy_Date': buy_date,
        'Buy_Price': buy_price,
        'Estimated_Marcap': estimated_marcap,
        'Buy_Kospi_ADX': buy_kospi_adx,
        'Buy_Kosdaq_ADX': buy_kosdaq_adx,
        'Buy_Index_ADX': buy_index_adx,
        'Buy_Index_DI': buy_index_di,
        'Buy_Index_MA5_Up': buy_index_ma5_up,
        'Buy_Index_MA20_Up': buy_index_ma20_up,
        'Buy_Index_MA60_Up': buy_index_ma60_up,
        'Buy_Index_MA120_Up': buy_index_ma120_up,
        'Sell_Date': sell_date,
        'Sell_Price': sell_price,
        'Sell_Index_ADX': sell_index_adx,
        'Sell_Index_DI': sell_index_di,
        'Sell_Index_MA5_Up': sell_index_ma5_up,
        'Sell_Index_MA20_Up': sell_index_ma20_up,
        'Full_Sell_Date': full_sell_date,
        'Full_Sell_Price': full_sell_price,
        'Full_Sell_Reason': full_sell_reason,
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


def find_sell_candidates(trades_data):
  """
  trades_data에서 오늘 날짜에 1차 또는 최종 매도가 발생한 거래를 필터링합니다.
  """
  if trades_data.empty:
    return pd.DataFrame()

  # NaT(결측값)를 제외하고 날짜 비교
  sell_today = pd.to_datetime(trades_data['Sell_Date']).dt.date == today.date()
  full_sell_today = pd.to_datetime(trades_data['Full_Sell_Date']).dt.date == today.date()

  # fillna(False)를 통해 NaT 값으로 인한 오류 방지
  return trades_data[sell_today.fillna(False) | full_sell_today.fillna(False)].copy()


def send_sell_to_slack(sell_data):
  """오늘의 매도 후보 종목을 슬랙으로 전송합니다."""

  token = os.getenv("SLACK_BOT_TOKEN")
  channel = os.getenv("SLACK_CHANNEL")
  builder = SlackMessageBuilder()

  try:
    builder.add_line(
        f"{today.year}년 {today.month}월 {today.day}일 매도 후보",
        bold=True
    )

    if sell_data.empty:
      builder.add_line(f"오늘은 매도 후보가 없습니다.")
      send_slack_message(builder.build(), token, channel)
      print("No stocks to sell today.")
      return

    sell_data['return_val'] = sell_data.apply(
        lambda row: (row['Full_Sell_Price'] / row['Buy_Price'] - 1) * 100
        if pd.notna(row['Full_Sell_Date']) and pd.to_datetime(row['Full_Sell_Date']).date() == today.date()
        else (row['Sell_Price'] / row['Buy_Price'] - 1) * 100,
        axis=1
    )
    sell_data = sell_data.sort_values(by='return_val', ascending=False).copy()

    for _, row in sell_data.iterrows():
      sell_type = "full" if pd.notna(row['Full_Sell_Date']) and pd.to_datetime(row['Full_Sell_Date']).date() == today.date() else "half"
      return_val = row['return_val']
      if return_val > 0 and sell_type == "full":
        emoji = "red_full_circle"
      elif return_val > 0 and sell_type == "half":
        emoji = "red_half_circle"
      else:
        emoji = "blue_full_circle"

      name = truncate_name(row['Name'], 12)
      buy_date = row['Buy_Date'].strftime('%y-%m-%d')
      holding_days = row['Full_Holding_Days'] if sell_type == "full" else row['Holding_Days']

      with builder.line() as line:
        line \
          .emoji(emoji) \
          .space() \
          .text(f"{name}") \
          .space() \
          .text(f"{return_val:+.1f}%,") \
          .space() \
          .text(f"{buy_date}") \
          .space() \
          .text(f"{holding_days:.0f}일")

    send_slack_message(builder.build(), token, channel)
    print(f"Sent {len(sell_data)} sell candidates to Slack.")

  except Exception as e:
    print(f"Error sending sell candidates to Slack: {e}")


def send_to_slack(trades_data, kospi, kosdaq):
  try:
    # 오늘 날짜 가져오기
    today = datetime.today()
    token = os.getenv("SLACK_BOT_TOKEN")
    channel = os.getenv("SLACK_CHANNEL")

    # 오늘 날짜의 매수 신호만 필터링
    today_trades = trades_data[trades_data['Buy_Date'].dt.date == today.date()] if not trades_data.empty else pd.DataFrame()
    today_kospi = kospi[kospi.index.date == today.date()] if not kospi.empty else pd.DataFrame()
    today_kosdaq = kosdaq[kosdaq.index.date == today.date()] if not kosdaq.empty else pd.DataFrame()

    builder = SlackMessageBuilder()

    # 헤더 추가
    builder.add_line(
        f"{today.year}년 {today.month}월 {today.day}일 매수 후보",
        bold=True
    )

    # 오늘 날짜의 trades를 Market별로 정렬
    if not today_trades.empty:
      today_trades = today_trades.sort_values(['Market', 'RS'], ascending=[False, False])

    # KOSPI와 KOSDAQ 각각 처리
    for market_name, market_df in [('KOSPI', today_kospi), ('KOSDAQ', today_kosdaq)]:
      # 시장 지표 계산
      if not market_df.empty:
        market_adx = market_df['ADX'].iloc[-1]
        market_di = market_df['DI'].iloc[-1]
        market_ma5_up = market_df['MA5_Up'].iloc[-1]
        market_ma20_up = market_df['MA20_Up'].iloc[-1]

        # 시장 상태에 따른 이모지 결정
        if market_ma20_up and 20 <= market_adx <= 70 and market_di:
          if 25 <= market_adx <= 70 and market_ma5_up:
            emoji = "green_sphere"
          elif 20 <= market_adx < 25 or not market_ma5_up:
            emoji = "yellow_sphere"
        else:
          emoji = "red_sphere"

        # 시장 정보 헤더 추가
        builder.add_line(
            f"{market_name} (ADX {market_adx:.2f}, DI {market_di})",
            emoji=emoji,
            bold=True,
            italic=True
        )
      else:
        # 시장 데이터가 없는 경우
        builder.add_line(
            f"{market_name} (데이터 없음)",
            emoji="question",
            bold=True,
            italic=True
        )

      # 해당 시장의 매수 후보 필터링
      market_trades = today_trades[today_trades['Market'].str.startswith(market_name)] if not today_trades.empty else pd.DataFrame()

      if market_trades.empty:
        # 해당 시장에 매수 후보가 없는 경우
        builder.add_line(f"오늘은 매수 후보가 없습니다.")
      else:
        # 매수 후보 종목들 추가
        for _, row in market_trades.iterrows():
          name = row['Name']
          marcap = row['Marcap']
          change = row['Change']
          ma20_gap = row['MA20_Gap']
          rs = row['RS']
          rs_1m = row['RS_1M']
          rs_3m = row['RS_3M']
          rs_6m = row['RS_6M']

          emoji = "question"
          if rs_1m >= rs_3m and rs_1m >= rs_6m and marcap >= 400_000_000_000 and change < 0.20:
            if 80 <= rs <= 97:
              emoji = "first_place_medal"
            elif (75 <= rs <= 79) or rs == 98:
              emoji = "second_place_medal"
            elif rs == 99:
              emoji = "third_place_medal"

          with builder.line() as line:
            line \
              .emoji(emoji) \
              .space() \
              .text(truncate_name(name, 10)) \
              .text(f"({format_market_cap(marcap)})") \
              .space() \
              .text(f"Change {change * 100:.1f}%,") \
              .space() \
              .text(f"20Gap {ma20_gap * 100:.1f}%,") \
              .space() \
              .text(f"RS {rs} ({rs_1m}/{rs_3m}/{rs_6m})") \

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
    #
    # # 날짜 설정
    today = datetime.today()

    krx_id = os.getenv("KRX_ID")
    krx_pw = os.getenv("KRX_PW")

    print("0. KRX 정보데이터시스템 로그인 진행 중...")
    if not krx_auth.login_krx(krx_id, krx_pw):
      print("❌ KRX 로그인에 실패했습니다. 아이디와 비밀번호를 확인하세요.")
      exit()
    print("✅ KRX 로그인 성공! 세션 쿠키가 확보되었습니다.")

    all_stocks = pd.concat([
      fdr.StockListing('KOSPI'),
      fdr.StockListing('KOSDAQ')
    ], ignore_index=True)

    # 윤달(2월 29일) 방어 로직 포함
    try:
      two_years_ago = today.replace(year=today.year - 2)
    except ValueError:
      two_years_ago = today.replace(year=today.year - 2, day=28)

    kospi = fdr.DataReader('KS11', two_years_ago)
    kospi['RSI'] = ta.rsi(kospi['Close'], length=14)
    adx_data = ta.adx(high=kospi['High'], low=kospi['Low'], close=kospi['Close'], length=14, mamode='EMA')
    kospi['ADX'] = adx_data['ADX_14']
    kospi['DI'] = adx_data['DMP_14'] > adx_data['DMN_14']
    kospi['MA5_Up'] = kospi['Close'] > kospi['Close'].rolling(window=5).mean()
    kospi['MA20_Up'] = kospi['Close'] > kospi['Close'].rolling(window=20).mean()
    kospi['MA60_Up'] = kospi['Close'] > kospi['Close'].rolling(window=60).mean()
    kospi['MA120_Up'] = kospi['Close'] > kospi['Close'].rolling(window=120).mean()

    kosdaq = fdr.DataReader('KQ11', two_years_ago)
    kosdaq['RSI'] = ta.rsi(kosdaq['Close'], length=14)
    adx_data = ta.adx(high=kosdaq['High'], low=kosdaq['Low'], close=kosdaq['Close'], length=14, mamode='EMA')
    kosdaq['ADX'] = adx_data['ADX_14']
    kosdaq['DI'] = adx_data['DMP_14'] > adx_data['DMN_14']
    kosdaq['MA5_Up'] = kosdaq['Close'] > kosdaq['Close'].rolling(window=5).mean()
    kosdaq['MA20_Up'] = kosdaq['Close'] > kosdaq['Close'].rolling(window=20).mean()
    kosdaq['MA60_Up'] = kosdaq['Close'] > kosdaq['Close'].rolling(window=60).mean()
    kosdaq['MA120_Up'] = kosdaq['Close'] > kosdaq['Close'].rolling(window=120).mean()

    # 병렬 처리로 데이터 분석
    result_data = parallel_process_stocks(all_stocks, two_years_ago)
    result_data = rs.calculate_relative_strength(result_data)
    filtered_data = filter_common_stocks(result_data)

    # buy_and_sell 함수를 사용하여 매수 후보 찾기
    trades_data = buy_and_sell(filtered_data, kospi, kosdaq)

    # Slack 메시지 전송 (오늘 날짜 매수 신호만)
    send_to_slack(trades_data, kospi, kosdaq)

    sell_candidates = find_sell_candidates(trades_data)
    send_sell_to_slack(sell_candidates)
  except Exception as e:
    print(f"Error in main execution: {e}")

  finally:
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"총 소요시간: {elapsed_time:.2f}초")
