# PRD: RS 대시보드 (RS Dashboard)

## Document Status
- Status: Draft
- File Mode: Single
- Current Phase: Not Started
- Last Updated: 2026-05-30
- PRD File: `tasks/prd-rs-dashboard.md`
- Purpose: RS 대시보드 MVP 구현을 위한 살아있는(Living) PRD 및 실행 진실 공급원(Source of truth).

## Problem
현재 상대강도(Relative Strength, RS) 지표는 `daily_market_report.py`를 통해 계산되어 Gemini를 위한 단순 텍스트 프롬프트로만 출력되고 있습니다. RS 값의 과거 이력을 저장하는 영구적인 데이터베이스가 없으며, 시간이 지남에 따른 주식 시장의 흐름과 RS 지표를 쉽게 모니터링할 수 있는 시각적 대시보드도 부재합니다.

## Goals
- G-1: 계산 결과를 단순 출력하는 대신, Turso(libSQL) 데이터베이스에 저장하는 파이썬 스크립트(`update_rs.py`) 구축.
- G-2: HTML 대시보드를 제공하고 HTMX를 위한 API 엔드포인트를 서빙하는 최소한의 FastAPI 백엔드 구축 (Turso DB에서 데이터 읽어오기).
- G-3: Jinja2 템플릿, HTMX, Alpine.js, Tailwind CSS(CDN)를 활용하여 RS 지표를 보여주는 반응형 데이터 테이블 프론트엔드 구축.

## Non-Goals
- NG-1: 복잡한 클라이언트 사이드 인터랙션 (예: 드래그 앤 드롭, 전체 SPA 라우팅) 구축 제외.
- NG-2: 첫 MVP 버전에서는 고급 차팅 라이브러리(Advanced charting) 사용 제외.
- NG-3: 본격적인 Cloudflare D1 및 Workers 마이그레이션 (우선 로컬 SQLite + Cloudflare Tunnel로 검증 후 점진적 도입).

## Success Criteria
- SC-1: 사용자가 `http://localhost:8000`에 접속하여 아름답게 디자인된 다크 모드 스타일의 최신 RS 지표 테이블을 볼 수 있다.
- SC-2: UI에서 "Refresh" 버튼을 클릭하면 Turso DB의 최신 랭킹을 로드하여 전체 페이지 새로고침 없이 HTMX를 통해 테이블만 매끄럽게 새로고침된다.
- SC-3: 모든 과거 RS 데이터 및 일자별 추이가 Turso DB에 안정적으로 누적 저장 및 관리되어 시계열 조회가 가능해진다.

## Discovery Summary
- Reviewed: `daily_market_report.py`, `rs.py`, `krx_auth.py`, `market.py`.
- Current system: `daily_market_report.py`는 `ThreadPoolExecutor`를 사용해 KOSPI/KOSDAQ의 RS를 계산함. ETF를 필터링하고 결과 프롬프트를 출력. `krx_auth.py`는 KRX 쿠키 처리를 위해 `requests` 모듈을 몽키 패칭함.
- Validation surface: 로컬 uvicorn 실행 및 수동 브라우저 스모크(Smoke) 테스트.
- Design implications: 텍스트 프롬프트를 출력하는 기능과 데이터 생성 로직을 깔끔하게 분리하여, FastAPI 앱에서 생성기를 호출하고 그 결과를 DB에 저장할 수 있도록 설계해야 함.

## Requirements
### Functional Requirements
- FR-1: 파이썬 스크립트가 계산한 전체 종목의 RS 데이터를 Turso DB 테이블 레코드로 저장해야 함 (최소 필드: `date`, `code`, `name`, `market`, `chages_ratio`, `marcap`, `rs`, `rs_1m`, `rs_3m`, `rs_6m`, `rs_12m`).
- FR-2: `update_rs.py` 스크립트는 `SQLModel`과 Turso 연결 주소(`libsql://`)를 이용해 데이터를 DB에 업서트(Upsert) 또는 인서트(Insert)해야 함.
- FR-3: `GET /api/rs-table` 엔드포인트는 Turso DB에서 최신 날짜의 RS 랭킹 데이터를 조회하여, HTML 부분 테이블(Partial table)로 렌더링하여 반환해야 함.
- FR-4: UI는 전체 페이지 새로고침 없이 HTMX를 이용해 최신 테이블 데이터를 다시 불러오는(새로고침) 버튼이 있어야 함.

