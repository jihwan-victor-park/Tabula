# Tabula 구현 체크포인트

기준 문서: 「Tabula — 소상공인 재고 보충·발주 자동화 제품 및 기술 명세」(2026-10-20), 저장소 기준 커밋 `d6335bf`.

규칙

- 체크포인트는 **완료 기준(gate)을 테스트나 실제 데이터로 통과해야** 닫는다. 날짜보다 gate가 우선이다.
- 각 항목의 `[ID]`는 명세 19.1 백로그 ID다.
- 상태: `[ ]` 미착수 · `[~]` 진행 중 · `[x]` gate 통과
- 외부 의존성(앱 심사, 공급업체 협조, 결제 provider 승인)은 `⏳ 외부`로 표시하고 코드 일정과 분리한다.
- 데모/샘플 데이터는 항상 `demo` 배지로 실제 데이터와 분리한다.

진행 순서 요약

```
CP0 고객·데이터 확인 (사람 작업, CP1과 병행)
CP1 운영 기반 ──► CP2 카탈로그·단위 ──► CP3 CSV/Sheets 수입 ──► CP5 보충 엔진 ──► CP6 PO·승인
                                  └──► CP4 첫 POS 커넥터 (⏳ 앱 심사와 병행) ──┘
CP6 ──► CP7 공급업체 전송·확인 ──► CP8 입고 ──► CP9 Invoice 대조   ← YC 데모 gate
CP10 화면(Today/Orders/Receiving)은 CP5부터 각 CP와 함께 붙인다
CP11 운영 신뢰성 · CP12 SaaS 구독 · CP13 제한 자동화 · CP14 확장
```

CSV 경로(CP3)로 보충 계산(CP5)까지 먼저 갈 수 있으므로 Square 앱 심사가 끝나기를 기다리지 않는다.

---

## CP0 — 고객·데이터 확인 (명세 단계 0)

담당: 창업자 · 코드 없음 · CP1과 병행

- [ ] 0.1 인터뷰 대상 10곳 목록(펫용품 1순위, 뷰티, 접근 가능한 장난감 매장)
- [ ] 0.2 명세 18.1 질문으로 인터뷰 5곳 이상, 지난 2회 발주를 실제 화면/문서로 확인
- [ ] 0.3 design partner 후보마다 확보: 90일+ 판매 export, 현재 재고 export, invoice 3–5개, 공급업체 단가표, 미입고 주문 목록
- [ ] 0.4 후보별 POS, 회계 프로그램, 공급업체 주문 채널(이메일/portal/전화) 기록
- [ ] 0.5 결정: 업종 1개, POS 1개, 상위 반복 SKU 50–200개, 주요 공급업체 2–3곳

Gate: 한 업종·한 POS·주문 채널이 정해지고 실제 파일 1세트가 `data/pilot/`(git 제외)에 있다. 정해진 POS가 Square가 아니면 CP4의 대상을 바꾼다.

**현재: 미착수. CP3·CP5는 합성 파일로만 검증됨 — 실제 고객 파일 검증은 여기서 남아 있음.**

---

## [~] CP1 — 운영 기반 (명세 단계 1) `[CORE-01] [CORE-02] [INV-01 일부]`

목표: 이후 모든 기능이 올라갈 tenant 격리, 트랜잭션 원장, 멱등성, outbox, 감사 기록.

