
from datetime import datetime

import pandas as pd
from pykrx import stock


def get_all_stocks():
  """pykrx를 활용하여 KOSPI/KOSDAQ 전 종목의 기본 정보와 시가총액을 반환합니다."""
  print("1. pykrx를 활용하여 전 종목 기본 데이터 및 시가총액 수집 중...")

  today_str = datetime.today().strftime("%Y%m%d")

  # 1. 가장 최근 영업일 확인 (세션 패치가 적용된 상태에서 실행됨)
  latest_b_day = stock.get_nearest_business_day_in_a_week(today_str)

  # 2. KOSPI, KOSDAQ 시가총액 데이터를 가져오면서 티커(Code) 확보
  df_kospi = stock.get_market_cap(latest_b_day, market="KOSPI").reset_index()
  df_kospi['Market'] = 'KOSPI'

  df_kosdaq = stock.get_market_cap(latest_b_day, market="KOSDAQ").reset_index()
  df_kosdaq['Market'] = 'KOSDAQ'

  # 3. 두 시장 데이터 병합
  all_stocks = pd.concat([df_kospi, df_kosdaq], ignore_index=True)

  # 4. pykrx 내장 함수를 사용하여 티커를 종목명(Name)으로 변환
  # (내부적으로 캐싱된 마스터 데이터를 사용하므로 수천 개를 변환해도 1초 이내에 완료됨)
  all_stocks['Name'] = all_stocks['티커'].apply(stock.get_market_ticker_name)

  # 5. 필요한 컬럼만 추출하고 이름 변경 ('티커' -> 'Code', '시가총액' -> 'Marcap')
  all_stocks = all_stocks[['티커', 'Name', 'Market', '시가총액']].rename(
      columns={'티커': 'Code', '시가총액': 'Marcap'}
  )

  # 결측치(NaN) 처리: 시가총액이 없는 종목은 0으로 처리
  all_stocks['Marcap'] = all_stocks['Marcap'].fillna(0).astype(int)

  return all_stocks


def get_index_data(start_str, end_str=None):
  """pykrx를 활용하여 KOSPI와 KOSDAQ의 지수 OHLCV 데이터를 반환합니다."""
  if end_str is None:
    end_str = datetime.today().strftime("%Y%m%d")

  print(f"지수 데이터(KOSPI, KOSDAQ) 수집 중... ({start_str} ~ {end_str})")

  # KOSPI (1001)
  kospi = stock.get_index_ohlcv(start_str, end_str, "1001")
  kospi = kospi.rename(columns={'시가': 'Open', '고가': 'High', '저가': 'Low', '종가': 'Close', '거래량': 'Volume'})

  # KOSDAQ (2001)
  kosdaq = stock.get_index_ohlcv(start_str, end_str, "2001")
  kosdaq = kosdaq.rename(columns={'시가': 'Open', '고가': 'High', '저가': 'Low', '종가': 'Close', '거래량': 'Volume'})

  return kospi, kosdaq