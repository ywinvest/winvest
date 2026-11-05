# PRD: 수정주가 기준 52주 신고가 및 역사적 신고가 지표 도입 (52-Week & All-Time High Indicators)

## Document Status
- Status: Complete
- File Mode: Single
- Current Phase: Complete
- Last Updated: 2026-11-05
- PRD File: `tasks/prd-new-high-indicator.md`
- Purpose: 수정주가 기준 52주 신고가 및 역사적 신고가 지표의 수집·저장·조회·UI 표시를 위한 실행 진실 공급원(Living PRD). 구현 진행에 따라 체크박스를 갱신하고 하위 페이즈를 업데이트한다.

## Problem
현재 Winvest(`stockspace`)는 종목별 상대강도(RS) 및 이동평균선(MA5~MA240) 지표를 수정주가 기준으로 계산하여 Tinybird(`krx_daily_adjusted_stocks`)에 저장하고 있으나, 모멘텀 투자의 핵심 돌파 지표인 **52주 신고가(52-Week High)**와 **역사적 신고가(All-Time High)** 데이터가 부재합니다.
이로 인해 사용자는 RS 상위 종목이 현재 전고점을 돌파한 신고가 종목인지, 혹은 고점 대비 얼마나 밀려 있는지(괴리율)를 대시보드나 종목 상세 드로어에서 즉시 파악하거나 필터링할 수 없습니다.

## Goals
- G-1: FinanceDataReader(FDR) 전체 기간 수정주가 이력을 바탕으로 **전일(D-1) 고가(`High`) 기준 52주(364D) 최고가(`prev_high_52w`)** 및 **역사적 최고가(`prev_high_all_time`)**를 계산하여 Tinybird `krx_daily_adjusted_stocks` 데이터소스에 저장한다.
- G-2: **당일 종가(`close`)와 전일 기준 최고가(`prev_high_52w`, `prev_high_all_time`)를 비교**하여 장중 윗꼬리(Fakeout)를 배제한 종가 기준 52주 신고가 및 역사적 신고가 초과 돌파 여부를 판별한다 (`close > prev_high_all_time > 0`, `close > prev_high_52w > 0`).
- G-3: 웹 UI 전반(RS 테이블 배지, RS 대시보드 상단 '신고가' 필터, 종목 상세 드로어의 최고가·괴리율 표시, 시장 대시보드 RS Top 5 카드 배지)에 신고가 정보를 직관적으로 표시한다.

## Non-Goals
- NG-1: 장중 실시간(Intraday) 틱/분봉 기반 실시간 신고가 알림 기능 (일일 마감 배치 기준 유지).
- NG-2: 차트 위젯 내 신고가 수평선 오버레이 렌더링 (차트 연동 PRD에서 별도 다룸).

## Success Criteria
- SC-1: 일일 수집(`ingest_daily_krx_adjusted_stocks.py`), 벌크 수집(`ingest_bulk_krx_adjusted_stocks.py`), 괴리 백필(`backfill_krx_adjusted_stocks.py`) 실행 시 모든 종목의 `high_52w`, `high_all_time`이 `int32` 타입으로 정확히 산출·적재된다.
- SC-2: RS 대시보드(`/rs`) 테이블에서 역사적 신고가(`역사적 신고가` 또는 `ATH`) 및 52주 신고가(`52주 신고가` 또는 `52W`) 배지가 종목명 옆에 구분 표시되며, 역사적 신고가 달성 종목은 중복 배지 없이 상위 개념인 '역사적 신고가'가 우선 표시된다.
- SC-3: RS 대시보드 상단 필터 바에서 `신고가` 필터(`전체 신고가` / `52주 신고가` / `역사적 신고가`)를 선택하면 클라이언트 사이드 필터링과 종목 수 카운트가 즉시 반영된다.
- SC-4: 종목 상세 드로어(`rs_drawer.html`)에서 52주 최고가, 역사적 최고가 및 당일 종가 기준 고점 대비 괴리율/돌파율(%)이 표시된다.
- SC-5: 시장 대시보드(`/`)의 KOSPI/KOSDAQ RS Top 5 종목 리스트에서도 신고가 달성 종목에 배지가 표시된다.

## Key Scenarios
### Scenario 1: RS 대시보드에서 신고가 돌파 주도주 필터링
- Actor: 모멘텀 투자자
- Trigger: `/rs` 페이지 접속 후 상단 필터 바에서 `신고가` 버튼을 클릭하고 `역사적 신고가` 또는 `52주 신고가` 칩을 선택.
- Expected outcome: 페이지 새로고침 없이 조건을 만족하는 신고가 돌파 종목만 즉시 필터링되고, 검색창 내부에 선택된 필터 칩이 표시된다.

