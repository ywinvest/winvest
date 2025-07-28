import os
import re
import threading
from datetime import datetime, timedelta

from flask import Flask, jsonify
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from pykrx import stock

# 토큰 검증
bot_token = os.environ.get("SLACK_BOT_TOKEN")
app_token = os.environ.get("SLACK_APP_TOKEN")

if not bot_token or not app_token:
  print("❌ 환경변수가 설정되지 않았습니다!")
  exit(1)

if not bot_token.startswith("xoxb-") or not app_token.startswith("xapp-"):
  print("❌ 토큰 형식이 잘못되었습니다!")
  exit(1)

# Flask 웹서버 (Render 포트 바인딩 요구사항)
flask_app = Flask(__name__)

# 봇 상태 추적
bot_status = {"running": False, "error": None}

@flask_app.route('/')
def home():
  return {
    "message": "한국 주식 Slack Bot이 실행 중입니다!",
    "bot_status": bot_status,
    "endpoints": {
      "health": "/health",
      "status": "/status"
    }
  }

@flask_app.route('/health')
def health():
  return jsonify({
    "status": "ok" if bot_status["running"] else "error",
    "bot_running": bot_status["running"],
    "error": bot_status.get("error")
  })

@flask_app.route('/status')
def status():
  return jsonify({
    "service": "Korean Stock Slack Bot",
    "version": "2.0.0 (pykrx)",
    "bot_status": bot_status,
    "cache_info": {
      "ticker_count": len(stock_bot.ticker_cache) // 2 if hasattr(stock_bot, 'ticker_cache') else 0,
      "last_updated": stock_bot.cache_updated.isoformat() if hasattr(stock_bot, 'cache_updated') and stock_bot.cache_updated else None
    },
    "environment": {
      "port": os.environ.get("PORT", "10000"),
      "has_bot_token": bool(bot_token),
      "has_app_token": bool(app_token)
    }
  })

# Slack App
slack_app = App(token=bot_token)

class LightStockBot:
  def __init__(self):
    self.ticker_cache = {}  # 종목명-코드 캐시
    self.cache_updated = None

  def update_ticker_cache(self):
    """종목 리스트 캐시 업데이트 (1일 1회)"""
    try:
      # 캐시가 없거나 하루 지났으면 업데이트
      if (self.cache_updated is None or
          datetime.now() - self.cache_updated > timedelta(days=1)):

        print("📋 종목 리스트 업데이트 중...")

        # KOSPI + KOSDAQ 종목 정보
        kospi_tickers = stock.get_market_ticker_list("20250101", market="KOSPI")
        kosdaq_tickers = stock.get_market_ticker_list("20250101", market="KOSDAQ")

        # 종목명-코드 매핑
        for ticker in kospi_tickers + kosdaq_tickers:
          try:
            name = stock.get_market_ticker_name(ticker)
            if name:
              self.ticker_cache[name] = ticker
              self.ticker_cache[ticker] = ticker  # 코드로도 접근 가능
          except:
            continue

        self.cache_updated = datetime.now()
        print(f"✅ 종목 {len(self.ticker_cache)//2}개 로드 완료")

    except Exception as e:
      print(f"⚠️ 종목 리스트 업데이트 실패: {e}")

  def find_stock_code(self, query):
    """종목명 또는 코드로 종목 찾기"""
    # 6자리 숫자면 종목코드로 간주
    if query.isdigit() and len(query) == 6:
      return query

    # 캐시 업데이트
    self.update_ticker_cache()

    # 정확한 매치
    if query in self.ticker_cache:
      return self.ticker_cache[query]

    # 부분 매치
    for name, code in self.ticker_cache.items():
      if query in name and len(code) == 6:  # 종목코드만
        return code

    return None

  def get_stock_info(self, stock_input):
    """주식 정보 조회 (pykrx 사용)"""
    try:
      # 종목코드 찾기
      stock_code = self.find_stock_code(stock_input.strip())
      if not stock_code:
          return f"❌ pykrx 모듈이 없어 6자리 종목코드만 사용 가능합니다.\n예: `005930`"

      # 종목명 가져오기
      try:
        stock_name = stock.get_market_ticker_name(stock_code)
      except:
        stock_name = stock_input

      # 최근 거래일 계산 (주말 제외)
      today = datetime.now()
      trade_date = today

      # 주말이면 금요일로
      if today.weekday() == 5:  # 토요일
        trade_date = today - timedelta(days=1)
      elif today.weekday() == 6:  # 일요일
        trade_date = today - timedelta(days=2)

      date_str = trade_date.strftime("%Y%m%d")

      # 주가 정보 조회
      try:
        # 최근 5일간 데이터 가져와서 최신 데이터 사용
        start_date = (trade_date - timedelta(days=7)).strftime("%Y%m%d")
        df = stock.get_market_ohlcv(start_date, date_str, stock_code)

        if df.empty:
          return f"❌ '{stock_name}({stock_code})' 종목의 데이터가 없습니다."

        # 최신 데이터
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest

        current_price = int(latest['종가'])
        change = current_price - int(prev['종가'])
        change_rate = (change / int(prev['종가']) * 100) if int(prev['종가']) > 0 else 0

        open_price = int(latest['시가'])
        high_price = int(latest['고가'])
        low_price = int(latest['저가'])
        volume = int(latest['거래량'])

        # 등락 표시
        if change > 0:
          emoji = "🔴"
          sign = "▲"
        elif change < 0:
          emoji = "🔵"
          sign = "▼"
        else:
          emoji = "⚪"
          sign = "→"

        # 결과 포맷팅
        result = f"""📈 **{stock_name} ({stock_code})**

💰 현재가: {current_price:,}원
{emoji} 등락: {sign} {change:+,}원 ({change_rate:+.2f}%)

📊 거래정보:
• 시가: {open_price:,}원 | 고가: {high_price:,}원
• 저가: {low_price:,}원 | 거래량: {volume:,}주

🕐 {df.index[-1].strftime('%Y-%m-%d')} 기준"""

        return result

      except Exception as e:
        return f"❌ '{stock_name}({stock_code})' 주가 데이터 조회 실패: 거래 중단 또는 데이터 없음"

    except Exception as e:
      return f"❌ 오류 발생: {str(e)[:50]}..."

