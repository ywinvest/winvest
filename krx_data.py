import pandas as pd
from datetime import datetime

def get_pykrx_market_listing(market: str, date_str: str = None) -> pd.DataFrame:
    """
    FinanceDataReader의 fdr.StockListing을 대체하는 pykrx 기반 데이터 수집 함수.
    KRX 봇 차단 이슈로 fdr.StockListing이 404 에러를 발생시키는 문제를 해결하기 위해 사용합니다.
    주의: 이 함수를 호출하기 전에 환경변수 로드 및 krx_auth.login_krx() 가 실행되어 있어야 합니다.
    """
    from pykrx import stock
    from pykrx.website.krx.market.wrap import get_market_ticker_and_name
    
    if date_str is None:
        date = datetime.today().strftime('%Y%m%d')
    else:
        # 입력된 날짜 포맷이 YYYY-MM-DD 인 경우를 대비해 하이픈 제거 (pykrx는 YYYYMMDD 요구)
        date = date_str.replace('-', '')
    
    # pykrx의 OHLCV에는 시가, 고가, 저가, 종가, 거래량, 거래대금, 등락률, 시가총액이 모두 포함됨
    df_ohlcv = stock.get_market_ohlcv(date, market=market)
    sr_name = get_market_ticker_and_name(date, market=market)
    
    # 티커(인덱스) 기준으로 병합
    df = pd.concat([df_ohlcv, sr_name], axis=1, join='inner')
    
    # 인덱스 초기화 및 컬럼명을 FDR 호환 형식으로 변경
    df = df.reset_index().rename(columns={
        '티커': 'Code',
        '종목명': 'Name',
        '등락률': 'ChagesRatio',
        '시가총액': 'Marcap',
        '거래대금': 'Amount',
        '시가': 'Open',
        '고가': 'High',
        '저가': 'Low',
        '종가': 'Close',
        '거래량': 'Volume'
    })
    
    # 빈 컬럼(Changes, Stocks) 채우기 (FDR 호환용)
    if 'Close' in df.columns and 'Marcap' in df.columns:
        # 상장주식수(Stocks) = 시가총액 // 종가
        df['Stocks'] = (df['Marcap'] / df['Close'].replace(0, 1)).fillna(0).astype(int)
    else:
        df['Stocks'] = 0
        
    if 'Changes' not in df.columns:
        df['Changes'] = 0
    
    df['Market'] = market
    return df
