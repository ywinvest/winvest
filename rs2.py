import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm


def calculate_rs_worker(args):
  code, name, date_ranges, base_date_str = args
  try:
    df = fdr.DataReader(code, date_ranges["6M"], base_date_str)
    if df is None or df.empty or 'Close' not in df.columns:
      return None

    last_price = df["Close"][-1]

    result = {
      "ticker": code,
      "name": name
    }

    for label, start_date in date_ranges.items():
      df_filtered = df[df.index >= pd.to_datetime(start_date)]
      if df_filtered.empty:
        result[f"return_{label}"] = None
        continue
      start_price = df_filtered.iloc[0]["Close"]
      if start_price == 0:
        result[f"return_{label}"] = None
      else:
        result[f"return_{label}"] = (last_price / start_price - 1) * 100

    return result
  except:
    return None


def process_market(market: str, base_date: datetime, max_workers: int = 4):
  base_date_str = base_date.strftime('%Y-%m-%d')

  date_ranges = {
    "1M": (base_date - timedelta(days=30)).strftime('%Y-%m-%d'),
    "3M": (base_date - timedelta(days=90)).strftime('%Y-%m-%d'),
    "6M": (base_date - timedelta(days=180)).strftime('%Y-%m-%d'),
  }

  # 종목 리스트 가져오기
  stock_df = fdr.StockListing(market)
  stock_df = stock_df[stock_df['Code'].str.len() == 6]  # 6자리 종목코드만

  print(f"[{market}] 종목 수: {len(stock_df)} - 병렬 계산 시작")

  args_list = [(row['Code'], row['Name'], date_ranges, base_date_str) for _, row in stock_df.iterrows()]

  results = []
  with ProcessPoolExecutor(max_workers=max_workers) as executor:
    futures = {executor.submit(calculate_rs_worker, args): args[0] for args in args_list}
    for future in tqdm(as_completed(futures), total=len(futures), desc=f"{market}"):
      result = future.result()
      if result:
        results.append(result)

  # DataFrame 생성
  df_result = pd.DataFrame(results)

  for label in ["1M", "3M", "6M"]:
    return_col = f"return_{label}"
    rs_col = f"RS_{label}"
    df_result[rs_col] = df_result[return_col].rank(pct=True) * 100
    df_result[rs_col] = df_result[rs_col].round(1)

  df_result = df_result[["ticker", "name", "RS_1M", "RS_3M", "RS_6M"]]
  df_result = df_result.sort_values(by="RS_1M", ascending=False)

  csv_filename = f"william_oneil_rs_{market.lower()}_{base_date_str}.csv"
  df_result.to_csv(csv_filename, index=False, encoding="utf-8-sig")

  print(f"✅ 저장 완료: {csv_filename}")


def main():
  base_date = datetime.today()
  max_workers = 4  # CPU 성능에 맞게 조정

  for market in ['KOSPI', 'KOSDAQ']:
    process_market(market, base_date, max_workers)


if __name__ == "__main__":
  main()