### Scenario 2: 종목 상세 드로어에서 최고가 및 괴리율 확인
- Actor: 사용자
- Trigger: RS 테이블에서 특정 종목 행(Row)을 클릭하여 상세 드로어를 오픈.
- Expected outcome: 드로어 헤더 또는 지표 그리드에 신고가 달성 배지와 함께 `52주 최고가`, `역사적 최고가`, 그리고 현재 종가의 최고가 대비 괴리율/돌파율(`+3.2% 돌파` 또는 `-4.5%`)이 표시된다.

### Scenario 3: 액면분할/무상증자 종목의 수정주가 신고가 재산정
- Actor: 자동화 배치 워크플로우 (`daily_update.yml` / `ingest-bulk-krx.yml`)
- Trigger: 권리락/액면분할 발생 또는 주간 벌크 리컨실리에이션 실행.
- Expected outcome: FDR에서 상장 이래 전체 수정주가 이력을 다시 불러와 수정된 과거 고가 기준으로 `high_52w`, `high_all_time`이 왜곡 없이 재계산된다.

## Discovery Summary
- Reviewed:
  - 데이터 수집/백필: `scripts/ingest_daily_krx_adjusted_stocks.py`, `scripts/ingest_bulk_krx_adjusted_stocks.py`, `scripts/backfill_krx_adjusted_stocks.py`, `rs.py`
  - Tinybird 정의: `tinybird/datasources/krx_daily_adjusted_stocks.py`, `tinybird/pipes/all_rs_stocks.py`, `tinybird/pipes/top_rs_stocks.py`
  - 백엔드/프론트엔드: `app/models.py`, `app/crud/rs.py`, `app/crud/market.py`, `app/templates/pages/rs.html`, `app/templates/partials/table.html`, `app/templates/partials/rs_drawer.html`, `app/templates/partials/market_status.html`
- Current system:
  - 현재 `krx_daily_stocks`(원시 주가)와 `krx_daily_indices`(시장 지수)는 벌크 스크립트 기준 `2014-01-01`부터 수집 중이나, `krx_daily_adjusted_stocks`(수정주가)는 벌크 스크립트 기본값이 `2024-01-01`이며 일일 수집 스크립트는 최근 `400일(약 270거래일)`만 FDR에서 조회하고 있음.
  - FDR(`fdr.DataReader(code)`)은 시작일을 생략하면 네이버 금융 차트 API를 통해 약 3,000거래일(약 2014년~현재, 상장일 이후 전체) 수정주가를 단일 HTTP 요청으로 반환함.
- Validation surface:
  - 스크립트 `--dry-run` 실행을 통한 DataFrame 스키마 및 지표 값 검증.
  - Tinybird CLI / SDK 동기화 및 로컬 FastAPI 서버(`fastapi dev app/main.py`) 구동 후 브라우저/Playwright 검증.
- Design implications:
  1. **전일 고가 기준 최고가 저장 + 당일 종가 비교 아키텍처**:
     - 당일 고가(`High`)를 포함한 최고가를 저장하고 당일 종가(`Close`)와 비교하면, 윗꼬리가 단 1틱이라도 달린 날에는 `Close < High`가 되어 신고가 달성을 판별할 수 없는 자기 참조 모순이 발생함.
     - 반면 **전일(D-1)까지의 고가(`High.shift(1)`) 기준 52주 최고가(`high_52w`) 및 역사적 최고가(`high_all_time`)**를 저장하고 이를 **당일 종가(`close`)**와 비교(`close >= high_52w`)하면, 별도의 Boolean 컬럼 없이 정수형(`int32`) 컬럼 2개만으로 ① 종가 기준 진성 신고가 돌파 여부, ② 직전 저항선(전고점) 가격, ③ 전고점 대비 돌파율/괴리율(%)을 모두 정확하게 도출할 수 있음.
  2. **FDR 전체 기간 조회 + Tinybird 타겟 기간 적재 분리**:
     - FDR 조회 시에는 시작일 제한 없이 전체 수정주가 이력을 가져와 `high_all_time`과 `high_52w`를 정확히 계산하고, Tinybird 업로드 시에만 `target_date`(일일 수집) 또는 `start_date`(벌크 수집, 기본 `2024-01-01`)로 슬라이싱하여 적재 비용과 응답 속도를 최적화함.

