import os
import re
import time
from datetime import datetime
import requests
import FinanceDataReader as fdr
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Slack Bot Token과 App Token 설정 (환경변수로 관리)
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

class KoreanStockBot:
  def __init__(self):
    # 한국거래소 종목 정보 캐시
    self.stock_list = None
    self.last_updated = None
    self.load_stock_list()

  def load_stock_list(self):
    """한국거래소 종목 리스트 로드"""
    try:
      # KOSPI + KOSDAQ 종목 리스트
      kospi = fdr.StockListing('KOSPI')
      kosdaq = fdr.StockListing('KOSDAQ')
      self.stock_list = {
        **{row['Name']: row['Code'] for _, row in kospi.iterrows()},
        **{row['Name']: row['Code'] for _, row in kosdaq.iterrows()},
        **{row['Code']: row['Code'] for _, row in kospi.iterrows()},
        **{row['Code']: row['Code'] for _, row in kosdaq.iterrows()}
      }
      self.last_updated = time.time()
      print(f"종목 리스트 업데이트 완료: {len(self.stock_list)}개 종목")
    except Exception as e:
      print(f"종목 리스트 로드 실패: {e}")

  def find_stock_code(self, query):
    """종목명 또는 코드로 종목 찾기"""
    # 캐시가 오래되었으면 다시 로드 (1시간마다)
    if time.time() - self.last_updated > 3600:
      self.load_stock_list()

    # 정확한 매치 우선
    if query in self.stock_list:
      return self.stock_list[query]

    # 부분 매치
    matches = [code for name, code in self.stock_list.items() if query in name]
    return matches[0] if matches else None

  def get_stock_info(self, stock_input):
    """주식 정보 조회"""
    try:
      # 종목 코드 찾기
      stock_code = self.find_stock_code(stock_input)
      if not stock_code:
        return f"❌ '{stock_input}' 종목을 찾을 수 없습니다."

      # 현재 주가 정보 조회
      stock_data = fdr.DataReader(stock_code, start='2025-01-01')
      if stock_data.empty:
        return f"❌ '{stock_input}' 종목의 데이터를 가져올 수 없습니다."

      # 최신 데이터
      latest = stock_data.iloc[-1]
      prev = stock_data.iloc[-2] if len(stock_data) > 1 else latest

      # 종목명 조회
      stock_name = None
      for name, code in self.stock_list.items():
        if code == stock_code and not code.isdigit():
          stock_name = name
          break

      if not stock_name:
        stock_name = stock_input

      # 등락율 계산
      change = latest['Close'] - prev['Close']
      change_rate = (change / prev['Close']) * 100

      # 이모지 설정
      emoji = "🔴" if change < 0 else "🔵" if change > 0 else "⚪"
      sign = "▼" if change < 0 else "▲" if change > 0 else "→"

      # 결과 포맷팅
      result = f"""
📈 **{stock_name} ({stock_code})**

💰 **현재가**: {latest['Close']:,.0f}원
{emoji} **등락**: {sign} {change:+,.0f}원 ({change_rate:+.2f}%)

📊 **거래 정보**:
• 시가: {latest['Open']:,.0f}원
• 고가: {latest['High']:,.0f}원
• 저가: {latest['Low']:,.0f}원
• 거래량: {latest['Volume']:,.0f}주

🕐 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """.strip()

      return result

    except Exception as e:
      return f"❌ 주식 정보 조회 중 오류가 발생했습니다: {str(e)}"

# KoreanStockBot 인스턴스 생성
stock_bot = KoreanStockBot()

@app.message("주식")
def handle_stock_query(message, say):
  """주식 명령어 처리"""
  text = message['text']

  # "주식 삼성전자" 또는 "주식 005930" 형태로 파싱
  match = re.search(r'주식\s+(.+)', text)
  if match:
    stock_input = match.group(1).strip()
    result = stock_bot.get_stock_info(stock_input)
    say(result)
  else:
    say("📖 사용법: `주식 [종목명 또는 종목코드]`\n예시: `주식 삼성전자` 또는 `주식 005930`")

@app.message(re.compile(r'^[0-9]{6}$'))
def handle_stock_code(message, say):
  """6자리 숫자(종목코드) 자동 인식"""
  stock_code = message['text']
  result = stock_bot.get_stock_info(stock_code)
  say(result)

@app.message("도움말")
def handle_help(message, say):
  """도움말 명령어"""
  help_text = """
🤖 **한국 주식 정보 봇**

📋 **사용 가능한 명령어**:
• `주식 [종목명/코드]` - 주식 정보 조회
• `005930` - 6자리 종목코드 직접 입력
• `도움말` - 이 도움말 표시

💡 **사용 예시**:
• `주식 삼성전자`
• `주식 005930`
• `005930`
• `주식 NAVER`

🔄 실시간 주가는 아니며, 가장 최근 거래일 기준 데이터입니다.
    """.strip()
  say(help_text)

@app.event("app_mention")
def handle_app_mention(event, say):
  """봇 멘션 처리"""
  text = event['text']
  # @봇이름 뒤의 텍스트 추출
  mention_removed = re.sub(r'<@[A-Z0-9]+>', '', text).strip()

  if mention_removed:
    if '주식' in mention_removed:
      stock_input = mention_removed.replace('주식', '').strip()
      if stock_input:
        result = stock_bot.get_stock_info(stock_input)
        say(result)
      else:
        say("📖 사용법: `@봇이름 주식 [종목명 또는 종목코드]`")
    else:
      # 직접 종목명이나 코드 입력
      result = stock_bot.get_stock_info(mention_removed)
      say(result)
  else:
    say("안녕하세요! 한국 주식 정보를 제공하는 봇입니다. `도움말`을 입력해보세요!")

# 앱 시작
if __name__ == "__main__":
  # Socket Mode로 실행 (무료)
  handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
  print("⚡️ 한국 주식 정보 봇이 시작되었습니다!")
  handler.start()