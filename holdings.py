from pykrx import stock

def fetch_etf_holdings_from_pykrx(ticker):
  """
  Fetch ETF holdings using pykrx.

  Parameters:
      ticker (str): The ETF ticker symbol (e.g., "305720.KS" for KODEX 2차전지).

  Returns:
      list: List of holdings with name and weight percentage.
  """
  try:
    # 티커에서 종목 코드 추출
    ticker_code = ticker.split(".")[0]

    # ETF 구성 종목 데이터 조회
    holdings = stock.get_etf_portfolio_deposit_file(ticker_code)

    if holdings.empty:
      print(f"No holdings data found for ticker: {ticker}")
      return []

    # 데이터 가공
    result = []
    for name, row in holdings.iterrows():
      weight = row['비중']
      result.append({"holdingName": name, "holdingPercent": weight})

    return result
  except Exception as e:
    print(f"Error fetching ETF holdings for {ticker}: {e}")
    return []

# 테스트
if __name__ == "__main__":
  ticker = "305720.KS"  # KODEX 2차전지
  holdings = fetch_etf_holdings_from_pykrx(ticker)
  for holding in holdings:
    print(f"{holding['holdingName']}: {holding['holdingPercent']}%")
