# Tabula 구현 체크포인트

기준 문서: 「Tabula — 소상공인 재고 보충·발주 자동화 제품 및 기술 명세」(2026-10-20), 저장소 기준 커밋 `d6335bf`.

규칙

- 체크포인트는 **완료 기준(gate)을 테스트나 실제 데이터로 통과해야** 닫는다. 날짜보다 gate가 우선이다.
- 각 항목의 `[ID]`는 명세 19.1 백로그 ID다.
- 상태: `[ ]` 미착수 · `[~]` 진행 중 · `[x]` gate 통과
- 외부 의존성(앱 심사, 공급업체 협조, 결제 provider 승인)은 `⏳ 외부`로 표시하고 코드 일정과 분리한다.
- 데모/샘플 데이터는 항상 `demo` 배지로 실제 데이터와 분리한다.
- 검증 수준은 네 단계로 따로 적는다: **구현 완료** (코드·테스트) · **mock 검증** (mock provider / capture 전송) · **Sandbox 실호출 검증** · **실제 고객 검증**. 앞 단계가 끝났다고 뒤 단계를 완료로 쓰지 않는다.

## 사용자 조치 체크리스트 (코드로 끝낼 수 없음 — 제공사에서 폐기 확인 전에는 완료 표시 금지)

- [ ] U1 OpenClaw gateway 토큰 폐기·재발급 (`docs/SECURITY.md` 3절 순서: 새 값 발급 → 실행 중 서비스 교체 → 옛 값 폐기)
- [ ] U2 기기 identity 키(Ed25519) 재생성, 옛 기기 등록 해제
- [ ] U3 operator 토큰 폐기·재발급
- [ ] U4 노출된 세션 기록·개인 전화번호 영향 확인
- [ ] U5 Git 이력 재작성·force push 여부 결정 (지금은 **하지 않음**, `docs/SECURITY.md` 4절)
- [ ] U6 Square Developer 계정 + Sandbox 앱 등록, 환경변수 설정 (`docs/SQUARE_SETUP.md`) → CP4 Sandbox 실호출 검증

진행 순서 요약