## Requirements
### Functional Requirements
- FR-1: 수정주가 수집/백필 스크립트에서 종목별 시계열 DataFrame(`DatetimeIndex`)에 대해 전일 고가(`High.shift(1)`) 기준 52주(`364D`) 롤링 최고가(`Prev_High_52W`)와 누적 최고가(`Prev_High_All_Time`)를 벡터화 연산으로 계산해야 한다 (`rs.py`는 순수 RS 계산 전용으로 유지).
  - `df["Prev_High_52W"] = df["High"].shift(1).rolling(window="364D", min_periods=1).max()`
  - `df["Prev_High_All_Time"] = df["High"].shift(1).cummax()`
- FR-2: `ingest_daily_krx_adjusted_stocks.py`, `ingest_bulk_krx_adjusted_stocks.py`, `backfill_krx_adjusted_stocks.py`는 FDR 호출 시 시작일 제한 없이 전체 수정주가 이력을 조회하여 `prev_high_52w`와 `prev_high_all_time`을 산출한 뒤, 적재 대상 날짜 범위만 필터링하여 Tinybird에 업로드해야 한다.
- FR-3: Tinybird `krx_daily_adjusted_stocks` 데이터소스 및 `app/models.py`(`KrxDailyAdjustedStock`)에 `prev_high_52w: int32`, `prev_high_all_time: int32` 필드를 추가하고, Tinybird Pipe(`all_rs_stocks`, `top_rs_stocks`) 출력 컬럼에 포함해야 한다.
- FR-4: `app/crud/rs.py` 및 `app/crud/market.py`에서 각 종목에 대해 다음 파생 필드를 계산하여 템플릿에 전달해야 한다:
  - `is_all_time_high`: `prev_high_all_time > 0 and close > prev_high_all_time`
  - `is_52w_high`: `prev_high_52w > 0 and close > prev_high_52w`
  - `pct_from_52w_high`: `((close - prev_high_52w) / prev_high_52w * 100)` (`prev_high_52w > 0`일 때)
  - `pct_from_all_time_high`: `((close - prev_high_all_time) / prev_high_all_time * 100)` (`prev_high_all_time > 0`일 때)
- FR-5: RS 테이블(`table.html`)과 시장 대시보드 Top 5(`market_status.html`)에서 종목명 옆에 신고가 배지를 표시해야 한다.
  - `is_all_time_high == True`: **역사적 신고가** 배지 (`역사적` 또는 `ATH`, 강조 색상 예: `badge-error` / `badge-warning`) 표시 (52주 신고가 배지와 중복 표시하지 않음).
  - `is_all_time_high == False` 이고 `is_52w_high == True`: **52주 신고가** 배지 (`52주` 또는 `52W`, 예: `badge-secondary` / `badge-accent`) 표시.
- FR-6: RS 페이지(`rs.html`) 상단 필터 툴바(`facetFilters`)에 `신고가` 필터 드롭다운/패널을 추가하여 `52주 신고가 이상`(`52w`: 52주 신고가 및 역사적 신고가 모두 포함) 및 `역사적 신고가`(`all_time`: 역사적 신고가만 포함) 필터링을 지원해야 한다.
- FR-7: 종목 상세 드로어(`rs_drawer.html`)에 `52주 최고가(전일 기준)` 및 `역사적 최고가(전일 기준)` 가격과 현재 종가의 대비율(`+X.XX%` 돌파 또는 `-X.XX%`)을 표시해야 한다.

### Non-Functional Requirements
- NFR-1: 모든 지표 계산은 `df.iterrows()` 없이 Pandas 벡터화 연산(`shift`, `rolling`, `cummax`)만 사용해야 한다.
- NFR-2: 일일 수집 스크립트가 전체 기간 FDR 데이터를 조회하더라도 `ThreadPoolExecutor` 병렬 처리를 통해 기존과 유사한 실행 시간(수십 초 이내) 내에 완료되어야 한다.
- NFR-3: UI 배지 및 드로어 컴포넌트는 DaisyUI v5 시맨틱 클래스와 Tailwind CSS v4를 사용하여 Light/Dark 모드 모두에서 높은 가독성과 대비를 유지해야 한다.

