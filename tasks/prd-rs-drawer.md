# PRD: RS 종목 상세 드로어 (RS Stock Detail Drawer)

## 문서 상태 (Document Status)
- 상태: Complete
- 파일 모드: Single
- 현재 페이즈: Complete
- 최종 업데이트: 2026-08-11
- PRD 파일: `tasks/prd-rs-drawer.md`
- 목적: 작업의 기준점(Source of Truth)이 되는 살아있는 PRD

## 문제점 (Problem)
현재 RS 대시보드에는 요약된 지표와 함께 종목 목록이 표시됩니다. 하지만 특정 종목을 클릭하여 상세 정보와 과거 RS 지표를 한 번에 볼 수 있는 기능이 없습니다. 추후 추가될 트레이딩뷰 차트의 자리를 확보하고, 모든 지표를 표시할 수 있는 상세 정보 드로어 화면이 필요합니다.

## 목표 (Goals)
- G-1: 종목 테이블의 행(Row)을 클릭하면 열리는 daisyUI의 `drawer` 컴포넌트 기반 우측 드로어 구현.
- G-2: 드로어 상단에 "차트 준비중"이라는 안내 메시지(Placeholder) 표시.
- G-3: 차트 영역 아래에 사용 가능한 모든 종목 지표(종목명, 종목코드, 시장, 현재가, 등락률, RS, RS_1M, 3M, 6M, 12M, 시가총액, 거래대금) 표시.
- G-4: 모바일 및 데스크톱 환경 모두에서 최적화된 레이아웃으로 표시되는 반응형 드로어 구현.

## 비목표 (Non-Goals)
- NG-1: 이번 PRD에서 실제 트레이딩뷰 차트를 연동하는 작업.
- NG-2: 새로운 백엔드 API 추가 (기존 DOM과 Alpine 상태에 있는 데이터만 사용).

## 성공 기준 (Success Criteria)
- SC-1: 종목 행을 클릭하면 해당 종목의 데이터가 담긴 드로어가 정상적으로 열림.
- SC-2: 드로어 내부에 "차트 준비중" 표시 및 모든 요구 데이터가 정확하게 렌더링됨.
- SC-3: 드로어 레이아웃이 모바일(전체 화면 또는 대부분 차지)과 데스크톱(사이드바 형태) 모두에서 자연스럽게 전환됨.

## 사전 조사 요약 (Discovery Summary)
- 검토 대상: `templates/pages/rs.html`, `templates/partials/table.html`
- 현재 시스템: `rs.html`은 상태 관리를 위해 Alpine.js를, 테이블 로드를 위해 HTMX를 사용합니다. `table.html`에는 `<template id="all-rows-template">`가 정의되어 있으며, JS를 통해 복제되어 렌더링됩니다.
- 검증 방법: 브라우저 테스트 (로컬 서버).
- 설계 고려사항: 테이블이 JavaScript에 의해 `<template>` 노드를 복제하여 렌더링되므로, 행에 인라인 Alpine 클릭 핸들러(`@click`)를 추가하면 Alpine이 다시 초기화되지 않는 한 제대로 동작하지 않을 수 있습니다. 가장 안전한 접근법은 `#rs-table-body`에 이벤트 위임(Event Delegation)을 사용하여 클릭 리스너를 추가하고, 전역 Alpine 이벤트를 발생시켜 드로어를 여는 것입니다.

## 요구사항 (Requirements)
### 기능적 요구사항 (Functional Requirements)
- FR-1: `#rs-table-body`의 이벤트 위임을 통해 행 클릭을 감지하고 `data-*` 속성을 추출해야 함.
- FR-2: 드로어 상태를 관리하는 Alpine 컴포넌트는 해당 열기 이벤트를 수신하고, 데이터를 채운 뒤 드로어 상태를 토글해야 함.
- FR-3: 드로어 UI에는 닫기 버튼이나 외부 클릭 시 닫히는 오버레이가 포함되어야 함.

### 비기능적 요구사항 (Non-Functional Requirements)
- NFR-1: 스타일링에는 반드시 daisyUI 클래스를 사용해야 함 (`drawer`, `drawer-side`, `drawer-content`, `drawer-overlay`).
- NFR-2: 드로어가 열릴 때 시각적인 성능 저하가 없어야 함.

## 실행 규칙 (Execution Rules)
- 본 PRD가 명시적으로 수정되지 않는 한 순서대로 페이즈를 완료할 것.

## 페이즈 인덱스 (Phase Index)
| 페이즈 | 상태 | 목표 | 검증 대상 | 파일 |
|---|---|---|---|---|
| 페이즈 1: 드로어 UI 및 로직 | Complete | 드로어 셸, UI 레이아웃 추가 및 클릭 이벤트 연동 | 브라우저/UI | `tasks/prd-rs-drawer.md` |