```
CP0 고객·데이터 확인 (사람 작업, CP1과 병행)
CP1 운영 기반 ──► CP2 카탈로그·단위 ──► CP3 CSV/Sheets 수입 ──► CP5 보충 엔진 ──► CP6 PO·승인
                                  └──► CP4 첫 POS 커넥터 (⏳ 앱 심사와 병행) ──┘
CP6 ──► CP7 공급업체 회신·확인 ──► CP8 입고 ──► CP9 Invoice 대조   ← YC 데모 gate
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


## [~] CP4 — 첫 POS 커넥터 (Square) `[CON-01] [CON-02]` — 구현 완료 · mock 검증 · ⏳ Sandbox 실호출 미검증(U6) · 실제 고객 미검증

**운영 전 필수:** D1–D5·D8의 Sandbox 실호출 검증. 4.2b·4.6·4.8a·환불 규칙은 구현·mock 검증까지 했다. Sandbox에서 실제 응답 형식(특히 환불 order와 재입고 기록)을 확인하기 전에는 Square를 실제 매장의 판매 출처로 켜지 않는다.


Sandbox 개발과 App Marketplace 등재 심사는 별개다(`docs/SQUARE_SETUP.md`). 심사를 기다리지 않는다.

- [x] 4.1 connector 계약(`clawbot/connectors/base.py`)과 실제 지원 기준의 `capabilities` (CP4: sales/inventory/catalog read만)
- [x] 4.2 OAuth: 단일 사용·10분 만료 state(교환 실패해도 재사용 불가), token Fernet 암호화 저장, revoke. production은 `TABULA_ENV=production`에서만
- [x] 4.2b access token refresh job — mock 검증, Sandbox 미검증 (D2)
- [x] 4.3 위치는 사람이 하나씩 연결(자동 합산 없음), 연결된 위치의 재고 소유자 = square
- [x] 4.4 backfill: catalog(매핑 **제안**만, 미일치 상품은 사람이 adopt), 완료 주문 판매·환불(Square UID key), 재고 snapshot, 동기화 기간을 sales coverage로 기록
- [x] 4.5 webhook: 서명 검증 → 원본 저장(event_id 중복 제거) → outbox job → Square 최신 상태 재조회
- [x] 4.6 변경분 polling + 야간 재대조 스케줄 (webhook 유실 복원) — mock 검증, Sandbox 미검증 (D3)
- [x] 4.7 POS 소유 위치는 snapshot 경로로만 갱신
- [x] 4.8a 판매 원본 소유권: 위치별 files/square + 전환 시각 (D4). 같은 주문이 두 경로로 오면 여전히 검토 대상(백스톱)
- [x] 4.8 판매는 `key_scheme=provider_line`, 같은 주문이 CSV로 이미 있으면 이중 집계 없이 검토 대상
- [x] 4.9 mock Square(`clawbot/connectors/square/mock.py`)로 전체 흐름 테스트, 재시도(429/5xx)·페이지네이션 포함

Gate: 실제 계정 표본의 거래·재고·환불이 원본과 일치(**Sandbox 계정 필요 — 미검증**). webhook을 일부러 누락시켜도 polling으로 복원(4.6 미완). 같은 webhook 반복 수신 → 1회 처리(테스트 통과).

---

## [~] CP5 — 보충 엔진 (결정적 계산) `[PLAN-01]` — 구현 완료 · 독립 리뷰 2회 반영 · 합성 데이터로만 검증 · 5.7 backtest와 실제 고객 데이터 미검증

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

Gate: 명세 7.3 예시(5상자, 품절 1일) 통과(엔진 단독 + import 경유). boundary: 납기 0일, 기한 지난 ETA, 계획 기간 밖 입고, 판매 데이터 공백, 실사 후 파손, 과거 시점 run, 공급업체 선택 — 테스트 통과. scheduler·수동 동시 실행 → 현재 계획 1개. 독립 리뷰 2차 반영: 미확인 열린 주문 때문에 0이 된 줄은 `on_hold`(원래 필요량·미확인 수량·보류를 따로 표시), 주문일·배송일(그날 영업 종료)·판매 가능일을 줄마다 명시 + lead 4 → 5일째 판매 가능 경계 테스트, 상자당 단가·가격 출처 표시, 판매 기간은 import에서 선언한 기간만 coverage로 인정(출처별), 실사 기준 재고는 `counted_qty`로.

남은 한계(명시): 시각 기준 `newer_data_since`는 보조 표시일 뿐이고, 판정 기준은 `tenant_data_versions`(입력 쓰기마다 같은 transaction에서 증가, 행 잠금으로 commit 순서대로 증가)다. 품절일 제외는 0재고 snapshot이 찍힌 날만 → 재고 이력 재구성은 CP5.x.

---

## [~] CP6 — PO·승인 (capture 전송) `[PO-01] [PO-02]` — 구현 완료 · mock(capture) 검증 · 독립 리뷰 1회 반영 · 실제 공급업체/고객 미검증

- [x] 6.1 `purchase_orders`, `po_revisions`(불변, 내용 sha256 digest), `po_approvals`(PO·revision당 1개), `po_send_attempts`, `captured_messages` (migration 0009). line은 revision 스냅샷 안에 있음 — line별 확인·입고 수량 테이블은 CP7/CP8
- [~] 6.2 상태: draft → awaiting_approval → queued → test_sent / failed, cancelled. 명세의 sent·supplier_confirmed·partially_received·received·closed·cancel_requested는 CP7/CP8에서
- [ ] 6.3 line별 confirmed/received/rejected/cancelled/outstanding → CP7/CP8
- [x] 6.4 승인은 revision + digest(수량·단가·가격 ID·포장·supplier item version·수취인·배송지·합계·당시 추천)에 묶임. 수정·새로고침 = 새 revision → draft → 다시 승인. 정책 version 묶기는 계획 run을 통해 간접적(추천 스냅샷) — 자동화 정책 version은 CP13
- [~] 6.5 승인 기록 + 상태 + outbox job + audit를 한 transaction으로 (budget 예약은 budget 기능과 함께 CP13)
- [ ] 6.6 legacy `universal_agent.py`의 "confirmed" 반환 교체 → CP6.10과 함께
- [x] 6.7 API: `GET /v1/purchase-orders[/{id}]`, `POST …/from-run`, `PATCH …/{id}/lines`, `POST …/refresh|submit|approve|cancel`. 전송은 승인 시 outbox로 자동 예약(별도 `/send` 없음), `/cancel-request`는 CP7(보낸 뒤 취소는 공급업체 응답 필요)
- [x] 6.8 line 스냅샷: supplier_item version, order_uom, units_per_order_uom, price ID·유형·출처·기준("30 USD per case of 12"), 통화. 이후 가격·포장 변경 → 승인 거부("refresh it")
- [~] 6.9 중복 방지는 고유 키로: 승인 `(po, revision)`, 전송 `po:{id}:rev:{n}:send`, 초안 생성은 (tenant, 위치) advisory lock + 품목당 활성 PO 1개. 일반 Idempotency-Key 저장소는 아직 없음
- [ ] 6.10 legacy procurement agent를 PO 도메인 + 확정 supplier_items로 전환 (CP2.8b)
- [x] 6.11 승인 요청에 화면의 revision + digest를 보내야 함 → 다르면 409
- [x] 6.12 owner만 승인: 권한 표(domain) + API 양쪽, manager 승인 403 (테스트 + 브라우저)
- [x] 6.13 데이터 신선도: 승인 시 `tenant_data_versions`를 share lock으로 읽고(진행 중 쓰기 commit까지 대기), PO 숫자를 만든 version과 다르면 계획 재계산 → 추천이 움직였으면 409. 진행 중 import·실행 중 sync가 있으면 승인 대기(재시도 대기 중 job은 막지 않음). **전송 직전에도 다시 확인**(조건·수취인·공급업체 상태·추천) → 다르면 failed + 이유, 새로고침 후 재승인. 새로고침은 추천을 다시 계산해 "주문 5 / 추천 7"을 보여주고 사람이 결정
- [x] 6.14 전송 결과 불명(worker 중단·lease 만료) → PO가 Queued로 남지 않음: capture가 기록됐으면 test_sent, 아니면 failed("outcome unknown, nothing was sent")
- [x] 6.15 브라우저 흐름 (`demo-ui/src/ops/*`, TanStack Query, 실제 `/v1` + Postgres): import 검토·확정 → 계획(보류·날짜·근거) → 공급업체별 초안 → 수량 수정 → 제출 → owner 승인 → capture 결과·실행 기록. 새로고침 후 상태 유지, loading/empty/error 상태. 화면 캡처 `docs/screenshots/cp6/`, 재현 스크립트 `scripts/ui_walkthrough.py`

Gate: 서버 재시작 뒤 승인 상태 유지(DB가 기준) ✓. 두 사람 동시 승인 → 승인 1·outbox 1 ✓(테스트). 승인 뒤 단가 변경 → 재승인 필요 ✓. 승인 뒤 입력 변경으로 추천이 움직이면 전송 차단 ✓. **실제 공급업체 전송은 이 빌드에서 거부**(`live` 모드 refused, transport 없음) — 실제 발송은 CP7에서 수신 확인 페이지·결과 불명 처리와 함께.

남은 한계(명시):
- ~~계획이 Tabula PO를 세지 않음~~ → CP7.11에서 해결.
- ~~승인 재계산이 위치의 현재 계획을 바꿈~~ → 해결: 새로고침·승인·전송 검사는 저장하지 않는 계산(`service.evaluate`)을 쓰고, 매장 계획(Today)은 사람이 재계산할 때만 바뀐다. PO 화면은 "이 주문의 자체 검사"로 따로 표시.
- 동시 초안 테스트는 경쟁 조건 기반이라 lock을 빼도 매번 실패하지는 않는다(3회 중 2회 실패 확인).

---

## [~] CP7 — 공급업체 회신·확인 `[SUP-01]` — 구현 완료 · mock/붙여넣기/파일 회신으로 검증 · 실제 공급업체 미검증 · 실제 발송 없음(capture)

- [~] 7.1 PO 본문·CSV 첨부 생성 + capture 저장 (CP6). **실제 이메일 전송은 없음** — 아래 "실제 발송 전 필수" 참고
- [x] 7.2 전송 결과 불명: capture는 DB로 확인 가능(capture 기록 = 전송, 없음 = 미전송). **그 밖의 transport는 worker가 넘긴 뒤 죽으면 `delivery_unknown`**: 자동 재전송 없음(outbox `unknown` 유지), 계획은 수량을 계속 보류, owner가 공급업체 확인 후 "받지 못함"으로만 해제 (`supplier_contact.outcome_verifiable`, 테스트는 비검증 transport를 흉내 냄)
- [ ] 7.3 공급업체 확인 페이지(만료 링크·POST+nonce) — 지금은 회신을 사람이 Tabula에 넣는 방식만
- [x] 7.4 회신 해석: 전체 수락 / 부분 수락(나머지 거절 또는 backorder) / 품절 / 가격 변경 / 납기 변경 / 대체품 / 초과 수량 / 잔량 취소. 결정적 parser(LLM 없음), 줄마다 원문 근거(줄 번호), 인용된 원 PO 줄은 무시. 입력: mock 회신(capture 모드 전용, 표시됨), 이메일 붙여넣기, .txt/.eml(Date 헤더)/.csv 업로드
- [x] 7.5 가격·상품·포장·초과 수량 변경은 바로 반영하지 않고 line `proposal` → **owner만** proposal digest에 묶어 수락/거절. 대체품은 확정된 supplier item이어야 수락 가능(새 line, 원래 line은 거절). 수락 전에는 보류(입고 예정 아님)
- [x] 7.6 상태 분리: 발송(test_sent / delivery_unknown) ≠ 공급업체 응답(`ack_status` pending/accepted/partially_accepted/counteroffer/rejected) ≠ 입고. capture 성공을 수락으로 처리하지 않음
- [x] 7.7 회신 안의 문장은 데이터로만 처리 (실행·지시 따름 없음)
- [x] 7.10 같은 회신 원문 = 같은 회신(sha256 고유), 확정 수량은 절대값 → 두 번 적용해도 변화 없음. 공급업체 시각이 이미 적용된 회신보다 오래된 회신은 적용 불가(`stale`)
- [x] 7.11 Tabula PO를 보충 계산에 연결: 초안(미발송)은 입고 아님·같은 품목 재초안만 막음 / 발송 후 미확인 = 재주문 보류, 도착 예정 아님 / 확인 = 확정 수량·ETA로 도착 예정 / 입고분은 잔량에서 제외 / 거절·취소는 그 수량만 빠지고 재계산. 화면: "On hold — already ordered", "Covered by incoming order", "Enough stock" 구분, 계획 단계에 PO 번호 표시
- [ ] 7.8 실제 발송 시 검증된 수취인 재확인은 CP6 전송 직전 검사로 구현됨 — 실제 transport 연결 시 재검토
- [ ] 7.9 outbox `unknown` → owner task 목록(CP10 Today) — 지금은 PO 화면의 delivery_unknown 안내

독립 리뷰 1회(사용 한도로 한 번 중단 후 재개) 반영: 제안된 변경(가격·포장·대체·초과)을 manager가 "수락"으로 바꿔 owner 결정을 건너뛰던 결함 → owner만 가능·기록, 대체품 수락 뒤 "all confirmed" 회신·같은 메일 재붙여넣기로 이중 계산 → 대체된 line 제외·원문 정규화 hash, 시간·PO 번호·가격·"in 2 days"를 수량으로 읽던 parser → 단위어/확인 동사 옆 숫자만, 초과 수량 거절 시 line 전체 거절 → 주문 수량 유지, 날짜 없는 붙여넣기 회신 순서 → 공급업체 시각 필수, 결과 불명 판단을 재시작 시점 mode로 하던 것 → claim 시 mode 기록, 닫힌 Tabula PO가 오래된 export로 되살아남 → 보낸 적 있는 모든 PO와 대조, 미응답 line의 확정 교체품 → 도착 예정으로.

Gate: 실제 공급업체 1곳이 실제 PO 1건을 확인 — **미검증(⏳ 외부, 실제 발송 금지 상태)**. 이메일 보안 스캐너 링크 문제는 확인 페이지(7.3)와 함께.

**실제 발송을 켜기 전 필수 (capture 개발은 막지 않음):**
- [ ] L1 예산 예약(주문당·주간 한도)을 승인과 같은 transaction에
- [ ] L2 승인 정책 version을 승인 digest에 묶기
- [ ] L3 실제 transport adapter(이메일/API) + delivery_unknown 운영 절차 + 공급업체 확인 페이지(7.3)
- [ ] L4 일반 Idempotency-Key 저장소(6.9)
- [ ] L5 legacy agent 경로 정리(6.6/6.10) — 실제 발송 경로는 PO 서비스 하나뿐임을 보장
- [ ] L6 독립 보안 리뷰 + `docs/SUPPLIER_CONTACT_POLICY.md` 개정 승인(사용자 결정)

---

## [~] CP8 — 입고 `[REC-01] [UI-02]` — 구현 완료 · 브라우저·테스트 검증(합성 데이터) · 실제 매장 미검증

- [~] 8.1 `receipts, receipt_lines` (receipt_key로 재전송·두 탭 동시 제출 = 같은 입고). verified/corrected 단계와 입고 수정은 아직 없음
- [x] 8.2 도착·손상·판매 가능·잔량: 10 주문 → 8 도착(1 손상) → 판매 가능 7 · 손상 1 · 잔량 2. 예상보다 많은 도착은 거절(초과분 처리 흐름 없음). 손상분 = `receipt_issues` open → 공급업체가 확인한 교체만 입고 예정에 추가(credit / write-off는 추가 없음)
- [x] 8.3 Tabula 소유 위치: 판매 가능 수량만 원장 `receipt` 이동 1회(receipt line key). **POS 소유 위치(Square, 읽기 전용)**: 원장에 쓰지 않고 `pending_pos` → "POS에 입력함" 표시 → POS 재고 reading(그 뒤 시각)이 오면 해소. 그 전에는 화면에 재고 불일치 표시 + 그 품목이 든 PO는 제출·승인·전송 차단(`stock_not_confirmed_in_pos`)
- [ ] 8.4 모바일 Receiving(scan) — 지금은 데스크톱 폼
- [ ] 8.5 실측 lead time 기록

Gate: 10상자 중 8 입고·1 손상·잔량 2 시나리오에서 잔량·재고 정확, 재고 1회 게시 ✓(테스트·브라우저). 동시 입고는 PO 행 잠금으로 직렬화(잠금을 쥔 채 순서를 제어한 재현 테스트) ✓.

---

## 연결·데이터 항목별 상태 (mock 검증과 Sandbox 실호출 검증을 따로 적는다)

| ID | 항목 | 구현 | mock 검증 | Sandbox 실호출 | 비고 |
|---|---|---|---|---|---|
| D1 | Square 실제 인증·상품·재고·주문 가져오기 | ✓ | ✓ | ✗ | U6(계정·설정) 후 `scripts/square_sandbox_check.py` |
| D2 | token refresh (만료 7일 전, 거부 시 needs_reauth) · 연결 해제·재연결(위치 연결 유지) | ✓ | ✓ | ✗ | |
| D3 | 정기 동기화(판매 15분·재고 30분) + 야간 최근 3일 재대조(누락 복구 수 기록) | ✓ | ✓ | ✗ | connector worker가 1분마다 예약, 시간 칸(slot) 단위로 1회만 |
| D4 | CSV ↔ Square 판매 원본 소유권·전환 | ✓ | ✓ | 해당 없음 | 위치별 전환 이력(구간). 판매 시각의 소유자만 기록 가능, 과거 구간 재작성 불가, 겹치면 전환 거부. 이미 Square 판매가 있던 위치는 migration에서 첫 Square 판매 시각부터 square로 채움 |
| D5 | 환불·반품 → 판매량·재고 | ✓ | ✓ | ✗ | 환불은 수요 감소, 재입고 확인된 환불만 재고 증가, Square 환불은 재입고 "모름" |
| D6 | 실제 고객 데이터 검증 | 도구 ✓ | — | — | **고객 데이터 없음.** `docs/CUSTOMER_DATA_REQUEST.md`, 익명화·비교 도구 준비 |
| D7 | Square 재고 쓰기(입고 반영) | ✗ | — | — | 읽기 전용 유지. 입고는 사람이 POS에 입력 → 증거를 보고 대조 완료 |
| D8 | webhook 실제 수신(서명·중복) | ✓ | ✓ | ✗ | 공개 HTTPS 터널 필요 |

### 미입고 주문 export ↔ Tabula PO 연결 (CP7.12)

- [x] 연결 식별자는 **공급업체 + 주문 번호뿐**이다. 상품·수량이 같다는 이유로는 합치지 않는다.
- [x] 공백·대소문자만 다른 같은 번호는 자동으로 같은 주문으로 보고, Tabula 쪽 줄로 한 번만 센다.
- [x] 구두점·앞자리 0만 다른 번호("PO00080", "80" ↔ "PO-00080")는 **제안**으로 둔다.
  - 사람이 "같은 주문 / 다른 주문"을 결정하기 전에는 세지 않는다.
  - 그동안 해당 품목 계획에 검토 사유가 붙고, Today의 "Needs your attention"에 표시된다.
- [x] 결정은 기록된다(누가·언제·메모). 같은 주문으로 연결할 수 있는 것은 보낸 적 있는 같은 공급업체·같은 위치의 PO뿐이다.
- [x] 닫히거나 실패한 PO의 번호도 대조한다. 오래된 export가 끝난 주문을 되살리지 않는다.

### POS 소유 위치의 입고 대조 (CP8.3 개정)

- [x] 더 새로운 POS 재고 reading이 들어왔다는 이유만으로 불일치를 해제하지 않는다.
- [x] 증거를 계산한다. 입고 전 reading, 입력 후 첫 reading, 그 사이 판매·재입고 환불·재입고 여부 모르는 환불·다른 입고, 예상치, 설명되지 않는 차이를 보여준다.
- [x] 판정 종류: consistent / consistent_if_refunds_not_restocked / explained_if_refunds_restocked / receipt_missing_in_pos / difference / no_reading_before / no_reading_after.
- [x] owner·manager가 "POS가 맞음 / POS에서 고쳤음 / 차이 수용" 중 하나로 대조를 완료한다.
  - 증거가 consistent가 아니면 메모가 필수다.
  - 증거와 결정을 함께 저장한다.
- [x] 미해결 항목은 Today의 "Needs your attention"에 경과 일수와 함께 계속 보인다. 조용히 해제되지도, 영원히 막히지도 않는다.

독립 리뷰 1회 반영 (store-readiness):
- 입고와 같은 시각의 POS reading이 그 입고를 가려 "consistent"가 되던 결함 → 이 입고는 항상 계산에 넣는다.
- 판매 원본을 되돌리면 상대 구간이 다시 열려 이중 집계되던 결함 → 전환 이력 구간으로 관리한다.
- 익명화 blocklist가 Billing/Shipping Name·PAN 등을 통과시키던 문제 → allowlist로 바꾸고 개인 열은 `--keep`으로도 유지 불가.
- 기존 Square 위치가 migration 후 동기화를 멈추던 문제 → 첫 Square 판매 시각부터 square로 채움.
- 과거 시각으로 전환하면 생기던 동기화 공백 → 동기화 기준점을 되감음.
- 동시 token refresh가 잘못된 재연결을 요구하던 문제 → 계정 행 잠금.
- 숫자만 같은 다른 번호 체계의 제안 → 접두 문자가 같거나 한쪽에 없을 때만 제안.
- nit: 연결 결정 동시 첫 결정 upsert, 위치별 import 표시, 판매 원본별 다음 행동 링크, refresh token 없는 계정 반복 예약 제거, 재대조 하루 여유, sandbox 점검은 그 계정만, 비교 도구 미래 시각 방지.

### 매장주 혼자 쓰기 (온보딩)

- [x] Today 맨 위 "Needs your attention": 데이터가 오래됨·없음, 계획이 낡음, 보류 품목, 승인 대기, 공급업체 변경 제안, 전송 결과 불명, 미응답, 지연 입고, 회신 검토, POS 대조, 손상, 연결 오류를 표시한다. 항목마다 이유와 다음 행동 링크가 있다.
- [x] 판매 import 미리보기가 파일 안의 첫·마지막 판매일을 제안한다(사람이 확인). 기준 시각 입력에 "Now" 버튼을 둔다.
- [x] 데모 매장 버튼(개발 모드 전용, 비개발 환경은 404): seed 출력에서 날짜를 찾아 넣는 절차 없이 계획부터 시작한다.
- [x] Connections 화면: 연결 상태·환경(mock/sandbox)·토큰 만료·위치 연결·판매 원본 전환·동기화·재대조 이력·해제.

## [~] Owner 앱 (가입 → 매장 → 데이터 → 재고 → 바코드 → 분석 → 발주 추천 → 승인) — 구현 완료 · 브라우저·API·DB 검증(합성 파일) · 실제 고객 미검증

검증 단계: **구현 완료** = 코드·테스트 있음 / **mock 검증** = 가짜 외부 서비스로 확인 / **Sandbox 실호출** = 제공사 테스트 계정으로 확인 / **실제 고객** = 실제 매장 데이터·사용.

| 영역 | 구현 | 브라우저·API·DB 확인 | Sandbox 실호출 | 실제 고객 | 남은 한계 |
|---|---|---|---|---|---|
| 계정·세션 (이메일+비밀번호, HttpOnly 쿠키, CSRF 헤더, 5회 실패 15분 잠금, 매장별 권한) | ✓ | ✓ | 해당 없음 | ✗ | 이메일 인증·비밀번호 재설정 없음. 팀 초대는 1회용 링크(14일, hash만 저장) — 링크 없이는 그 이메일로 가입 불가. 초대 메일 발송 없음(owner가 링크 전달) |
| 데모 로그인 분리 (dev 모드 + loopback만, password 모드에서 거부) | ✓ | ✓ | 해당 없음 | — | |
| 매장 생성 (이름·업종·시간대·통화 → 위치 생성 → 데이터 연결로 이동) | ✓ | ✓ | — | ✗ | |
| 샘플 매장 (계정 소유, 어디서나 "sample" 표시, 실제 매장과 분리) | ✓ | ✓ | — | — | |
| Excel/CSV 가져오기 (열 자동 매칭, 사용 안 하는 열과 이유, 필요한 질문만) | ✓ | ✓ | — | ✗ | |
| Google Sheets (공개 공유 링크 1회 읽기, docs.google.com만, 리디렉트 검사) | ✓ | 테스트(가짜 전송)만 | ✗ 실제 시트 미확인 | ✗ | OAuth·정기 동기화 없음 |
| Square 상태 표시 (정직한 "demo connection" / 필요한 설정 이름) | ✓ | ✓ (mock) | ✗ (U6) | ✗ | |
| 데이터별 가능 기능 (재고 / 추세 ≥7일 / 발주 추천 ≥14일+재고 / 발주: 승인된 공급업체·단가·주소) | ✓ | ✓ | — | ✗ | |
| 홈·재고 목록·품목 상세 (데이터 기준 시각, 24시간 넘으면 오래됨 표시, 추정치 표시) | ✓ | ✓ (데스크톱·휴대폰 폭) | — | ✗ | |
| 바코드 (스캐너·입력, 카메라는 BarcodeDetector 지원 브라우저만, 동작·수량 선택 후에만 변경, 미등록 바코드 추가·연결, 기록·되돌리기, Square 소유 재고는 읽기 전용) | ✓ | ✓ | — | ✗ | 실제 스캐너 기기·휴대폰 카메라 미확인 |
| 분석 (기간 비교는 데이터 있는 날 기준, 없는 날은 0이 아님, 잘 팔림/안 팔림, 품절 예상) | ✓ | ✓ | — | ✗ | |
| 발주 추천 → 수량 수정 → 초안 (기존 엔진, 배수·최소 수량 서버 검사) → owner 승인 | ✓ | ✓ | — | ✗ | 전송은 test mode(capture) 유지 |

- 완료 기준 경로(`scripts/ui_walkthrough_owner.py`): 새 계정 가입 → 매장 생성 → 자기 재고·판매 파일 → 재고 확인 → 바코드로 1건 조정 → 분석 → 공급업체 등록 → 발주 추천 수량 수정 → 초안 → 승인(test mode). 화면 `docs/screenshots/owner-app/01–24`.
- 기존 흐름도 새 화면으로 다시 확인: `scripts/ui_walkthrough.py`(회신·입고·다른 매장 404·manager 승인 403), `scripts/ui_walkthrough_store.py`(샘플 매장·주문 번호 연결·Square demo 입고 대조).
- 실제 공급업체 전송과 결제는 꺼져 있다. 새 커넥터·결제 기능은 추가하지 않았다.

독립 리뷰 1회 반영 (owner 앱):
- **blocker** 초대된 이메일을 먼저 가입한 사람이 매장 권한을 가져가던 문제 → 1회용 초대 링크(`invitations`, migration 0013). 링크 없이 store 권한이 있는 이메일로 가입하면 거부. owner 역할은 초대로 줄 수 없음.
- 샘플 매장: 서버에서 계정당 1개, 동시에 1개만 생성, 실행마다 별도 임시 폴더, 모든 import가 끝난 뒤에만 소유권 이전(실패 시 반쪽 매장 없음), 데모 manager 추가 안 함, 시간 초과는 504 안내.
- 수량 확인(count) 되돌리기가 재고를 부풀리고 "방금 확인"으로 보이던 문제 → count는 되돌리지 않고 다시 세도록 안내. 이후 count가 있는 변경도 되돌리기 거부.
- 한 번도 센 적 없는 품목이 스캔 1건 후 "방금 확인"으로 보이던 문제 → `stock_counted` 노출, "not counted yet" 표시·오래됨 처리. readiness는 count·재고 보고서만 재고 데이터로 인정.
- 같은 request_key에 다른 수량·동작 → 409(조용히 무시하지 않음).
- 분석: 데이터가 완전하지 않은 날의 판매는 합계·그래프에서 제외. 가격 없는 판매가 하나라도 있으면 매출 미표시(개수 안내).
- "Stock No." 같은 번호 열이 수량으로 자동 매칭되던 문제 → 느슨한 매칭은 식별자 필드에만.
- Google Sheets: 10MB 넘으면 즉시 중단(스트리밍), https만, gid 숫자만, Google 로그인으로 리디렉트되면 "공개 공유 아님" 안내, 가져오는 동안 DB transaction을 열어 두지 않음.
- 로그인 실패 메시지 통일(잠금이 계정 존재를 드러내지 않음). 세션 쿠키는 dev 모드 외에는 기본 Secure.
- 남은 것: 샘플 매장은 여전히 별도 프로세스의 seed(외부에서 접근 불가한 in-process dev 인증)로 만든다. IP별 로그인 제한 없음(5회 실패 잠금만). 품목 상세 차트는 부분 데이터 날도 기록된 판매를 그대로 보여준다.

## [~] 매장주 UI 재설계 (정보 구조·우선순위) — 구현 완료 · 브라우저·API·DB 확인(합성·샘플 데이터) · 실제 매장주 사용성 미검증

- 메뉴: Overview / Inventory / Orders / Insights + Settings. Scan은 Inventory의 주 버튼, Suppliers는 Orders의 탭, 데이터 연결·매장·팀은 Settings. 예전 주소는 새 위치로 이동(redirect).
- 신규 매장은 `/app/setup` 체크리스트(재고 → 판매 → 공급업체·가격 → 배송 주소)로 시작, 상품이 있으면 Overview로 바로.
- Overview: 매장명·마지막 갱신 시각·"Review reorder plan" → 요약 3개(재고 부족, 검토할 주문, 입고 예정) → 우선순위 발주 표(현재 재고, 소진일, 추천 수량·케이스, 예상 비용, 공급업체; 저장하지 않는 같은 엔진 계산) → 진행 중 주문과 예상 도착일 → 할 일. 데이터가 없으면 숫자 대신 다음 행동(예: "Add a supplier", "Import sales history").
- Orders: 검토 필요 / 진행 중 / 완료 탭(공급업체, 금액, 상태, 예상 도착일, 다음 행동). 예상 도착일은 공급업체 날짜가 있으면 그 날짜, 없으면 리드타임 추정으로 표시하고 "estimate / if sent today"라고 밝힌다.
- 주문 상세: 품목·수량·비용·배송이 먼저. 추천과 다른 수량, 가격·검토 알림은 항상 보임. 계산 근거·보관된 이메일·승인/전송·이력은 접어 둠. 실제 전송 여부: "Test mode: approving keeps this order in Tabula" / "Test order — not sent".
- Inventory: 표(상품, 판매 가능, 입고 예정, 소진일, 상태) + 상세 패널(바코드, 공급업체별 단가, 판매·예상 재고 차트, 변경 이력, 주문). Scan: 작업 모드 먼저 선택, 저장 시 이전 → 이후 표시.
- 디자인: 중립 배경, 흰 작업 영역, 짙은 글자, 강조색 하나(파랑), 상태 색은 품절·소진 임박·문제에만. 테스트 모드는 사이드바 한 곳 + 결정이 걸린 주문 화면에서만, 샘플 매장은 얇은 상단 줄 한 곳.
- API 추가: `/v1/stock/overview` 행의 `reorder`, `/v1/items/{id}/history`의 `suppliers`, `/v1/purchase-orders` 목록의 `expected_at`/`expected_source`. 테스트 추가.
- 확인: `scripts/ui_walkthrough_owner.py`(가입 → 온보딩 → Overview → 패널 → 스캔 → 공급업체 → 발주 계획 → 초안 → 승인, 26장), `ui_walkthrough.py`, `ui_walkthrough_store.py` 모두 새 화면으로 통과.
- 한계: 실제 매장주 사용성 테스트 없음. 접근성 점검(스크린리더·키보드 전체 경로) 미실시. 차트는 단순 SVG.
- **독립 리뷰 미완료**: 리뷰 에이전트가 네트워크 오류 후 사용량 한도로 중단(2026-10-22). 리뷰되지 않은 범위: 새 화면 전체(`app/Overview.tsx`, `app/Orders.tsx`, `ops/OrdersPage.tsx`, `app/Inventory.tsx`, `app/Scan.tsx`, `app/Setup.tsx`, `ops/kit.tsx`)와 API 추가 필드(`stock_view.overview` reorder, `item_history` suppliers, PO 목록 expected_at). 한도 해제 후 같은 리뷰를 이어서 실행할 것.

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

- [~] 10.1 TanStack Query 도입, `data.ts`의 output JSON import 제거 → live API, demo fixtures는 별도 모드 — `/app/*` 매장주 화면 전부 live API(Owner 앱), legacy 화면은 `/legacy/*`에 그대로
- [~] 10.2 메뉴: Overview / Inventory / Orders / Insights + Settings (Scan은 Inventory, Suppliers는 Orders 안; Bills는 CP9 이후)
- [ ] 10.3 `ActionChip`(이벤트 없는 span) → loading/disabled/success/error 버튼, 발주·지급은 낙관적 성공 표시 금지
- [ ] 10.4 Today: 오늘 결정할 주문, 미확인 supplier, 늦은 입고, invoice 차이, stale/연결 끊김/budget 초과
- [ ] 10.5 추천 상세: 근거 수치, 총 승인 금액, 수정 사유 선택
- [~] 10.6 모바일 카드+하단 승인, 데스크톱 고정 열+drawer, 접근성(키보드·focus·label) — 휴대폰 폭 하단 메뉴·카드 목록 완료, 접근성 점검은 미실시
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