## Assumptions
- A-1: **지표 필드 네이밍 컨벤션 (Project Standard)**:
  - **봉(Bar) 개수 기준 기술적 지표 (`<indicator><bars>`)**: 기간 단위가 없는 캔들(봉) 개수 기준 지표는 언더스코어 없이 숫자를 붙여 표기한다 (예: `ma5`, `ma20`, `ma240`, 향후 확장 시 `rsi14`, `atr22` 등).
  - **달력 기간(Period) 또는 수식어 기준 지표 (`<metric>_<period>`)**: `1m`, `52w`, `all_time`처럼 시간 단위나 단어가 결합되는 지표는 언더스코어(`_`)로 구분하며, 문법 제약(Python/SQL/JS에서 숫자로 시작하는 식별자 불가)을 피하기 위해 지표명을 접두사로 둔다 (예: `rs_1m`, `rs_12m`, **`high_52w`**, **`high_all_time`**).
  - **돌파 여부 Boolean 플래그 (`is_<condition>`)**: CRUD 및 템플릿에서 사용하는 판별 플래그는 **`is_52w_high`**, **`is_all_time_high`**로 명명한다.
- A-2: 52주 최고가의 롤링 윈도우는 `woo2.py`의 `Pre52WeekHigh` 구현과 동일하게 달력 기준 52주(`window="364D"`, `52 * 7 = 364일`)로 정의한다.
- A-3: 신규 상장 첫 거래일(IPO 당일)에는 직전 거래일 데이터가 없으므로 `high_52w = 0`, `high_all_time = 0`이 되며, `high > 0` 조건을 통해 상장 첫날 모든 종목이 무조건 신고가로 분류되는 것을 방지한다.
- A-4: 드로어에 표시되는 최고가 수치는 돌파 기준이 되는 전일 기준 최고가(`high_52w`, `high_all_time`)를 기본으로 하되, 고점 대비 등락률(`pct_from_52w_high`, `pct_from_all_time_high`)을 함께 병기하여 돌파 시 `+X.XX%`, 미돌파 시 `-X.XX%`로 직관적으로 이해할 수 있게 한다.

## Dependencies / Constraints
- Tinybird 스키마 변경 시 기존 `krx_daily_adjusted_stocks` 데이터소스에 컬럼 추가 배포 및 전체 벌크 재적재(`ingest_bulk_krx_adjusted_stocks.py`)가 선행되어야 파이프에서 신규 컬럼 조회가 가능하다.
- HTMX + Alpine.js 아키텍처 원칙에 따라, `/rs` 테이블의 신고가 필터링은 서버 재요청 없이 이미 로드된 `<template id="all-rows-template">`의 `data-is_52w_high`, `data-is_all_time_high` 속성을 이용해 클라이언트 사이드에서 즉시 수행한다.

## Risks / Edge Cases
- **신규 상장주(252거래일 미만)**: `rolling(window=252, min_periods=1)`을 사용하여 상장 후 252거래일이 지나지 않은 종목도 상장 이후 전일까지의 최고가를 `high_52w`로 산출한다 (이 경우 `high_52w == high_all_time`).
- **거래정지 및 가격 괴리(액면분할/감자)**: `backfill_krx_adjusted_stocks.py`에서도 동일하게 전체 기간 FDR 데이터를 기반으로 `high_52w`, `high_all_time`을 재계산하도록 동기화하여 수정주가 변경 시 과거 최고가가 함께 보정되도록 보장한다.

## Execution Rules
- Complete phases in order unless this PRD is explicitly revised.
- Before starting any phase, read this PRD and inspect the listed files in the Phase Discovery Gate.
- Use this PRD file as the only active plan; check off items (`- [x]`) as work progresses.
- At the end of each phase, update this PRD and revise future phases if discoveries change the plan.

## Phase Index
| Phase | Status | Objective | Validation Focus | File |
|---|---|---|---|---|
| Phase 1: 데이터 파이프라인 및 Tinybird 스키마 확장 | Complete | `high_52w`, `high_all_time` 계산 로직 및 Tinybird 데이터소스/수집 스크립트 반영 | Script `--dry-run` & Unit Check | `tasks/prd-new-high-indicator.md` |
| Phase 2: Tinybird Pipe 및 FastAPI CRUD 연동 | Complete | `all_rs_stocks`, `top_rs_stocks` 파이프 확장 및 `crud/rs.py`, `crud/market.py` 가공 로직 추가 | Pipe & API Response Check | `tasks/prd-new-high-indicator.md` |
| Phase 3: 프론트엔드 UI 배지·필터·드로어 구현 | Complete | RS 테이블/시장 대시보드 배지, RS 신고가 필터, 상세 드로어 최고가·괴리율 표시 | Browser UI (Light/Dark, Mobile/Desktop) | `tasks/prd-new-high-indicator.md` |