- [x] 1.1 단일 FastAPI app `clawbot/api/app.py`, `/v1` domain router 분리 (기존 포트별 app은 legacy로 유지)
- [x] 1.2 PostgreSQL + SQLAlchemy 2 + Alembic, `clawbot/persistence/`
- [x] 1.3 최소 테이블: `tenants, users, memberships, locations, variants, inventory_positions, inventory_movements, connector_events, outbox, audit_events`
- [x] 1.4 tenant 범위 복합 FK `(tenant_id, id)`: 다른 tenant의 variant/location을 DB 수준에서 참조 불가
- [x] 1.5 인증: Auth0 JWT + 로컬 전용 dev 모드(`TABULA_AUTH_MODE=dev`, production에서는 거부). JWKS 1시간 캐시 + 모르는 `kid`면 재조회(키 교체 대응), Auth0 경로 테스트 포함
- [x] 1.6 `X-Tenant-Id` 헤더를 서버에서 membership으로 검증, 역할 `owner/manager/receiver/bookkeeper`, `GET/PUT /v1/members`(owner 전용, 마지막 owner 강등 금지)
- [x] 1.6b 권한은 **domain 계층**에서 강제: `clawbot/policies/permissions.py`의 단일 표, 행위자 = human/agent/system. agent는 매핑 제안만, 확정·공급업체 승인·주문 주소 검증은 사람만 (명세 8)
- [x] 1.7 재고 원장: 이동 기록 + 위치별 수량 갱신을 **한 트랜잭션**으로, `(tenant_id, source, source_event_id)` 고유 제약, UUID ID (기존 `adjust_stock()`의 비원자성·초 단위 ID 문제 해결)
- [x] 1.8 같은 idempotency key에 다른 payload가 오면 409 (재고 이동, outbox enqueue). 일반 POST용 Idempotency-Key 저장소는 CP6
- [x] 1.9 outbox: `(tenant_id, operation_key)` 고유, `FOR UPDATE SKIP LOCKED` 임대 + fencing token, backoff, 최대 시도 후 `dead`. 임대 만료 = 결과 불명 → `unknown`(재전송 안 함, 명세 16.2), `retry_safe` 메시지만 재시도
- [x] 1.9b 재고 write owner: 위치별 `inventory_write_owner`, POS 소유 위치에는 Tabula 이동 거부. 수동 입력은 adjustment/count/damage/return만 (receipt·transfer는 각 흐름에서만)
- [x] 1.10 connector raw event 저장·중복 제거 `(tenant_id, provider, external_event_id)`
- [x] 1.11 audit_events: actor(kind/user/name), action, before/after, reason
- [x] 1.12 pytest를 실제 Postgres(`tabula_test`)로 실행
- [x] 1.13a 저장소 조치 (구현 완료): 런타임 credential·세션·로그 파일 추적 해제, `.gitignore`, 전화번호 → 환경변수, `scripts/secret_scan.py` + pre-commit hook + 테스트, 노출 목록·영향·교체 절차 `docs/SECURITY.md`
- [ ] 1.13b **credential 교체 (사용자 조치 대기)**: OpenClaw gateway 토큰, 기기 identity 키, operator 토큰을 gateway 기기에서 폐기·재발급 (`docs/SECURITY.md` 3절 순서). 공개 저장소라 파일 삭제만으로는 해결되지 않음
- [ ] 1.13c Git 이력 재작성·force push: **하지 않음, 별도 확인 필요** (`docs/SECURITY.md` 4절)
- [x] 1.14 정책 개정: `docs/SUPPLIER_CONTACT_POLICY.md` + `clawbot/policies/supplier_contact.py`(기본 disabled, 개발은 test_only, live는 이 빌드에서 거부). 대화형 agent의 공급업체 연락 금지는 유지

Gate (테스트로 확인) — 코드 gate 통과 2026-10-20, 독립 리뷰 1회 반영. **구현은 완료, credential 교체(1.13b)가 사용자 조치로 남아 CP1 전체는 `[~]`**

- 다른 tenant의 객체 ID로 조회·변경 시 404/403
- 같은 재고 이벤트 10회 → 수량 1회만 반영
- 서로 다른 이동 50건 동시 실행 → 최종 수량 = 합계
- 같은 key 동시 요청 → 1건만 반영
- 두 worker가 같은 outbox 행을 동시에 임대하지 못함
- 같은 connector event 반복 저장 → 1행

---

## [x] CP2 — 카탈로그·단위·공급업체 마스터 `[CAT-01]`