### Non-Functional Requirements
- NFR-1: 프론트엔드는 CDN을 통해 Tailwind CSS v4를 사용해야 함.
- NFR-2: FastAPI 라우팅은 공식 스킬 가이드라인 컨벤션을 준수해야 함.
- NFR-3: 데이터 아키텍처는 시계열 조회가 가능한 Turso (서버리스 SQLite) 기반으로 구축함.
- NFR-4: 보안을 위해 Turso DB의 접속 URL과 Auth Token은 `.env` 파일을 통해서만 관리함.

## Architecture & Deployment Strategy
- **저장소 (Turso Database)**:
  - 시계열 데이터(일자별 추이)를 완벽하게 쿼리하기 위해 Turso (libSQL)를 사용함.
  - 파이썬의 `SQLModel` 라이브러리를 사용해 데이터 모델링 및 쿼리를 간결하게 유지.
- **데이터 갱신 (GitHub Actions / Local)**:
  - 매일 장 마감 후 `update_rs.py`를 실행해 최신 주가로 계산된 데이터를 Turso DB에 INSERT.
- **데이터 조회 (FastAPI)**:
  - FastAPI 서버는 Turso DB에 연결하여 `SELECT` 쿼리로 최신 랭킹 데이터 및 특정 종목의 과거 추이 데이터를 조회.
- **향후 고도화**:
  - 특정 종목 클릭 시 과거 RS 지표 변동 흐름을 보여주는 시계열 차트 기능 추가.

## Execution Rules
- 단계(Phase)를 순서대로 완료할 것.
- `market.py`와 `krx_auth.py`의 기존 로직은 온전히 보존할 것.
- 리스크에 따라 검증 방법을 선택할 것 (MVP의 경우 수동 UI 스모크 테스트로 충분함).
- 각 단계가 끝날 때마다 이 PRD를 업데이트할 것.

## Phase Index
| Phase | Status | Objective | Validation Focus | File |
|---|---|---|---|---|
| Phase 1: Database & Models | Not Started | SQLite 및 SQLModel 세팅 | Unit/Static Check | `tasks/prd-rs-dashboard.md` |
| Phase 2: Refactoring Logic | Not Started | DB 저장을 위한 로직 분리 | Integration Check | `tasks/prd-rs-dashboard.md` |
| Phase 3: FastAPI Backend | Not Started | `main.py` 및 엔드포인트 생성 | API Check | `tasks/prd-rs-dashboard.md` |
| Phase 4: Frontend UI | Not Started | Jinja2 템플릿 및 HTMX UI 생성 | Browser Check | `tasks/prd-rs-dashboard.md` |

## Phase Plan

### Phase 1: Data Models & Turso DB Setup
Parent PRD: [PRD: RS Dashboard](./prd-rs-dashboard.md)
Status: Not Started
Last Updated: 2026-05-30

#### Objective
RS 데이터를 표현할 Pydantic/SQLModel 클래스를 정의하고, Turso DB와 통신하는 엔진 세팅.

#### Scope
In Scope: `models.py`, `db.py`

#### Implementation Checklist
- [ ] `SQLModel`을 사용하여 Turso 테이블과 매핑되는 `StockRS` 클래스 작성 (`models.py`).
- [ ] Turso URL(`libsql://`)과 `TURSO_AUTH_TOKEN`을 이용해 DB 엔진을 생성하는 연결 코드 작성 (`db.py`).

#### Validation Checklist
- [ ] 테이블 자동 생성 스크립트를 실행하여 Turso 클라우드 상에 테이블이 잘 만들어졌는지 확인.