## Phase Plan

### Phase 1: 데이터 파이프라인 및 Tinybird 스키마 확장
Parent PRD: [PRD: 수정주가 기준 52주 신고가 및 역사적 신고가 지표 도입](./prd-new-high-indicator.md)
Status: Complete
Last Updated: 2026-11-05

#### Objective
전일 고가 기준 52주 최고가(`high_52w`) 및 역사적 최고가(`high_all_time`) 계산 로직을 구현하고, Tinybird `krx_daily_adjusted_stocks` 스키마와 3종의 수집/백필 스크립트(`ingest_daily_krx_adjusted_stocks.py`, `ingest_bulk_krx_adjusted_stocks.py`, `backfill_krx_adjusted_stocks.py`)를 업데이트한다.

#### Context From Master PRD
- Goals covered: G-1, G-2
- Success Criteria: SC-1
- Requirements covered: FR-1, FR-2, FR-3, NFR-1, NFR-2
- Key scenarios touched: Scenario 3

#### Phase Discovery Gate
Before editing code, re-check:
- [x] Relevant code/files: `rs.py`, `tinybird/datasources/krx_daily_adjusted_stocks.py`, `app/models.py`, `scripts/ingest_daily_krx_adjusted_stocks.py`, `scripts/ingest_bulk_krx_adjusted_stocks.py`, `scripts/backfill_krx_adjusted_stocks.py`
- [x] Relevant skills: `.agents/skills/tinybird-python-sdk-guidelines/SKILL.md`, `.agents/skills/tinybird-best-practices/SKILL.md`
- [x] Assumptions from the master PRD still hold

#### Scope
##### In Scope
- `rs.py`의 `calculate_indicators(df)`(또는 별도 헬퍼)에 `High_52W`, `High_All_Time` 계산 추가.
- `tinybird/datasources/krx_daily_adjusted_stocks.py` 및 `app/models.py`에 `high_52w`, `high_all_time` 컬럼 정의 추가.
- 일일/벌크/백필 스크립트에서 FDR 전체 이력 조회 및 `format_for_tinybird`의 `int32_columns`, `final_cols`에 `high_52w`, `high_all_time` 반영.

##### Out of Scope
- Tinybird Pipe SQL 및 FastAPI 웹 템플릿 수정 (Phase 2, 3에서 수행).

#### Implementation Checklist
- [x] `rs.py`는 순수 상대강도(RS) 계산 전용 모듈로 유지하고, 이동평균선(`MA5~MA240`)이 계산되는 수집/백필 스크립트 내 지표 계산부에 `woo2.py` 방식의 `High_52W`(`rolling(window="364D", min_periods=1).max()`) 및 `High_All_Time`(`cummax()`) 벡터화 계산 로직 추가.
- [x] `tinybird/datasources/krx_daily_adjusted_stocks.py` 스키마에 `"high_52w": t.int32()`, `"high_all_time": t.int32()` 추가.
- [x] `app/models.py`의 `KrxDailyAdjustedStock` 모델에 `high_52w: int = 0`, `high_all_time: int = 0` 필드 추가.
- [x] `scripts/ingest_daily_krx_adjusted_stocks.py`에서 `fdr.DataReader(code)` 호출 시 400일 제한을 제거하여 전체 수정주가 이력을 조회하도록 수정하고, `format_for_tinybird`에 `high_52w`, `high_all_time`(`int32`) 매핑 추가.
- [x] `scripts/ingest_bulk_krx_adjusted_stocks.py`의 `process_single_stock`에서 전체 수정주가 이력을 먼저 조회하여 지표(`MA*`, `Return_*`, `High_52W`, `High_All_Time`)를 산출한 뒤 `start_date` 이후 행만 필터링하도록 수정하고, `format_for_tinybird`에 `high_52w`, `high_all_time` 매핑 추가.
- [x] `scripts/backfill_krx_adjusted_stocks.py`의 `backfill_ticker_history`에서 전체 수정주가 이력을 조회하여 지표를 계산한 뒤 `effective_start` 이후 행을 필터링하도록 수정하고, `format_for_tinybird`에 `high_52w`, `high_all_time` 매핑 추가.