- [x] 2.1 `products`, `variants`: 크기(값+단위), pack_count, 속성(맛/색), active/discontinued, GTIN-14 정규화(체크디지트 검증, tenant 내 고유). 크기·포장·속성은 생성 후 변경 불가(다르면 새 variant)
- [x] 2.2 `external_item_mappings`: provider item ID ↔ variant, suggested/confirmed/rejected. 제안은 확정을 덮지 않음, 결정은 사람만·되돌릴 수 있음·감사 기록, 결정 시 검토한 variant를 함께 보내야 함(중간에 바뀌면 409)
- [x] 2.3 동일 상품 판별(`domain/matching.py`): provider ID → merchant SKU → GTIN/바코드 → 확정 supplier SKU, 낮은 순위가 다른 상품을 가리키면 conflict. 텍스트 유사도는 후보만 + 크기·포장 충돌 경고
- [x] 2.4 `suppliers`(명세의 supplier_accounts는 tenant별 supplier에 통합): 주문 채널, portal, merchant account, 마감 시각+timezone, 배송 요일, 최소 금액, 무료배송 기준, 운임 조건, lead time, 통화, 결제 조건, credit hold, 휴무일, 배송 가능 매장, `relationship_status`, `verified_at/by`. 연락처는 merchant가 검증
- [x] 2.4b 승인 체크리스트(명세 5.5): 주문 경로, 검증된 주문 이메일/portal, merchant account(없다는 명시 가능), 결제 조건, lead time, 최소 주문 조건(0 = 없음), 운임 조건, 배송 매장. 주문 경로 변경 → candidate로 강등, 체크리스트를 깨는 수정 → 거부
- [x] 2.5 `supplier_items` + `supplier_item_prices`(이력): supplier SKU, order_uom, units_per_order_uom, order multiple, MOQ, lead time. 가격은 견적 포장 단위를 명시해야 하고 다르면 거부, 미래 적용가 지원, 공개 판매가(public_listing)는 발주 불가, 주문 가능 가격은 공급업체 통화만
- [x] 2.5b 포장 변경(12→24입, 명세 19.2): 매핑 확정 해제 + 현재·예약 가격 폐기 → 재확인 전 발주 불가
- [x] 2.6 단위·금액(`domain/units.py`, Decimal 전용, float 거부): 48 each → 4 case, pack/multiple/MOQ 반올림과 초과분 표시, 통화 minor unit, 통화 혼합 비교 거부
- [x] 2.7 tenant 격리: 모든 supplier 데이터 복합 FK, 다른 tenant 조회·매핑·가격 기록 404 (테스트)
- [x] 2.8a `insert_quote`는 중복 키만 무시, regex injection 차단, legacy `find_catalog_entry`는 크기·포장 충돌 매치 거부
- [→] 2.8b legacy procurement agent를 `resolve_item` + 확정 supplier_items로 전환 → **CP6.10**으로 이동
- [x] 2.9 발주 가능 판정 `offers_for_variant`: 막힌 이유 목록(공급업체 상태, credit hold, 매핑, 품목·variant 상태, 배송 매장, 가격 없음/만료/포장 불일치, lead time 없음)

Gate: 12입 상품이 **주문 단위**에서 일치(입고 쪽은 CP8에서 확인). 50ml/100ml, 1개/12개입이 별개 variant로 남는다. 텍스트 매칭만으로는 mapping이 확정되지 않는다. — 통과 2026-10-20: 테스트 116개, 독립 리뷰 2회(1차 버그 11·명세 누락 4, 2차 추가 결함 10여 건) 반영, 핵심 수정은 mutation 검사로 테스트 유효성 확인

CP2에서 미룬 것 (담당 CP)

- 운임 포함 원가(landed cost), 구조화된 운임 규칙 → CP5/CP6
- 매장 배송 주소·영업일 → CP5(영업일), CP6(배송 주소)
- 공급업체 수준 MOQ(수량) → CP6
- 실측 lead time 분포 → CP8.5
- 확인된 지급 수단 reference → CP14
- supplier_items의 포장·조건 출처 기록(현재는 audit에만) → CP3
- 텍스트 후보 검색 성능(행×variant 전수 비교) → CP3(pg_trgm 등)
- `ExternalItemMapping` 낙관적 동시성(version) → CP3 (결정은 이미 검토한 variant에 묶임)
- 서버 간 시계 차이로 동시 가격 기록이 back-date로 거부될 수 있음 → CP11(DB `now()` 사용 검토)
- agent/worker 코드는 사람 actor를 `tenancy.actor_for()`로만 생성 (역할은 membership에서) → CP3부터 규칙

