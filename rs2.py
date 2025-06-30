import pandas as pd
from pykrx import stock
from datetime import datetime, timedelta
from tqdm import tqdm

# 기준일 설정
base_date = datetime.today()
base_date_str = base_date.strftime('%Y%m%d')

# 분석 대상 기간
dates = {
  "1M": (base_date - timedelta(days=30)).strftime('%Y%m%d'),
  "3M": (base_date - timedelta(days=90)).strftime('%Y%m%d'),
  "6M": (base_date - timedelta(days=180)).strftime('%Y%m%d'),
}

# 종목 리스트 가져오기
tickers = stock.get_market_ticker_list(market='KOSPI')# + stock.get_market_ticker_list(market='KOSDAQ')

# 결과 저장
results = []

print("RS 계산 중...")
for ticker in tqdm(tickers):
  try:
    df = stock.get_market_ohlcv_by_date(dates["6M"], base_date_str, ticker)
    if df is None or df.empty:
      continue

    # 날짜 기준 가격 추출
    first_prices = {}
    for label, date in dates.items():
      df_temp = df[df.index >= pd.to_datetime(date)]
      if df_temp.empty:
        first_prices[label] = None
      else:
        first_prices[label] = df_temp.iloc[0]["종가"]

    last_price = df.iloc[-1]["종가"]

    row = {
      "ticker": ticker,
      "name": stock.get_market_ticker_name(ticker)
    }

    # 수익률 계산
    for label in ["1M", "3M", "6M"]:
      start_price = first_prices[label]
      if start_price is None or start_price == 0:
        row[f"return_{label}"] = None
      else:
        row[f"return_{label}"] = (last_price / start_price - 1) * 100

    results.append(row)

  except Exception:
    continue

# DataFrame 생성
df_result = pd.DataFrame(results)

# RS 점수 계산 (백분위)
for label in ["1M", "3M", "6M"]:
  return_col = f"return_{label}"
  rs_col = f"RS_{label}"
  df_result[rs_col] = df_result[return_col].rank(pct=True) * 100
  df_result[rs_col] = df_result[rs_col].round(1)

# 불필요한 컬럼 제거 (수익률 컬럼 제거해도 됨)
df_result = df_result[["ticker", "name", "RS_1M", "RS_3M", "RS_6M"]]

# 결과 정렬 (예: 최근 1개월 RS 기준으로 정렬)
df_result = df_result.sort_values(by="RS_1M", ascending=False)

# CSV 저장
csv_filename = f"william_oneil_rs_multi_{base_date_str}.csv"
df_result.to_csv(csv_filename, index=False, encoding="utf-8-sig")

print(f"\n✅ CSV 파일 저장 완료: {csv_filename}")