#### Validation Strategy
단위 데이터프레임 검증 및 각 수집 스크립트의 `--dry-run` 모드를 실행하여 `high_52w`, `high_all_time` 컬럼 타입(`int32`), 결측치 처리(`0`), 상장 첫날 및 돌파 종목의 수치가 정확한지 확인한다.

#### Validation Checklist
- [x] `python scripts/ingest_daily_krx_adjusted_stocks.py --dry-run` 실행 시 `high_52w`, `high_all_time`이 포함된 DataFrame이 오류 없이 생성되는지 확인.
- [x] `python scripts/backfill_krx_adjusted_stocks.py --dry-run` 실행 확인.
- [x] Tinybird 데이터소스 변경사항 배포 및 벌크 적재(`ingest_bulk_krx_adjusted_stocks.py`) 검증.

#### Exit Criteria
- [x] Phase objective is satisfied
- [x] Requirements FR-1, FR-2, FR-3 (datasource part) are implemented
- [x] Validation checklist is complete
- [x] No known blocker remains for Phase 2

#### Phase-End Multi-Pass Review
- [x] 1. Intent/coverage review
- [x] 2. Correctness review (특히 `shift(1)` 누락 여부, IPO 첫날 `NaN -> 0` 캐스팅 확인)
- [x] 3. Simplicity review
- [x] 4. Code quality review
- [x] 5. Duplication/cleanup review
- [x] 6. Security/privacy review
- [x] 7. Performance/load review (FDR 전체 기간 조회 시 실행 시간 확인)
- [x] 8. Validation review
- [x] 9. Future-phase review
- [x] 10. PRD sync review

---

### Phase 2: Tinybird Pipe 및 FastAPI CRUD 연동
Parent PRD: [PRD: 수정주가 기준 52주 신고가 및 역사적 신고가 지표 도입](./prd-new-high-indicator.md)
Status: Complete
Last Updated: 2026-11-05

#### Objective
Tinybird 엔드포인트 파이프(`all_rs_stocks`, `top_rs_stocks`)에서 `high_52w`, `high_all_time`을 조회하도록 확장하고, `app/crud/rs.py`와 `app/crud/market.py`에서 신고가 달성 여부 및 고점 대비 괴리율을 계산하여 반환한다.

#### Context From Master PRD
- Goals covered: G-2
- Success Criteria: SC-2, SC-4, SC-5 기반 데이터 제공
- Requirements covered: FR-3, FR-4
- Key scenarios touched: Scenario 1, Scenario 2

#### Phase Discovery Gate
Before editing code, re-check:
- [x] Relevant code/files: `tinybird/pipes/all_rs_stocks.py`, `tinybird/pipes/top_rs_stocks.py`, `app/crud/rs.py`, `app/crud/market.py`
- [x] Relevant skills: `.agents/skills/fastapi/SKILL.md`, `.agents/skills/tinybird-python-sdk-guidelines/SKILL.md`
- [x] Assumptions from the master PRD still hold

#### Scope
##### In Scope
- `tinybird/pipes/all_rs_stocks.py` 및 `tinybird/pipes/top_rs_stocks.py`의 SQL `SELECT` 절과 `output` 스키마에 `i.high_52w`, `i.high_all_time` 추가.
- `app/crud/rs.py`의 `get_rs_table_data`에 `high_52w`, `high_all_time`, `is_52w_high`, `is_all_time_high`, `pct_from_52w_high`, `pct_from_all_time_high` 계산 추가.
- `app/crud/market.py`의 `_fetch_market_top5_rs` 및 Mock 데이터에 `is_52w_high`, `is_all_time_high` 필드 추가.

##### Out of Scope
- HTML/Jinja2 템플릿 및 Alpine.js 프론트엔드 수정 (Phase 3에서 수행).

#### Implementation Checklist
- [x] `tinybird/pipes/all_rs_stocks.py`의 SQL 쿼리 및 `output` 정의에 `high_52w: t.int32()`, `high_all_time: t.int32()` 추가.
- [x] `tinybird/pipes/top_rs_stocks.py`의 SQL 쿼리 및 `output` 정의에 `high_52w: t.int32()`, `high_all_time: t.int32()` 추가.
- [x] `app/crud/rs.py`에서 `close`, `high_52w`, `high_all_time`을 비교하여 `is_52w_high`, `is_all_time_high`, `pct_from_52w_high`, `pct_from_all_time_high`를 계산하도록 업데이트.
- [x] `app/crud/market.py`의 `_fetch_market_top5_rs`에서 `is_52w_high`, `is_all_time_high`를 계산하여 반환 리스트에 추가.