## [x] CP3 — CSV / Excel 수입 `[IMP-01]` (3c Google Sheets는 ⏳ 외부 대기)

흐름: 업로드 → 열 매핑 초안 → 미리보기(행별 해석·오류) → 사람이 의미를 확정 → 적용 job(202) → 결과·오류 목록. 확정 전에는 아무것도 반영되지 않는다.

3a. 수입 틀

- [x] 3a.1 `imports`, `import_rows`: 파일 SHA-256, 크기, 종류, 상태, context(공급업체·위치 등), mapping + revision. `(tenant, kind, sha256)` 고유 → 같은 파일 재업로드는 기존 import 반환
- [x] 3a.2 파서: CSV(UTF-8/BOM, 구분자 감지), XLSX(openpyxl read-only, 캐시된 값만, macro 미실행), 크기·행 수 제한, 빈 행 무시
- [x] 3a.3 값 해석: 숫자(통화 기호·천 단위·괄호 음수), 통화 기호 ↔ 선언 통화 불일치 오류, 날짜(ISO 기본, 그 외 형식은 사람이 명시), timezone 없는 시각은 위치 timezone
- [x] 3a.4 열 매핑 초안(헤더 동의어) + 애매한 의미(Case/Qty/Cost가 상자인지 개수인지)는 **사람이 명시해야 확정 가능**
- [x] 3a.5 미리보기: 행별 해석("상자 12개 × $30.00 = 개당 $2.50")과 오류·경고, 파일 내 중복 행 탐지
- [x] 3a.6 확정 = mapping revision에 묶임(중간에 바뀌면 409), 행 오류가 있으면 명시적 동의 시에만 유효 행 적용
- [x] 3a.7 적용은 outbox job(`import.apply`, retry_safe), 행 단위 멱등 → worker 재시작·재시도에도 중복 반영 없음
- [x] 3a.8 오류 목록 CSV 내보내기(formula injection 방지 `=`, `+`, `-`, `@` 등)
- [x] 3a.9 API: `POST /v1/imports`(multipart), `GET /v1/imports/{id}`, `GET …/preview`, `PUT …/mapping`, `POST …/confirm-mapping`(202), `GET …/errors.csv`

3b. 종류별 적용

- [x] 3b.1 공급업체 가격표 → supplier_items(출처 기록) + 가격 이력. 단가 기준(상자당/개당)과 포장 수량은 사람이 확정, merchant SKU/바코드가 있으면 variant **제안만**. 같은 가격 재적용은 무변화
- [x] 3b.2 재고 → `inventory_snapshots`(기준 시각·출처). Tabula 소유 위치는 차이만큼 `count` 이동, POS 소유 위치는 snapshot만. 선택 시 미등록 SKU를 variant로 생성(권한 필요)
- [x] 3b.3 판매 → `sales_lines`(출처 채널·거래 ID·line key 고유, 판매/환불 구분) → 같은 판매를 두 번 올려도 수요 1회
- [x] 3b.4 미입고 주문 → `external_open_order_lines`(공급업체·PO 번호·SKU·잔량·확인 여부·ETA) → CP5 중복 발주 방지 입력
- [x] 3b.5 SKU 해석은 `resolve_item`, 실패 행은 후보와 함께 오류. 텍스트 후보는 pg_trgm 인덱스로(CP2 이월)

3c. Google Sheets ⏳ 외부: Google OAuth 앱·검증

- [ ] 3c.1 파일·탭 선택, 15–60분 polling, 범위 batch read + checksum, quota 준수
- [ ] 3c.2 행 번호를 ID로 쓰지 않음(행 key = SKU+위치+source), 열 이동 감지 시 매핑 재확인
- [ ] 3c.3 기본 읽기 전용, writeback은 Tabula 전용 탭만

Gate: 잘못된 단위의 가격표가 승인 전에 차단된다. 같은 판매 CSV를 두 번 올려도 수요가 한 번만 반영된다. CP0의 실제 파일 1세트가 오류 목록과 함께 수입된다(실제 파일은 CP0 이후 — 그 전에는 현실적인 합성 파일로 검증하고 그렇게 표시).
— 3a/3b 통과 2026-10-20: 테스트 195개(합성 파일), 독립 리뷰 2회(1차 버그 14·명세 누락 4, 2차 미해결 3·신규 8) 반영. **실제 파일 검증은 CP0 이후 남음**