#### Phase-End Multi-Pass Review
- [ ] 1. 의도/커버리지 리뷰 (Intent/coverage review)
- [ ] 2. 정확성 리뷰 (Correctness review)
- [ ] 3. 단순성 리뷰 (Simplicity review)
- [ ] 4. 코드 품질 리뷰 (Code quality review)
- [ ] 5. 중복/정리 리뷰 (Duplication/cleanup review)
- [ ] 6. 보안/프라이버시 리뷰 (Security/privacy review)
- [ ] 7. 성능/부하 리뷰 (Performance/load review)
- [ ] 8. 검증 리뷰 (Validation review)
- [ ] 9. 후속 단계 점검 리뷰 (Future-phase review)
- [ ] 10. PRD 동기화 리뷰 (PRD sync review)

### Phase 2: Refactoring Logic
Status: Not Started

#### Objective
단순 터미널 출력이 아니라, 계산된 데이터를 Turso DB 테이블에 직접 INSERT하는 독립 스크립트로 `update_rs.py` 구축.

#### Scope
In Scope: `update_rs.py`

#### Implementation Checklist
- [ ] `SQLModel`을 활용해 분석 결과(DataFrame)를 `StockRS` 객체 리스트로 변환.
- [ ] 변환된 객체 리스트를 Turso DB에 일괄 삽입(Bulk Insert)하는 로직 구현.

#### Validation Checklist
- [ ] 터미널에서 스크립트 실행 후 `turso db shell techtrader-db`를 통해 데이터가 잘 들어갔는지 `SELECT * FROM stockrs`로 확인.

#### Phase-End Multi-Pass Review
- [ ] 1-10 (표준 리뷰 완료)

### Phase 3: FastAPI Backend
Status: Not Started

#### Objective
FastAPI 애플리케이션 초기화, Turso DB 세션 의존성 주입 및 UI용 HTMX 엔드포인트 구축.

#### Implementation Checklist
- [ ] FastAPI를 초기화하는 `main.py` 파일 생성.
- [ ] `templates/index.html`을 렌더링하는 `GET /` 라우터 생성.
- [ ] Turso DB에서 `SELECT * FROM stockrs WHERE date = 최근영업일` 쿼리를 실행해 결과를 `templates/partials/table.html`로 렌더링하는 `GET /api/rs-table` 라우터 생성.

#### Validation Checklist
- [ ] `fastapi dev main.py` 실행.
- [ ] curl 또는 브라우저를 통해 각 엔드포인트 동작 확인.

#### Phase-End Multi-Pass Review
- [ ] 1-10 (표준 리뷰 완료)

### Phase 4: Frontend UI
Status: Not Started

#### Objective
Tailwind CSS (CDN), HTMX, Alpine.js를 활용하여 HTML 템플릿 화면 구축.

#### Implementation Checklist
- [ ] Tailwind CSS v4 CDN 스크립트 및 다크 모드 스타일이 적용된 `templates/index.html` 생성.
- [ ] `hx-get="/api/rs-table"` 속성이 부여된 "Refresh Table" 버튼과 헤더 추가.
- [ ] 버튼 클릭(또는 스크립트 실행 후 갱신) 시 로딩 상태를 표시하기 위한 Alpine.js 속성 추가.
- [ ] Jinja2를 이용해 `stocks` 목록을 반복 렌더링하는 `templates/partials/table.html` 생성.

#### Validation Checklist
- [ ] `localhost:8000` 브라우저 접속.
- [ ] 업데이트 버튼 클릭 후, UI가 로딩 상태를 표시하고 성공적으로 테이블이 갱신되는지 확인.

#### Phase-End Multi-Pass Review
- [ ] 1-10 (표준 리뷰 완료)

## Final Multi-Pass Review After All Phases
모든 단계를 마친 후 순서대로 검토:
- [ ] 1. 요구사항 커버리지 점검
- [ ] 2. 단계 간 통합 점검
- [ ] 3. 로직 정확성 점검
- [ ] 4. 단순성 및 리팩터링 여부 점검
- [ ] 5. 코드 중복 및 불필요 파일 정리 점검
- [ ] 6. 보안 및 프라이버시 점검
- [ ] 7. 성능 점검
- [ ] 8. 검증 전략 점검
- [ ] 9. 문서 및 운영 대응 여부 점검
- [ ] 10. PRD 최종 마감 처리