#### Validation Strategy
Tinybird 파이프 배포 후 `get_rs_table_data()`와 `get_market_dashboard_data()`를 호출하여 반환 딕셔너리에 신고가 관련 필드가 정확한 타입과 값으로 포함되는지 확인한다.

#### Validation Checklist
- [x] `tinybird/pipes/all_rs_stocks.py` 및 `top_rs_stocks.py` 문법 및 스키마 검증.
- [x] `app/crud/rs.py`의 `high_52w == 0` 방어 로직(ZeroDivisionError 방지 및 상장 첫날 False 처리) 검증.
- [x] API 엔드포인트(`/api/stock/rs-table`, `/api/market-status`) 응답 정상 동작 확인.

#### Exit Criteria
- [x] Phase objective is satisfied
- [x] Requirements FR-3, FR-4 are implemented
- [x] Validation checklist is complete
- [x] No known blocker remains for Phase 3

#### Phase-End Multi-Pass Review
- [x] 1. Intent/coverage review
- [x] 2. Correctness review (ZeroDivisionError 및 `None` 값 방어 확인)
- [x] 3. Simplicity review
- [x] 4. Code quality review
- [x] 5. Duplication/cleanup review
- [x] 6. Security/privacy review
- [x] 7. Performance/load review
- [x] 8. Validation review
- [x] 9. Future-phase review
- [x] 10. PRD sync review

---

### Phase 3: 프론트엔드 UI 배지·필터·드로어 구현
Parent PRD: [PRD: 수정주가 기준 52주 신고가 및 역사적 신고가 지표 도입](./prd-new-high-indicator.md)
Status: Complete
Last Updated: 2026-11-05

#### Objective
RS 대시보드 테이블(`table.html`), RS 상단 필터 툴바(`rs.html`), 종목 상세 드로어(`rs_drawer.html`), 시장 대시보드 Top 5(`market_status.html`)에 52주 신고가 및 역사적 신고가 UI를 구현한다.

#### Context From Master PRD
- Goals covered: G-3
- Success Criteria: SC-2, SC-3, SC-4, SC-5
- Requirements covered: FR-5, FR-6, FR-7, NFR-3
- Key scenarios touched: Scenario 1, Scenario 2

#### Phase Discovery Gate
Before editing code, re-check:
- [x] Relevant code/files: `app/templates/partials/table.html`, `app/templates/pages/rs.html`, `app/templates/partials/rs_drawer.html`, `app/templates/partials/market_status.html`
- [x] Relevant skills: `.agents/skills/daisyui/SKILL.md`, `.agents/skills/alpine/SKILL.md`, `.agents/skills/htmx/SKILL.md`, `.agents/skills/frontend-design/SKILL.md`
- [x] Assumptions from the master PRD still hold

#### Scope
##### In Scope
- `app/templates/partials/table.html`:
  - `<tr class="stock-row">`에 `data-high_52w`, `data-high_all_time`, `data-is_52w_high`, `data-is_all_time_high`, `data-pct_from_52w_high`, `data-pct_from_all_time_high` 속성 바인딩.
  - 종목명 셀 내부에 `역사적 신고가` / `52주 신고가` 배지 렌더링.
- `app/templates/pages/rs.html`:
  - 상단 툴바(`facetFilters`)에 `신고가` 필터 버튼 및 확장 패널(`52주 신고가`, `역사적 신고가` 옵션) 추가.
  - `applyFiltersAndSort()`에 신고가 필터 조건(`activeHighs`) 반영.
- `app/templates/partials/rs_drawer.html`:
  - 드로어 헤더 종목명 옆 신고가 배지 표시.
  - 드로어 지표 그리드에 `52주 최고가`(가격 및 괴리율/돌파율)와 `역사적 최고가`(가격 및 괴리율/돌파율) 카드 추가.
- `app/templates/partials/market_status.html`:
  - 데스크톱 Top 5 종목 행 및 모바일 하이라이트 카드에 신고가 배지 표시.

##### Out of Scope
- 차트 영역 수정.