CP3 리뷰 반영 요약: XLSX 압축 해제 크기·셀 길이 제한, 매직 바이트 검사, 계산 안 된 수식 = 오류, void/취소는 판매 아님, DB 오류는 행 단위로 격리, 죽은 job → import `failed`, 같은 파일이라도 다른 위치·거절 후 재업로드는 새 import, **확정 시 행별 해석 digest 고정 → 적용 시 달라진 행은 반영 안 함**, 의미 설정(단가 기준·포장·통화·가격 유형·날짜 형식·timezone 등)은 확정하는 사람이 다시 진술(값의 의미로 비교), **오류 행 허용에 동의하지 않았으면 적용 중 한 행이라도 실패 시 전체 미적용**, XLSX 선언 크기 무시(행 누락 방지), 단위 별칭 정규화(CS=case), `$`/`¥` 다통화, 판매 line key는 파일의 원래 식별자 + 순번(바코드 재연결·부분 환불 반복에도 1회), 실사 순서는 실제 발생 시각 기준, 미래 날짜 거부, 판매 출처는 고정 목록 + 주문 단위 key 방식 하나만(다른 경로로 들어온 같은 주문은 검토 대상)

CP3에서 미룬 것 (담당 CP)

- 원본 파일 보관(documents 테이블) → CP9
- receiver용 실사 전용 권한(지금은 owner/manager/bookkeeper만 업로드·확정) → CP8/CP10
- 권장 필드(판매 가능·손상 수량, 할인·채널·재고 복원, 이미 받은 수량) → CP4/CP5
- 긴 job의 lease heartbeat, 미리보기 결과 캐시, 파서를 API 프로세스 밖으로 → CP11
- "1,500"은 미국 기본값대로 천 단위로 읽음(다른 locale 지원 시 재검토) → CP14


## [~] CP4 — 첫 POS 커넥터 (Square) `[CON-01] [CON-02]` — Sandbox 코드 완료, ⏳ Sandbox 실호출 검증은 사용자 계정 등록 후

Sandbox 개발과 App Marketplace 등재 심사는 별개다(`docs/SQUARE_SETUP.md`). 심사를 기다리지 않는다.

- [x] 4.1 connector 계약(`clawbot/connectors/base.py`)과 실제 지원 기준의 `capabilities` (CP4: sales/inventory/catalog read만)
- [x] 4.2 OAuth: 단일 사용·10분 만료 state(교환 실패해도 재사용 불가), token Fernet 암호화 저장, revoke. production은 `TABULA_ENV=production`에서만
- [ ] 4.2b access token refresh job
- [x] 4.3 위치는 사람이 하나씩 연결(자동 합산 없음), 연결된 위치의 재고 소유자 = square
- [x] 4.4 backfill: catalog(매핑 **제안**만, 미일치 상품은 사람이 adopt), 완료 주문 판매·환불(Square UID key), 재고 snapshot, 동기화 기간을 sales coverage로 기록
- [x] 4.5 webhook: 서명 검증 → 원본 저장(event_id 중복 제거) → outbox job → Square 최신 상태 재조회
- [ ] 4.6 변경분 polling + 야간 전체 대조 스케줄 (webhook 유실 복원) — 동기화 함수는 있음, 스케줄러 없음
- [x] 4.7 POS 소유 위치는 snapshot 경로로만 갱신
- [ ] 4.8a 주문 key 방식 인계: CSV로 기록된 주문에 커넥터가 이후 줄(환불 등)을 붙일 때의 규칙(지금은 검토 대상, CP3 리뷰 2e)
- [x] 4.8 판매는 `key_scheme=provider_line`, 같은 주문이 CSV로 이미 있으면 이중 집계 없이 검토 대상
- [x] 4.9 mock Square(`clawbot/connectors/square/mock.py`)로 전체 흐름 테스트, 재시도(429/5xx)·페이지네이션 포함

