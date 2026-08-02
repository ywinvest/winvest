# Market Dashboard PRD

## 1. 개요 (Overview)
현재 "상대강도(RS)" 단일 메뉴로 구성된 상단 네비게이션을 **"시장(Market)"**과 **"종목(Stock)"**으로 분리하여, 전체 시장 상황을 먼저 파악한 후 개별 종목을 탐색하는 하향식(Top-down) 뷰를 제공합니다.

## 2. 주요 요구사항 (Requirements)
1. **네비게이션 개편**
   - 기존 `상대강도(RS)` 텍스트를 `종목`으로 변경하고, 좌측에 `시장` 메뉴를 추가.
   - 루트 경로(`/`) 접속 시 `/rs` 대신 `/market`으로 리다이렉트.

2. **시장 대시보드 (`/market`)**
   - `fdr.DataReader`와 기존 `market.py` 모듈을 활용하여 코스피(`KS11`)와 코스닥(`KQ11`)의 최근 100일 데이터를 조회하고 최신 신호(green, yellow, red -> 양호🟢, 주의🟡, 경고🔴)를 산출.
   - `daily_market_report.py`의 `get_market_status` 로직을 참고하여 등락률 및 신호 유지/전환 메시지 생성.
   - 해당 일자 기준으로 DB에 저장된 RS 랭킹을 조회하여 각 시장(KOSPI, KOSDAQ)별 **RS TOP 5** 종목을 추출.
   - 추출된 TOP 5 종목 중 **당일 등락률(changes_ratio)이 가장 높은 종목 1개**를 각각 선정하여 시장 신호 하단에 표시.

## 3. 세부 실행 계획 (Execution Phases)
- [ ] **Phase 1: 라우터 및 데이터 로직 구현**
  - `routes/views/dashboard.py`에 `/market` 라우트 추가 (또는 분리).
  - 루트(`/`) 리다이렉트를 `/market`으로 변경.
  - FastAPI 백엔드에서 `fdr` 조회 및 `market.py` 계산 로직, 그리고 DB에서 RS TOP 5 중 등락률 1위 종목 추출 로직 작성. (조회 속도 최적화를 위해 HTMX 비동기 로딩 혹은 백그라운드 캐싱 적용 검토)
- [ ] **Phase 2: UI 및 템플릿 구현**
  - 상단 네비게이션 메뉴(`base.html` 또는 `index.html`)에 "시장"과 "종목" 버튼 배치 및 활성화 상태(Active) 스타일 분리.
  - `/market`에 대응하는 `market.html` 템플릿 생성.
  - 템플릿 내에 코스피/코스닥 카드 위젯을 구현하여 신호와 종목 정보 표시.
- [ ] **Phase 3: 검증 (Validation)**
  - `/market` 접속 시 시장 신호가 정상적으로 표시되는지 확인.
  - 종목 메뉴 클릭 시 기존 RS 페이지가 렌더링되는지 확인.

## 4. 제약사항 및 참고 (Constraints & References)
- `fdr.DataReader`는 페이지 접속 시마다 호출하면 응답 속도 지연(콜드부팅)이 발생할 수 있으므로, HTMX로 스피너를 보여준 뒤 렌더링(`hx-get="/api/market-status"`)하는 방식을 권장합니다.
- UI는 Tailwind CSS와 Alpine.js를 활용하여 "Premium Dashboard" 형태의 깔끔한 카드(Glassmorphism 등) 뷰로 구성합니다.
