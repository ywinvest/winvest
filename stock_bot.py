import os
import threading
from datetime import datetime, timedelta

import FinanceDataReader as fdr
from flask import Flask, jsonify
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from slack_utils import SlackMessageBuilder

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
    "message": "주식 Slack Bot이 실행 중입니다!",
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
    "service": "Stock Slack Bot",
    "version": "0.0.1",
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

        krx_df = fdr.StockListing('KRX')

        # 종목명-코드 매핑
        for _, row in krx_df.iterrows():
          try:
            ticker = row['Code']
            name = row['Name']
            if name and ticker:
              self.ticker_cache[name] = ticker
              self.ticker_cache[ticker] = ticker
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
    """주식 정보 조회 (FinanceDataReader 사용)"""
    try:
      # 종목코드 찾기
      stock_code = self.find_stock_code(stock_input.strip())
      print(f"종목 코드: {stock_code}")
      if not stock_code:
        builder = SlackMessageBuilder()
        with builder.line() as line:
          line \
            .emoji("red_x") \
            .space() \
            .text("종목을 찾을 수 없습니다. 6자리 종목코드(예: ") \
            .text("005930", code=True) \
            .text(") 또는 정확한 종목명(예: ") \
            .text("삼성전자", code=True) \
            .text(")")
        return {"response_type": "ephemeral", "blocks": builder.build()}

      # 종목명 가져오기
      try:
        # 캐시에서 종목명 조회
        stock_name = next((name for name, code in self.ticker_cache.items() if code == stock_code and name != stock_code), stock_input)
        print(f"종목명: {stock_name}")
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

      # 주가 정보 조회
      try:
        # 최근 7일간 데이터 가져와서 최신 데이터 사용
        start_date = trade_date - timedelta(days=7)
        print(f"데이터 조회: {stock_code} ({start_date} ~ {trade_date})")
        df = fdr.DataReader(stock_code, start=start_date, end=trade_date)
        print(f"데이터 조회 결과: {df.tail()}")

        if df.empty:
          builder = SlackMessageBuilder()
          builder.add_line(
              text=f"'{stock_name} ({stock_code})' 종목의 데이터가 없습니다.",
              emoji="red_x"
          )
          return {"blocks": builder.build()}

        # 최신 데이터
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest

        prev_close_price = int(prev['Close'])
        prev_volume = int(prev['Volume'])

        close_price = int(latest['Close'])
        open_price = int(latest['Open'])
        high_price = int(latest['High'])
        low_price = int(latest['Low'])
        volume = int(latest['Volume'])

        # 등락률 계산
        close_change_rate = ((close_price - prev_close_price) / prev_close_price * 100) if prev_close_price > 0 else 0
        open_change_rate = ((open_price - prev_close_price) / prev_close_price * 100) if prev_close_price > 0 else 0
        high_change_rate = ((high_price - prev_close_price) / prev_close_price * 100) if prev_close_price > 0 else 0
        low_change_rate = ((low_price - prev_close_price) / prev_close_price * 100) if prev_close_price > 0 else 0
        volume_change_rate = ((volume - prev_volume) / prev_volume * 100) if prev_volume > 0 else 0

        # 등락 이모지
        def get_emoji(change_rate):
          return "red_full_circle" if change_rate >= 0 else "blue_full_circle"

        # Block Kit 포맷팅 with SlackMessageBuilder
        builder = SlackMessageBuilder()
        builder.add_line(
            text=f"{df.index[-1].strftime('%Y-%m-%d')} {stock_name} ({stock_code}) 주가 정보",
            bold=True
        ).add_line(
            text=f" 종가 {close_price:,} {close_change_rate:+.2f}%",
            emoji=get_emoji(close_change_rate)
        ).add_line(
            text=f" 시가 {open_price:,} {open_change_rate:+.2f}%",
            emoji=get_emoji(open_change_rate)
        ).add_line(
            text=f" 고가 {high_price:,} {high_change_rate:+.2f}%",
            emoji=get_emoji(high_change_rate)
        ).add_line(
            text=f" 저가 {low_price:,} {low_change_rate:+.2f}%",
            emoji=get_emoji(low_change_rate)
        ).add_line(
            text=f" 거래량 {volume:,} {volume_change_rate:+.2f}%",
            emoji=get_emoji(volume_change_rate)
        )

        return {"response_type": "in_channel", "blocks": builder.build()}

      except Exception as e:
        print(f"주가 정보 조회 오류: {e}")
        builder = SlackMessageBuilder()
        builder.add_line(
            text=f" {stock_name} ({stock_code}) 주가 정보 조회 실패: 거래 중단 또는 데이터 없음",
            emoji="red_x"
        )
        return {"response_type": "ephemeral", "blocks": builder.build()}

    except Exception as e:
      print(f"종목 조회 오류: {e}")
      builder = SlackMessageBuilder()
      builder.add_line(
          text=f"오류 발생: {str(e)[:50]}...",
          emoji="red_x"
      )
      return {"response_type": "ephemeral", "blocks": builder.build()}

# 봇 인스턴스 생성
stock_bot = LightStockBot()

@slack_app.command("/stock")
def handle_stock_slash_command(ack, respond, command):
  """슬래시 커맨드 '/stock 종목명 또는 종목코드' 처리"""
  ack()  # 명령어 수신 확인

  # 입력 파싱
  stock_input = command['text'].strip()

  if not stock_input:
    builder = SlackMessageBuilder()
    with builder.line() as line:
      line \
        .emoji("book") \
        .space() \
        .text("/stock [종목명 또는 종목코드]", code=True) \
        .space() \
        .text("(예:") \
        .space() \
        .text("/stock 삼성전자", code=True) \
        .space() \
        .text("또는") \
        .space() \
        .text("/stock 005930", code=True) \
        .text(")") \

    respond({"response_type": "ephemeral", "blocks": builder.build()})
    return

  # 주식 정보 조회
  result = stock_bot.get_stock_info(stock_input)
  respond(result)

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

  # print(f"🔧 Bot Token: {bot_token[:12]}..." if bot_token else "❌ Bot Token 없음")
  # print(f"🔧 App Token: {app_token[:12]}..." if app_token else "❌ App Token 없음")

  # Slack 봇을 별도 스레드에서 실행
  bot_thread = threading.Thread(target=run_slack_bot, daemon=True)
  bot_thread.start()

  # Flask 웹서버 실행 (0.0.0.0 바인딩 - Render 요구사항)
  print(f"🚀 서버 시작: 0.0.0.0:{port}")
  flask_app.run(host="0.0.0.0", port=port, debug=False)