Gate: 실제 계정 표본의 거래·재고·환불이 원본과 일치(**Sandbox 계정 필요 — 미검증**). webhook을 일부러 누락시켜도 polling으로 복원(4.6 미완). 같은 webhook 반복 수신 → 1회 처리(테스트 통과).

---

## [~] CP5 — 보충 엔진 (결정적 계산) `[PLAN-01]` — 구현·리뷰 1회 반영, 재검증 대기

- [x] 5.1 일별 SKU 수요(위치 local 날짜), **coverage 기록으로 "판매 없음"과 "데이터 없음" 구분**, 0재고 snapshot 날은 평균에서 제외
- [x] 5.2 이동평균 + 요일 패턴(4주 이상) + merchant min/max, 간헐 수요는 긴 구간 + 검토 표시
- [x] 5.3 target/position/need, pack·multiple·MOQ 반올림 (`clawbot/domain/replenishment/engine.py`, LLM 없음)
- [x] 5.4 날짜별 projected stock, 주문 있을 때/없을 때 품절일
- [x] 5.5 공급업체 마감 시각·배송 요일·휴무, 열린 주문(확정/미확정/기한 지남/ETA 없음), 최소 금액·무료배송(표시만), 단종, 주간 budget(표시만)
- [ ] 5.5b 매장 영업일, 유통기한, 보관 공간, 행사, 매장 간 이동 → CP13/CP14
- [x] 5.6 run: cutoff, policy version, engine version, input digest, line별 입력 저장 → replay 동일. 같은 입력 = 같은 run, 위치당 current 1개, 과거 시점 run은 `historical`
- [ ] 5.7 rolling-origin backtest 하네스 → CP0 실제 데이터 확보 후
- [x] 5.8 LLM 미사용(수량·금액 전부 코드). 설명 생성은 CP10에서 선택
- [x] 5.9 legacy agent 루프 상한(`clawbot/agents/limits.py`: step·시간)
- [x] 5.10 `POST /v1/replenishment-runs`, `GET /v1/recommendations`(cutoff 기준 오래됨·새 데이터 표시)
- [x] 5.11 통화 섞인 offer → `mixed_currency_offers` blocker
- [x] 5.12 미입고 주문 파일: 기준 시각·완전 목록 여부 명시 필수, 오래된 보고는 덮어쓰기 불가, 완전 목록에서 빠진 줄 닫음
- [x] 5.13 실사 사이 재고 = 마지막 실사 + 이후 다른 이동 − 이후 판매(환불은 되돌리지 않음), snapshot 우선순위 POS > 수동

Gate: 명세 7.3 예시(5상자, 품절 1일) 통과(엔진 단독 + import 경유). boundary: 납기 0일, 기한 지난 ETA, 계획 기간 밖 입고, 판매 데이터 공백, 실사 후 파손, 과거 시점 run, 공급업체 선택 — 테스트 통과. scheduler·수동 동시 실행 → 현재 계획 1개. **독립 리뷰 2차(재검증)는 리뷰 agent 사용 한도로 중단 — 재개 필요.**

남은 한계(명시): 행이 기록된 transaction 시작 시각 기준이라 실행 직전에 시작해 직후 commit된 쓰기는 "새 데이터"로 표시되지 않을 수 있음 → CP11. 품절일 제외는 0재고 snapshot이 찍힌 날만 → 재고 이력 재구성은 CP5.x.

---

## CP6 — PO·승인·예산 `[PO-01] [PO-02]`

