import os
import re
import threading
from datetime import datetime

import requests
from flask import Flask
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# 토큰 검증
bot_token = os.environ.get("SLACK_BOT_TOKEN")
app_token = os.environ.get("SLACK_APP_TOKEN")

if not bot_token or not app_token:
  print("❌ 환경변수가 설정되지 않았습니다!")
  exit(1)

if not bot_token.startswith("xoxb-") or not app_token.startswith("xapp-"):
  print("❌ 토큰 형식이 잘못되었습니다!")
  exit(1)

# Flask 웹서버 (더미)
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
  return "한국 주식 Slack Bot이 실행 중입니다!"

@flask_app.route('/health')
def health():
  return {"status": "ok", "message": "Bot is running"}

# Slack App
slack_app = App(token=bot_token)

class LightStockBot:
  def __init__(self):
    self.base_url = "https://polling.finance.naver.com/api/realtime"
    self.headers = {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

  def search_stock_code(self, query):
    try:
      if query.isdigit() and len(query) == 6:
        return query

      search_url = f"https://ac.finance.naver.com/ac"
      params = {
        'q': query,
        'q_enc': 'UTF-8',
        'st': '111',
        'frm': 'stock',
        'r_format': 'json',
        'r_enc': 'UTF-8',
        'r_unicode': '0',
        't_koreng': '1',
        'r_lt': '111'
      }

      response = requests.get(search_url, params=params, headers=self.headers, timeout=5)
      if response.status_code == 200:
        data = response.json()
        if 'items' in data and len(data['items']) > 0:
          for item in data['items']:
            if len(item) >= 2:
              code_match = re.search(r'(\d{6})', item[0])
              if code_match:
                return code_match.group(1)

      return None
    except Exception as e:
      print(f"종목 검색 오류: {e}")
      return None

  def get_stock_info(self, stock_input):
    try:
      stock_code = self.search_stock_code(stock_input.strip())
      if not stock_code:
        return f"❌ '{stock_input}' 종목을 찾을 수 없습니다."

      url = f"{self.base_url}.nhn"
      params = {'query': f'SERVICE_ITEM:{stock_code}'}

      response = requests.get(url, params=params, headers=self.headers, timeout=10)

      if response.status_code != 200:
        return f"❌ 주가 정보를 가져올 수 없습니다."

      data = response.json()

      if 'result' not in data or 'areas' not in data['result']:
        return f"❌ '{stock_input}' 종목의 데이터가 없습니다."

      areas = data['result']['areas']
      if not areas or len(areas[0]['datas']) == 0:
        return f"❌ '{stock_input}' 종목의 데이터가 없습니다."

      stock_data = areas[0]['datas'][0]

      name = stock_data.get('nm', stock_input)
      current_price = int(stock_data.get('nv', 0))
      change = int(stock_data.get('cv', 0))
      change_rate = float(stock_data.get('cr', 0))

      open_price = int(stock_data.get('ov', 0))
      high_price = int(stock_data.get('hv', 0))
      low_price = int(stock_data.get('lv', 0))
      volume = int(stock_data.get('aq', 0))

      if change > 0:
        emoji = "🔴"
        sign = "▲"
      elif change < 0:
        emoji = "🔵"
        sign = "▼"
      else:
        emoji = "⚪"
        sign = "→"

      result = f"""📈 **{name} ({stock_code})**

💰 현재가: {current_price:,}원
{emoji} 등락: {sign} {change:+,}원 ({change_rate:+.2f}%)

📊 거래정보:
• 시가: {open_price:,}원 | 고가: {high_price:,}원
• 저가: {low_price:,}원 | 거래량: {volume:,}주

🕐 {datetime.now().strftime('%H:%M:%S')}"""

      return result

    except requests.exceptions.Timeout:
      return "❌ 요청 시간이 초과되었습니다. 다시 시도해주세요."
    except Exception as e:
      return f"❌ 오류 발생: 네트워크를 확인해주세요."

# 봇 인스턴스 생성
stock_bot = LightStockBot()

@slack_app.message(re.compile(r'^/stock\s+(.+)', re.IGNORECASE))
def handle_stock_command(message, say):
  match = re.search(r'/stock\s+(.+)', message['text'], re.IGNORECASE)
  if match:
    stock_input = match.group(1).strip()
    result = stock_bot.get_stock_info(stock_input)
    say(result)

@slack_app.message(re.compile(r'^[0-9]{6}$'))
def handle_stock_code_direct(message, say):
  stock_code = message['text']
  result = stock_bot.get_stock_info(stock_code)
  say(result)

@slack_app.message("도움말")
def handle_help(message, say):
  help_text = """🤖 **경량 한국 주식 봇**

📋 **사용법**:
• `/stock 삼성전자` - 종목명으로 조회
• `/stock 005930` - 종목코드로 조회  
• `005930` - 6자리 코드 직접 입력
• `도움말` - 이 메시지 표시

💡 **예시**: `/stock 네이버`, `/stock TSLA`
⚡ 경량화로 빠른 응답!"""
  say(help_text)

@slack_app.event("app_mention")
def handle_app_mention(event, say):
  text = event['text']
  mention_removed = re.sub(r'<@[A-Z0-9]+>', '', text).strip()

  if mention_removed:
    stock_match = re.search(r'/stock\s+(.+)', mention_removed, re.IGNORECASE)
    if stock_match:
      stock_input = stock_match.group(1).strip()
      result = stock_bot.get_stock_info(stock_input)
      say(result)
    else:
      result = stock_bot.get_stock_info(mention_removed)
      say(result)
  else:
    say("💡 사용법: `@봇이름 /stock 삼성전자` 또는 `도움말`")

def run_slack_bot():
  """Slack 봇을 별도 스레드에서 실행"""
  try:
    handler = SocketModeHandler(slack_app, app_token)
    print("⚡️ Slack 봇 시작!")
    handler.start()
  except Exception as e:
    print(f"❌ Slack 봇 시작 실패: {e}")

# 메인 실행
if __name__ == "__main__":
  # Slack 봇을 별도 스레드에서 실행
  bot_thread = threading.Thread(target=run_slack_bot, daemon=True)
  bot_thread.start()

  # Flask 웹서버 실행 (Render 포트 요구사항 충족)
  port = int(os.environ.get("PORT", 5000))
  print(f"🌐 웹서버 시작 (포트: {port})")
  flask_app.run(host="0.0.0.0", port=port)