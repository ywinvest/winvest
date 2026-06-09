# PRD: Woo 퀀트 트레이딩 전략 (Woo Quantitative Trading Strategies)

## Document Status
- Status: Complete (코드 기반 역공학 완료)
- File Mode: Single
- Current Phase: Complete
- Last Updated: 2026-05-30
- PRD File: `tasks/prd-woo-strategies.md`

## Problem
투자자들은 한국 주식 시장(KOSPI, KOSDAQ)에서 주가 상승 돌파 기회를 식별하기 위해 체계적이고 데이터 중심적인 방법이 필요합니다. 수동 분석은 시간이 많이 소요되고 감정적 편향에 노출되기 쉽습니다. 매일 전체 종목을 스캔하고, 트레이딩 전략을 백테스트하며, 슬랙을 통해 실전 매수/매도 시그널 알림을 제공하는 퀀트 파이프라인이 필요합니다.

## Goals
- G-1: 거래량 급증 및 이동평균선 골든크로스에 초점을 맞춘 단기 돌파 전략(`woo1`) 구현.
- G-2: 52주 신고가 갱신 및 장기 이동평균선 정배열 추세 추종에 초점을 맞춘 전략(`woo2`) 구현.
- G-3: 두 전략의 과거 성과를 평가하기 위한 강력한 백테스팅 모듈(`woo1_backtest`, `woo2_backtest`) 제공.
- G-4: 매일 자동으로 스크립트를 실행하여 슬랙(Slack) 채널로 매수/매도 후보 종목을 전달.

## Discovery Summary
- Reviewed: `woo1.py`, `woo2.py`, `woo1_backtest.py`, `woo2_backtest.py`.
- Current system: 
  - `FinanceDataReader`와 `pykrx`를 사용하여 KOSPI/KOSDAQ 주가 데이터를 수집.
  - `concurrent.futures.ThreadPoolExecutor`를 통한 멀티 스레딩 병렬 처리 구현.
  - Pandas-TA를 이용해 MA(5, 10, 20, 60, 120, 240), RSI, ADX, DI, ATR, Relative Strength (RS) 등 기술적 지표 계산.
  - `slack_utils.py`를 통해 슬랙 연동 및 `krx_auth.py`를 통해 KRX 세션 인증 처리.

## Requirements
### Functional Requirements
#### Strategy 1 (`woo1`)
- FR-1: 다음 매수 조건을 충족하는 종목 스크리닝: 종가 <= 52주 최저가 * 1.3, 고가 등락률 >= 8%, 거래량 증감률 > 300%, 종가 > 20일 이동평균선.
- FR-2: ETF, ETN, 리츠, 스팩(SPAC), 선박펀드 및 우선주 등 제외.
- FR-3: 매수 후보 종목을 '위꼬리' 길이에 따라 분류하여 슬랙으로 알림 전송.
- FR-4: 백테스트(`woo1_backtest`)에서 고정 목표 수익률(예: +8.2%) 도달 시 매도하거나 종가가 20일 이동평균선을 하향 이탈할 경우 손절매하는 로직 평가.

#### Strategy 2 (`woo2`)
- FR-5: 52주 신고가를 돌파하는 종목 스크리닝 (`First_52WeekHigh_Break`).
- FR-6: 모든 장기 이동평균선(20, 60, 120, 240)이 상승 추세(기울기 > 0)에 있는지 확인.
- FR-7: 트레일링 스탑, 거래량 실린 장대 음봉 낙폭(오닐식 청산), 추세 붕괴 확정 등 다양한 조건을 사용해 매도 시점 평가.
- FR-8: 매일 발생하는 매수 및 매도 후보 종목을 시장 심리 지표(ADX, DI, 이동평균선 추세) 주석과 함께 슬랙으로 전송.

### Non-Functional Requirements
- NFR-1: 성능: 합리적인 시간 내에 3000개 이상의 종목을 스캔하기 위해 병렬 처리(`ThreadPoolExecutor`)를 반드시 사용.
- NFR-2: 안정성: API 호출 제한(Rate limits) 및 KRX 세션 인증을 안정적으로 처리.

## Architecture & Data Flow
1. **Data Ingestion**: `krx_data.get_pykrx_market_listing`을 통해 모든 티커 심볼 수집.
2. **Parallel Processing**: `parallel_process_stocks`를 사용해 전체 목록을 10개의 워커 스레드로 분할 처리.
3. **Indicator Calculation**: `calculate_indicators` 함수로 Pandas-TA 기반의 기술적 지표 일괄 계산.
4. **Signal Generation**: `buy_condition` (및 백테스트 매도 로직)으로 전체 데이터프레임 필터링.
5. **Notification**: `send_to_slack`을 통해 이모지와 순위 정보가 포함된 페이로드 포맷팅 및 알림 전송.

## Backtesting Logic
- 매수일, 매수가, 매도일, 매도가, 보유 일수(Holding Days), 그리고 수익률(Return %)을 기록하여 실제 트레이딩 환경을 시뮬레이션.
- 전략 2(`woo2`)의 경우 리스크 팩터(`BASE_RISK = 0.08`, `TRADING_FEE = 0.002`)를 기반으로 한 부분 매도(절반/전량) 로직을 통합하여 테스트.