# 봇 인스턴스 생성
stock_bot = LightStockBot()

@slack_app.command("/stock")
def handle_stock_slash_command(ack, respond, command):
  """슬래시 커맨드 '/stock 종목명' 처리"""
  ack()  # 명령어 수신 확인

  stock_input = command['text'].strip()
  if not stock_input:
    respond("📖 사용법: `/stock [종목명 또는 종목코드]`\n예시: `/stock 삼성전자` 또는 `/stock 005930`")
    return

  result = stock_bot.get_stock_info(stock_input)
  respond(result)

@slack_app.message(re.compile(r'^stock\s+(.+)', re.IGNORECASE))
def handle_stock_message(message, say):
  """'stock 종목명' 일반 메시지 처리 (슬래시 없음)"""
  match = re.search(r'stock\s+(.+)', message['text'], re.IGNORECASE)
  if match:
    stock_input = match.group(1).strip()
    result = stock_bot.get_stock_info(stock_input)
    say(result)

@slack_app.message(re.compile(r'^[0-9]{6}$'))
def handle_stock_code_direct(message, say):
  """6자리 종목코드 직접 입력"""
  stock_code = message['text']
  result = stock_bot.get_stock_info(stock_code)
  say(result)

@slack_app.message("도움말")
def handle_help(message, say):
  """도움말"""
  if PYKRX_AVAILABLE:
    help_text = """🤖 **한국 주식 봇 (pykrx 버전)**

📋 **사용법**:
• `/stock 삼성전자` - 슬래시 커맨드 (추천)
• `stock 네이버` - 일반 메시지 (슬래시 없이)
• `005930` - 6자리 코드 직접 입력
• `@봇이름 stock LG화학` - 멘션으로 조회
• `도움말` - 이 메시지 표시

💡 **지원**: KOSPI, KOSDAQ 전 종목
⚡ pykrx로 안정적인 데이터 제공!"""
  else:
    help_text = """🤖 **한국 주식 봇 (종목코드 전용)**

📋 **사용법**:
• `/stock 005930` - 슬래시 커맨드
• `005930` - 6자리 코드 직접 입력

⚠️ **제한**: pykrx 모듈 없음 - 종목코드만 사용 가능
💡 **예시**: 삼성전자(005930), 네이버(035420)"""

  say(help_text)

@slack_app.event("app_mention")
def handle_app_mention(event, say):
  """봇 멘션 처리"""
  text = event['text']
  mention_removed = re.sub(r'<@[A-Z0-9]+>', '', text).strip()

  if mention_removed:
    # stock 명령어 확인 (슬래시 없음)
    stock_match = re.search(r'stock\s+(.+)', mention_removed, re.IGNORECASE)
    if stock_match:
      stock_input = stock_match.group(1).strip()
      result = stock_bot.get_stock_info(stock_input)
      say(result)
    else:
      # 직접 종목명 입력
      result = stock_bot.get_stock_info(mention_removed)
      say(result)
  else:
    say("💡 사용법: `@봇이름 stock 삼성전자`, `/stock 삼성전자` 또는 `도움말`")

def run_slack_bot():
  """Slack 봇을 별도 스레드에서 실행"""
  try:
    handler = SocketModeHandler(slack_app, app_token)
    bot_status["running"] = True
    bot_status["error"] = None
    print("⚡️ Slack 봇이 시작되었습니다!")
    handler.start()
  except Exception as e:
    bot_status["running"] = False
    bot_status["error"] = str(e)
    print(f"❌ Slack 봇 시작 실패: {e}")

# 메인 실행
if __name__ == "__main__":
  # Render의 PORT 환경변수 사용 (기본값: 10000)
  port = int(os.environ.get("PORT", 10000))

  print(f"🌐 웹서버 포트: {port}")
  print(f"🔧 Bot Token: {bot_token[:12]}..." if bot_token else "❌ Bot Token 없음")
  print(f"🔧 App Token: {app_token[:12]}..." if app_token else "❌ App Token 없음")

  # Slack 봇을 별도 스레드에서 실행
  bot_thread = threading.Thread(target=run_slack_bot, daemon=True)
  bot_thread.start()

  # Flask 웹서버 실행 (0.0.0.0 바인딩 - Render 요구사항)
  print(f"🚀 서버 시작: 0.0.0.0:{port}")
  flask_app.run(host="0.0.0.0", port=port, debug=False)