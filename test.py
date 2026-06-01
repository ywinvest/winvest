import pandas as pd
from pykrx import stock

if __name__ == "__main__":
  """
  pykrx를 사용하여 특정 종목의 일별 투자자별 순매수량(거래량)을 가져옵니다.
  :param symbol: 종목 코드 (예: '005930')
  :param start_date_str: 시작일 문자열 (예: '20230101')
  :return: DataFrame (index: 날짜, columns: 순매수량)
  """
  ticker = "005930"
  start_date_str = "20150615"
  try:
    # 데이터 조회 (단위: 주)
    df_krx = stock.get_market_trading_volume_by_date(
        fromdate=start_date_str,
        todate=start_date_str,
        ticker=ticker
    )

    # 필요한 컬럼만 선택하고 이름을 변경
    df_krx = df_krx[['개인', '외국인', '기관합계']].copy()
    df_krx.columns = ['Net_Buy_Individual', 'Net_Buy_Foreigner', 'Net_Buy_Institution']

    # 순매수량으로 변환: 매수량 - 매도량 = 순매수량 (pykrx는 이미 순매수량으로 제공)
    # 금액 단위로 변환이 필요하면 (수량 * 종가)를 사용해야 함. 여기서는 수량(주) 사용

    # 인덱스를 datetime 형식으로 변환
    df_krx.index = pd.to_datetime(df_krx.index, format='%Y%m%d')

  except Exception as e:
    print(f"Error fetching pykrx data for {ticker}: {e}")