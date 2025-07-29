import io
import os
import threading
from datetime import datetime, timedelta

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

import FinanceDataReader as fdr
from flask import Flask, jsonify
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

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

def create_stock_chart(df: pd.DataFrame, stock_name: str, stock_code: str):
  """Matplotlib으로 주식 차트 이미지를 생성하고 메모리에 저장 (영문 버전)"""
  try:
    # 이동평균선 계산
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()

    plt.style.use('seaborn-v0_8-darkgrid')

    fig, ax = plt.subplots(figsize=(10, 5))

    ax.set_title(f"{stock_name} ({stock_code}) - Last 30 Days", fontsize=16)
    ax.plot(df.index, df['Close'], label='Close', color='skyblue', linewidth=2)
    ax.plot(df.index, df['MA5'], label='5-Day MA', color='green', linestyle='--', linewidth=1.5)
    ax.plot(df.index, df['MA20'], label='20-Day MA', color='orange', linestyle='--', linewidth=1.5)

    ax.legend(loc='upper left')
    ax.grid(True)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{int(x):,}'))

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    plt.close(fig)

    return buf
  except Exception as e:
    print(f"⚠️ Chart creation failed: {e}")
    return None

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

  def build_stock_info_blocks(self, df: pd.DataFrame, stock_name: str, stock_code: str):
    """SlackMessageBuilder를 사용해 상세 정보 블록 생성"""
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest

    prev_close_price = int(prev['Close'])
    prev_volume = int(prev['Volume'])

    close_price = int(latest['Close'])
    open_price = int(latest['Open'])
    high_price = int(latest['High'])
    low_price = int(latest['Low'])
    volume = int(latest['Volume'])

    close_change_rate = ((close_price - prev_close_price) / prev_close_price * 100) if prev_close_price > 0 else 0
    open_change_rate = ((open_price - prev_close_price) / prev_close_price * 100) if prev_close_price > 0 else 0
    high_change_rate = ((high_price - prev_close_price) / prev_close_price * 100) if prev_close_price > 0 else 0
    low_change_rate = ((low_price - prev_close_price) / prev_close_price * 100) if prev_close_price > 0 else 0
    volume_change_rate = ((volume - prev_volume) / prev_volume * 100) if prev_volume > 0 else 0

    def get_emoji(change_rate):
      return "red_full_circle" if change_rate >= 0 else "blue_full_circle"

    builder = SlackMessageBuilder()
    builder.add_line(
        text=f"{df.index[-1].strftime('%Y-%m-%d')} {stock_name} ({stock_code}) 상세 정보",
        bold=True
    ).add_line(
        text=f" 종가 {close_price:,} ({close_change_rate:+.2f}%)",
        emoji=get_emoji(close_change_rate)
    ).add_line(
        text=f" 시가 {open_price:,} ({open_change_rate:+.2f}%)",
        emoji=get_emoji(open_change_rate)
    ).add_line(
        text=f" 고가 {high_price:,} ({high_change_rate:+.2f}%)",
        emoji=get_emoji(high_change_rate)
    ).add_line(
        text=f" 저가 {low_price:,} ({low_change_rate:+.2f}%)",
        emoji=get_emoji(low_change_rate)
    ).add_line(
        text=f" 거래량 {volume:,} ({volume_change_rate:+.2f}%)",
        emoji=get_emoji(volume_change_rate)
    )
    return builder.build()


# 봇 인스턴스 생성
stock_bot = LightStockBot()

def process_and_send_stock_info(client: WebClient, channel_id: str, stock_input: str):
  """데이터 조회, 차트 생성, 메시지 및 파일 전송을 모두 처리하는 함수"""
  # 1. 종목 코드 찾기
  stock_code = stock_bot.find_stock_code(stock_input)
  if not stock_code:
    client.chat_postMessage(channel=channel_id, text=f"😅'{stock_input}'에 해당하는 종목을 찾을 수 없습니다.")
    return

  stock_name = next((name for name, code in stock_bot.ticker_cache.items() if code == stock_code and name != stock_code), stock_input)

  # 2. 데이터 조회
  try:
    # 차트 생성을 위해 넉넉히 45일치 데이터 조회
    end_date = datetime.now()
    start_date = end_date - timedelta(days=45)
    df = fdr.DataReader(stock_code, start=start_date, end=end_date)
    if df.empty:
      client.chat_postMessage(channel=channel_id, text=f"😅 '{stock_name}'의 주가 데이터가 없습니다.")
      return
  except Exception as e:
    client.chat_postMessage(channel=channel_id, text=f"😥 데이터 조회 중 오류가 발생했습니다: {e}")
    return

  # 3. 차트 생성
  # 최근 30일치 데이터로 차트 생성
  chart_image_buffer = create_stock_chart(df.tail(30), stock_name, stock_code)

  # 4. 상세 정보 블록 생성
  info_blocks = stock_bot.build_stock_info_blocks(df, stock_name, stock_code)

  # 5. 슬랙에 전송
  try:
    # 5-1. 차트 이미지 먼저 업로드
    upload_response = client.files_upload_v2(
        channel=channel_id,
        file=chart_image_buffer,
        filename=f"{stock_code}_chart.png",
        title=f"{stock_name} ({stock_code}) Chart",
        initial_comment=f"📈 *{stock_name}*의 최근 1개월 차트입니다."
    )

    # 5-2. 업로드된 파일 메시지에 대한 답글로 상세 정보 블록 전송
    thread_ts = upload_response['file']['ts']
    client.chat_postMessage(
        channel=channel_id,
        blocks=info_blocks,
        thread_ts=thread_ts # 스레드에 메시지 달기
    )
  except Exception as e:
    print(f"Slack 메시지 전송 실패: {e}")
    client.chat_postMessage(channel=channel_id, text=f"😥 슬랙 메시지 전송 중 오류가 발생했습니다: {e}")

@slack_app.command("/stock")
def handle_stock_slash_command(ack, respond, command, client):
  """슬래시 커맨드 '/stock' 처리 (차트 포함)"""
  ack()

  stock_input = command.get('text', '').strip()
  channel_id = command['channel_id']

  if not stock_input:
    respond(text="종목명을 입력해주세요. (예: `/stock 삼성전자`)", response_type="ephemeral")
    return

  # 사용자에게 작업이 시작되었음을 알림 (3초 타임아웃 방지)
  respond(text=f"`{stock_input}` 정보를 조회하고 차트를 만들고 있어요... 잠시만 기다려주세요!", response_type="ephemeral")

  # 실제 작업은 별도 스레드에서 실행
  task_thread = threading.Thread(
      target=process_and_send_stock_info,
      args=(client, channel_id, stock_input)
  )
  task_thread.start()

# --- 기존 코드와 동일한 부분 시작 ---

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

if __name__ == "__main__":
  port = int(os.environ.get("PORT", 10000))
  bot_thread = threading.Thread(target=run_slack_bot, daemon=True)
  bot_thread.start()
  print(f"🚀 서버 시작: 0.0.0.0:{port}")
  flask_app.run(host="0.0.0.0", port=port, debug=False)