- [ ] 6.1 `purchase_orders, po_lines, po_revisions` (메모리 dict인 `pending_orders.py` 대체)
- [ ] 6.2 PO 상태 기계(명세 10): draft → awaiting_approval → approved → sending → sent → supplier_confirmed → partially_received → received → closed, cancel_requested/cancelled/exception
- [ ] 6.3 line별 ordered/confirmed/received/rejected/cancelled/outstanding
- [ ] 6.4 승인은 revision·금액·수취인·배송지·정책 version에 묶임, 변경 시 무효
- [ ] 6.5 승인 + budget 예약 + outbox 기록을 한 트랜잭션으로
- [ ] 6.6 `universal_agent.py`의 "confirmed" 반환을 실제 상태로 교체 (Approved ≠ Supplier accepted)
- [ ] 6.8 PO line은 승인 시점의 supplier_item version, order_uom, units_per_order_uom, price ID, 통화를 스냅샷 → 이후 포장·가격 변경이 승인을 무효화 (CP2 리뷰 C4)
- [ ] 6.9 일반 Idempotency-Key 저장소: POST purchase-orders/approve/send 등 재시도·더블클릭 중복 방지 (CP2 리뷰 C5)
- [ ] 6.10 legacy procurement agent를 PO 도메인 + 확정 supplier_items로 전환 (CP2.8b)
- [ ] 6.11 승인은 화면에 보인 내용의 digest에 묶음(수량·단가·포장·수취인·배송지) — CP3 import 확정과 같은 방식 (CP3 리뷰 C5)
- [ ] 6.7 API: `POST /v1/purchase-orders`, `/approve`, `/send`, `/cancel-request`

Gate: 서버 재시작 뒤 승인 상태 유지. 두 사람이 동시에 승인해도 outbox 전송 작업 1건. 승인 뒤 단가가 바뀌면 재승인 필요.

---

## CP7 — 공급업체 전송·확인 `[SUP-01]`

- [ ] 7.1 PO PDF/CSV 생성, 사전 검증된 주소로만 이메일 전송 (outbox worker)
- [ ] 7.2 전송 결과 불명(timeout)은 재전송하지 않고 owner task로
- [ ] 7.3 공급업체 확인 페이지: 만료 링크, GET은 읽기 전용, 수락은 POST + nonce + 유효기간 + 수취인 확인
- [ ] 7.4 전체 수락 / 부분 수락 / 가격 변경 / ETA 변경 / 공급 불가
- [ ] 7.5 변경 제안은 counteroffer revision으로, merchant 승인 후 확정. 대체품은 명시적 승인 전 주문 안 함
- [ ] 7.6 `supplier_acknowledgements`: 발송 ≠ 접수 ≠ 납기 확정
- [ ] 7.7 문서·이메일 속 지시문은 데이터로만 처리 (prompt injection 차단)
- [ ] 7.8 전송 대상은 **검증된** order recipient 연락처만 (미검증 연락처 추가는 승인 상태에 영향 없음)
- [ ] 7.9 outbox `unknown` 메시지 → owner task + provider 상태 조회로 해소

Gate: 실제 공급업체 1곳이 실제 PO 1건을 확인 페이지 또는 회신으로 확인. 이메일 보안 스캐너가 링크를 열어도 수락되지 않음. ⏳ 외부: 공급업체 협조

---

## CP8 — 입고 `[REC-01] [UI-02]`

- [ ] 8.1 `receipts, receipt_lines`: draft → verified → posted → corrected
- [ ] 8.2 부분 입고·손상·거절·초과·다른 SKU, 잔량은 공급업체 취소 확인 전까지 유지
- [ ] 8.3 입고 게시 = CP1 재고 원장 이동 1회 (write owner가 POS면 `post_receipt` 경로)
- [ ] 8.4 모바일 Receiving: scan + 카메라 거부·미인식 시 수동 입력
- [ ] 8.5 실측 lead time 기록 → supplier 조건에 반영

Gate: 10상자 중 8 입고·1 손상·나머지 backorder 시나리오에서 잔량과 재고가 정확하고 재고는 한 번만 게시.

---

## CP9 — Invoice 대조 `[BILL-01]`

- [ ] 9.1 전용 수신 주소 + 업로드로 invoice 수입 (Gmail 전체 inbox 접근은 하지 않음)
- [ ] 9.2 `documents, extraction_runs`: 원본 hash, parser/model version, 검토 상태
- [ ] 9.3 PO·입고·invoice line 대조, 중복 invoice `(tenant, supplier, normalized_invoice_number)` + 원문 hash
- [ ] 9.4 단가·수량·운임·세금 차이 → task, credit 요청 초안
- [ ] 9.5 invoice 안의 새 계좌·wallet 정보는 beneficiary를 바꾸지 못함

Gate: 같은 invoice가 이메일과 업로드로 두 번 들어와도 1건. 실제 3회 이상 전체 cycle(추천→PO→확인→입고→invoice) 추적.