#### Implementation Checklist
- [x] `app/templates/partials/table.html`의 `tr.stock-row`에 신고가 관련 `data-*` 속성을 추가하고, 종목명 옆에 배지(`is_all_time_high`일 때 `역사적 신고가`, 아닐 때 `is_52w_high`이면 `52주 신고가`) 표시.
- [x] `app/templates/pages/rs.html`의 `facetFilters` Alpine 컴포넌트에 `newHigh` 필터 배열과 `newHighOptions`(`[{ value: '52w', label: '52주 신고가' }, { value: 'all_time', label: '역사적 신고가' }]`)를 추가하고, 툴바 버튼·확장 패널·검색창 내부 선택 칩(`activeChips`)과 연동.
- [x] `app/templates/pages/rs.html`의 `applyFiltersAndSort()` 함수에서 `window.alpineFilters.newHigh` 선택 값에 따라 `row.dataset.is_52w_high === 'True'` 또는 `row.dataset.is_all_time_high === 'True'`인 행만 필터링하도록 구현.
- [x] `app/templates/partials/rs_drawer.html`에 신고가 배지 및 `52주 최고가` / `역사적 최고가` 스탯 박스(전일 기준 최고가 가격 및 종가 기준 돌파율/괴리율 `%`) 추가.
- [x] `app/templates/partials/market_status.html`의 KOSPI/KOSDAQ RS Top 5 종목 리스트(데스크톱 및 모바일 뷰)에 신고가 배지 표시.

#### Validation Strategy
로컬 FastAPI 개발 서버를 실행하고 데스크톱 및 모바일 뷰포트, Light 및 Dark 테마에서 배지 렌더링, 신고가 필터 동작, 드로어 오픈 시 최고가·괴리율 표시를 검증한다.

#### Validation Checklist
- [x] `/rs` 접속 시 테이블 종목명 옆에 `역사적 신고가` / `52주 신고가` 배지가 깨짐 없이 렌더링되는지 확인.
- [x] 상단 `신고가` 필터에서 `52주 신고가`, `역사적 신고가` 선택 및 해제 시 테이블 행과 총 종목 수가 즉시 갱신되는지 확인.
- [x] 종목 행 클릭 시 열리는 상세 드로어에 `52주 최고가`, `역사적 최고가`, 괴리율/돌파율(`%`)이 정확히 표시되는지 확인.
- [x] `/` 시장 대시보드에서 Top 5 종목에 신고가 배지가 자연스럽게 표시되는지 확인.
- [x] Light / Dark 모드 및 모바일 반응형 레이아웃 깨짐 여부 확인.

#### Exit Criteria
- [x] Phase objective is satisfied
- [x] Requirements FR-5, FR-6, FR-7, NFR-3 are implemented
- [x] Validation checklist is complete
- [x] All phases complete

#### Phase-End Multi-Pass Review
- [x] 1. Intent/coverage review
- [x] 2. Correctness review
- [x] 3. Simplicity review
- [x] 4. Code quality review
- [x] 5. Duplication/cleanup review
- [x] 6. Security/privacy review
- [x] 7. Performance/load review
- [x] 8. Validation review
- [x] 9. Future-phase review
- [x] 10. PRD sync review

## Final Multi-Pass Review After All Phases
Complete in order:
- [x] 1. Requirements coverage review: every FR, NFR, and success criterion is satisfied or explicitly deferred.
- [x] 2. Cross-phase integration review: phase outputs work together without gaps, broken assumptions, or duplicated ownership.
- [x] 3. Correctness review: happy paths, edge cases, errors, empty states, permissions, and state transitions are handled.
- [x] 4. Simplicity/refactor review: the final design is no more complex than necessary.
- [x] 5. Duplication/cleanup review: repeated logic, dead code, temporary code, noisy logs, commented leftovers, unused files, and unused dependencies are removed.
- [x] 6. Security/privacy review: auth, access control, secrets, sensitive data, auditability, and data exposure are safe.
- [x] 7. Performance/load review: bottlenecks, expensive queries, N+1 patterns, unnecessary renders, and avoidable network calls are addressed.
- [x] 8. Validation review: the final mix of unit, integration, API E2E, UI/browser, simulator, visual, manual, or observability checks is appropriate for the risk.
- [x] 9. Documentation/operability review: docs, runbooks, release notes, migrations, rollback, monitoring, or support notes are updated when needed.
- [x] 10. PRD closeout review: status is Complete, change log is current, and follow-ups are recorded.

## Open Questions
- 없음 (사용자 확인을 통해 전일 고가 기준 최고가 저장 + 당일 종가 비교 방식 및 UI 적용 범위 확정 완료).

## Change Log
- 2026-11-05: Initial PRD created (`tasks/prd-new-high-indicator.md`).
- 2026-11-05: Phase 1, 2, 3 구현 및 단위/템플릿 렌더링 검증 완료.
