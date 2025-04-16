import yfinance as yf
import requests
from bs4 import BeautifulSoup
from pykrx import stock


def get_dollar_index():
  ticker = "DX-Y.NYB"  # Dollar Index
  data = yf.Ticker(ticker)
  history = data.history(period="1d")
  price = history['Close'].iloc[-1]  # iloc으로 마지막 값 가져오기
  return round(price, 2)


def get_usd_krw_exchange_rate():
  url = "https://finance.naver.com/marketindex/"
  response = requests.get(url)
  soup = BeautifulSoup(response.content, "html.parser")
  rate_element = soup.select_one("div.head_info > span.value")
  if rate_element:
    return float(rate_element.text.replace(",", ""))
  else:
    raise ValueError("원-달러 환율 데이터를 찾을 수 없습니다.")


def get_usd_jpy_exchange_rate():
  ticker = "JPY=X"  # USD/JPY Exchange Rate
  data = yf.Ticker(ticker)
  history = data.history(period="1d")
  price = history['Close'].iloc[-1]  # iloc으로 마지막 값 가져오기
  return round(price, 2)


def get_fear_greed_index():
  url = "https://money.cnn.com/data/fear-and-greed/"
  response = requests.get(url)
  soup = BeautifulSoup(response.content, "html.parser")
  index_element = soup.find("div", class_="feargreedvalue")
  if index_element:
    return int(index_element.text.strip())
  else:
    raise ValueError("Fear & Greed Index 데이터를 찾을 수 없습니다.")


def get_credit_balance():
  # 코스피와 코스닥 신용잔고 데이터 가져오기
  kospi = stock.get_market_trading_value_by_date(
      "20240101", "20241219", ticker="KOSPI"
  )
  kosdaq = stock.get_market_trading_value_by_date(
      "20240101", "20241219", ticker="KOSDAQ"
  )

  # 합계 계산 (예시: 특정 컬럼에서 신용잔고 데이터를 추출)
  kospi_credit = kospi['신용잔고'].sum() if '신용잔고' in kospi.columns else 0
  kosdaq_credit = kosdaq['신용잔고'].sum() if '신용잔고' in kosdaq.columns else 0

  return kospi_credit, kosdaq_credit


def main():
  try:
    print("1. 달러인덱스 (Dollar Index):", get_dollar_index())
  except Exception as e:
    print("달러인덱스 데이터를 가져오는 중 오류 발생:", e)

  try:
    print("2. 원-달러 환율 (USD/KRW):", get_usd_krw_exchange_rate())
  except Exception as e:
    print("원-달러 환율 데이터를 가져오는 중 오류 발생:", e)

  try:
    print("3. 달러-엔 환율 (USD/JPY):", get_usd_jpy_exchange_rate())
  except Exception as e:
    print("달러-엔 환율 데이터를 가져오는 중 오류 발생:", e)

  try:
    print("4. Fear & Greed Index:", get_fear_greed_index())
  except Exception as e:
    print("Fear & Greed Index 데이터를 가져오는 중 오류 발생:", e)

  try:
    kospi_credit, kosdaq_credit = get_credit_balance()
    print(f"5. 코스피 신용잔고: {kospi_credit} 억 원")
    print(f"6. 코스닥 신용잔고: {kosdaq_credit} 억 원")
  except Exception as e:
    print("데이터를 가져오는 중 오류 발생:", e)


if __name__ == "__main__":
  main()
