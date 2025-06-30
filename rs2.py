import pandas as pd
from pykrx import stock
from datetime import datetime, timedelta
from tqdm import tqdm

# 기준일 설정
base_date = datetime.today().strftime('%Y%m%d')
one_year_ago = (datetime.today() - timedelta(days=365)).strftime('%Y%m%d')

# 코스피 + 코스닥 전체 종목 리스트 가져오기
tickers = stock.get_market_ticker_list(market='KOSPI')# + stock.get_market_ticker_list(market='KOSDAQ')

# 수익률 계산 결과 저장
results = []

print("수익률 계산 중...")
for ticker in tqdm(tickers):
  try:
    df = stock.get_market_ohlcv_by_date(one_year_ago, base_date, ticker)
    if df is None or df.empty:
      continue

    start_price = df.iloc[0]['종가']
    end_price = df.iloc[-1]['종가']

    if start_price > 0:
      return_1y = (end_price / start_price - 1) * 100
      results.append({'ticker': ticker, 'return_1y': return_1y})
  except Exception:
    continue

# 데이터프레임 생성
df_result = pd.DataFrame(results)

# 상대강도 (RS) 계산 - 백분위 (Percentile)
df_result['rs_score'] = df_result['return_1y'].rank(pct=True) * 100
df_result['rs_score'] = df_result['rs_score'].round(1)

# 종목명 추가
df_result['name'] = df_result['ticker'].apply(lambda x: stock.get_market_ticker_name(x))

# 컬럼 정렬 및 저장
df_result = df_result[['ticker', 'name', 'return_1y', 'rs_score']]
df_result = df_result.sort_values(by='rs_score', ascending=False)

# CSV 파일로 저장
csv_filename = f"william_oneil_rs_{base_date}.csv"
df_result.to_csv(csv_filename, index=False, encoding='utf-8-sig')

print(f"\n✅ CSV 파일 저장 완료: {csv_filename}")
