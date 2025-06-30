import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm


# 워커 함수: 거래일 기준 iloc으로 수익률 계산
def calculate_rs_worker(args):
  code, name, base_date_str = args
  try:
    # 최소 120거래일 확보 위해 200일 전부터 조회
    df = fdr.DataReader(code, start=(datetime.strptime(base_date_str, "%Y-%m-%d") - pd.Timedelta(days=200)).strftime("%Y-%m-%d"), end=base_date_str)
    if df is None or df.empty or 'Close' not in df.columns or len(df) < 121:
      return None

    last_price = df["Close"].iloc[-1]

    result = {
      "ticker": code,
      "name": name
    }

    periods = {"1M": 20, "3M": 60, "6M": 120}

    for label, offset in periods.items():
      if len(df) >= offset:
        start_price = df["Close"].iloc[-offset]
        if start_price == 0:
          result[f"return_{label}"] = None
        else:
          result[f"return_{label}"] = (last_price / start_price - 1) * 100
      else:
        result[f"return_{label}"] = None

    return result
  except:
    return None


# 시장별 계산 함수
def process_market(market: str, base_date: datetime, max_workers: int = 4):
  base_date_str = base_date.strftime('%Y-%m-%d')

  # 종목 리스트 가져오기
  stock_df = fdr.StockListing(market)
  # stock_df = stock_df[stock_df['Code'].str.len() == 6]  # 6자리 종목만

  print(f"[{market}] 종목 수: {len(stock_df)} - 병렬 계산 시작")

  args_list = [(row['Code'], row['Name'], base_date_str) for _, row in stock_df.iterrows()]

  results = []
  with ProcessPoolExecutor(max_workers=max_workers) as executor:
    futures = {executor.submit(calculate_rs_worker, args): args[0] for args in args_list}
    for future in tqdm(as_completed(futures), total=len(futures), desc=f"{market}"):
      result = future.result()
      if result:
        results.append(result)

  # 결과 DataFrame
  df_result = pd.DataFrame(results)

  # 백분위 → 1~99 점수화
  for label in ["1M", "3M", "6M"]:
    return_col = f"return_{label}"
    rs_col = f"RS_{label}"
    df_result[rs_col] = df_result[return_col].rank(pct=True) * 98 + 1
    df_result[rs_col] = df_result[rs_col].fillna(1).astype(int).clip(1, 99)

  # 결과 정리 및 저장
  df_result = df_result[["ticker", "name", "RS_1M", "RS_3M", "RS_6M"]]
  df_result = df_result.sort_values(by="RS_1M", ascending=False)

  csv_filename = f"william_oneil_rs_{market.lower()}_{base_date_str}.csv"
  df_result.to_csv(csv_filename, index=False, encoding="utf-8-sig")

  print(f"✅ 저장 완료: {csv_filename}")


# 실행 함수
def main():
  base_date = datetime.today()
  max_workers = 4  # CPU 자원에 따라 조절

  for market in ['KOSPI', 'KOSDAQ']:
    process_market(market, base_date, max_workers)


if __name__ == "__main__":
  main()