## 페이즈 계획 (Phase Plan)

### 페이즈 1: 드로어 UI 및 로직 (Drawer UI & Logic)

상위 PRD: [PRD: RS 종목 상세 드로어](./prd-rs-drawer.md)
상태: Complete
최종 업데이트: 2026-08-11

#### 목표
`rs.html`에 daisyUI 드로어 구조를 추가하고, 상세 레이아웃을 디자인하며, 테이블에서 클릭 이벤트를 연동합니다.

#### 페이즈 진입 전 확인사항 (Phase Discovery Gate)
코드 수정 전 재확인:
- [x] 관련 코드/파일: `templates/pages/rs.html`
- [x] 마스터 PRD의 가정이 여전히 유효한지 확인

#### 작업 범위 (Scope)
**포함 (In Scope)**
- `main` 콘텐츠를 `drawer-content`로 감싸기.
- `drawer-side` 및 `drawer-toggle` 추가.
- 드로어 내부 디자인 ("차트 준비중" + 데이터 그리드).
- 행 클릭 처리를 위한 JS 이벤트 리스너 추가.

**제외 (Out of Scope)**
- 트레이딩뷰 차트 연동.

#### 구현 체크리스트 (Implementation Checklist)
- [x] **1. Alpine 상태:** `rs.html`에서 메인 레이아웃을 새로운 Alpine 컴포넌트(예: `x-data="stockDrawer()"`)로 감싸기.
- [x] **2. 드로어 마크업:** daisyUI의 `<div class="drawer drawer-end">`, `<input class="drawer-toggle">`, `<div class="drawer-content">`, `<div class="drawer-side">` 삽입.
- [x] **3. 드로어 UI:** `drawer-side` 내부에 "차트 준비중" 블록(daisyUI mockup 또는 빈 상태 활용)과 종목 데이터를 보여줄 `stat` 또는 `badge` 컴포넌트 기반 그리드 추가.
- [x] **4. 이벤트 위임:** `rs.html`의 기존 클라이언트 측 스크립트에서 `#rs-table-container`에 클릭 리스너를 추가하여, 클릭된 가장 가까운 `.stock-row`를 찾고 `dataset`을 읽어 사용자 정의 이벤트(`open-stock-drawer`)와 함께 종목 데이터를 발생시킴.
- [x] **5. Alpine 리스너:** `stockDrawer()` 컴포넌트는 `@open-stock-drawer.window` 이벤트를 수신하여 내부 상태를 업데이트하고 드로어를 열림 상태로 변경.

#### 검증 전략 (Validation Strategy)
브라우저/UI 검증: 모바일 및 데스크톱 해상도 모두에서 행을 클릭하여 드로어가 부드럽게 열리고 올바른 데이터가 표시되는지 테스트합니다.

#### 검증 체크리스트 (Validation Checklist)
- [x] 브라우저/UI 검증 완료: 행 클릭 시 드로어가 열리는지 확인.
- [x] 브라우저/UI 검증 완료: "차트 준비중" 안내가 정상적으로 보이는지 확인.
- [x] 브라우저/UI 검증 완료: 다른 종목 클릭 시 데이터가 올바르게 갱신되는지 확인.
- [x] 브라우저/UI 검증 완료: 모바일과 데스크톱에서 반응형 디자인이 정상적으로 작동하는지 확인.

#### 종료 조건 (Exit Criteria)
- [x] 페이즈 목표 달성
- [x] 명시된 요구사항 구현 완료
- [x] 다음 페이즈로 넘어가기 위한 알려진 차단(Blocker) 이슈 없음

#### 페이즈 종료 리뷰 (Phase-End Multi-Pass Review)
- [x] 1. 의도 및 커버리지 검토
- [x] 2. 정확성 검토 (Correctness)
- [x] 3. 단순성 검토 (Simplicity)
- [x] 4. 코드 품질 검토 (Code quality)
- [x] 5. 중복/정리 검토 (Duplication/cleanup)
- [x] 6. 보안/개인정보 보호 검토
- [x] 7. 성능/부하 검토
- [x] 8. 검증 리뷰
- [x] 9. PRD 동기화 검토

## 최종 리뷰 (Final Multi-Pass Review After All Phases)
- [x] 1. 요구사항 커버리지 검토
- [x] 2. 페이즈 간 통합 검토
- [x] 3. 정확성 검토
- [x] 4. 단순성/리팩토링 검토
- [x] 5. 중복/정리 검토
- [x] 6. 보안/개인정보 보호 검토
- [x] 7. 성능/부하 검토
- [x] 8. 검증 리뷰
- [x] 9. 문서/운영 리뷰
- [x] 10. PRD 종료 리뷰