**🎯 YC 데모 gate (CP1–CP9)**: 실제 데이터 읽기 → 한 SKU 보충량 설명 → supplier별 PO → owner 승인 → 접수 추적 → 부분 입고 차이 표시. 실제가 아닌 부분은 demo/sandbox 표시.

---

## CP10 — Owner 화면 `[UI-01]` (CP5부터 각 CP와 함께)

- [ ] 10.1 TanStack Query 도입, `data.ts`의 output JSON import 제거 → live API, demo fixtures는 별도 모드
- [ ] 10.2 메뉴: Today / Inventory / Orders / Suppliers / Bills / Connections, Settings
- [ ] 10.3 `ActionChip`(이벤트 없는 span) → loading/disabled/success/error 버튼, 발주·지급은 낙관적 성공 표시 금지
- [ ] 10.4 Today: 오늘 결정할 주문, 미확인 supplier, 늦은 입고, invoice 차이, stale/연결 끊김/budget 초과
- [ ] 10.5 추천 상세: 근거 수치, 총 승인 금액, 수정 사유 선택
- [ ] 10.6 모바일 카드+하단 승인, 데스크톱 고정 열+drawer, 접근성(키보드·focus·label)
- [ ] 10.7 첫 화면에서 agent transcript, token 수, chain, raw JSON, confidence %, ecosystem 점수 제거
- [ ] 10.8 simulation/YHack 화면은 `archive/demo`로 분리

Gate: 모든 버튼이 실제 상태·권한과 연동. 상태는 색+텍스트.

---

## CP11 — 운영 신뢰성 `[OPS-01]`

- [ ] 11.1 구조화 log + trace ID (connector → PO → provider)
- [ ] 11.2 durable queue(SQS 등) + DLQ + 재처리 도구, raw event replay
- [ ] 11.3 데이터 freshness 기준 초과 시 자동 발주 중지
- [ ] 11.4 DB backup + 복구 연습
- [ ] 11.5 credential revoke·재연결, prompt/log에 credential 금지
- [ ] 11.6 merchant export·계정 해제

Gate: 실패 event를 DLQ에서 재처리해 복구. 백업에서 실제 복원 1회.

## CP12 — SaaS 구독 `[PAY-01]`

- [ ] Stripe Billing/Checkout, 물품 대금과 완전 분리, webhook 서명 검증으로만 상태 변경

## CP13 — 제한 자동화 (Autopilot)

- [ ] approved supplier/SKU, 주문당·주간 한도, 단가 변동 한도, stale/신규 계좌/미확인 PO 시 중지 → task
- Gate: 장애·중복·가격 변경 시 멈춤 검증, 몇 차례 정상 발주·입고 이후에만 활성화

## CP14 — 확장

- [ ] `[ACC-01]` QuickBooks 기록 export (재고 이중 반영 없음)
- [ ] 두 번째 POS (Shopify: GraphQL, bulk ops, `read_all_orders` 승인 전 CSV 보완)
- [ ] `[PAY-02]` supplier 지급 adapter (명세 11.6 계약) ⏳ 외부
- [ ] `[PAY-03]` 국제 stablecoin 파일럿 ⏳ 외부

---

## 출시 전 필수 실패 시나리오 (명세 19.2) → 담당 CP

| 시나리오 | CP |
|---|---|
| 같은 판매 webhook 10회, 환불이 판매보다 먼저 | CP4 |
| 같은 PO 동시 승인 | CP6 |
| 주문 제출 후 timeout, 실제로는 접수됨 | CP7 |
| 10상자 중 8 입고, 1 손상, 나머지 backorder | CP8 |
| 12입 → 24입 변경 | CP2, CP7 |
| 승인 뒤 단가·운임 상승 | CP6 |
| 같은 invoice 이메일+업로드 | CP9 |
| ACH 반환 | CP14 |
| supplier 문서 속 새 계좌·지시문 | CP7, CP9 |
| POS 권한 취소, webhook 장기 유실, Sheets 열 이동 | CP3, CP4 |
| scheduler와 수동 실행 동시 계산 | CP5 |
| tenant A agent가 tenant B PO ID 제출 | CP1 (기반), CP6 |
