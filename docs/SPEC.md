# Tabula — 소상공인 재고 보충·발주 자동화 제품 및 기술 명세

작성 기준: 2026년 10월 20일 · 초기 시장: 미국 · 문서 성격: 조사 결과 + 권장 설계 + 구현 백로그

> 이 파일은 창업자가 작성한 기준 명세의 저장소 사본이다. 구현 체크포인트는 [CHECKPOINTS.md](CHECKPOINTS.md), 각 체크포인트 리뷰는 이 문서를 기준으로 한다. 출처 표기 [S..], [R..]는 원문 그대로 둔다.

권장 제품 정의: 매장이 이미 사용하는 POS와 공급업체를 연결해, 재고 부족을 예측하고 재주문·주문 확인·입고·청구서 대조를 처리하는 구매 운영 도우미.

이 문서에서 확인은 공식 문서나 저장소 코드로 확인한 사실, 제안은 제품·구현 판단, 가설은 고객 인터뷰나 파일럿으로 검증해야 할 항목이다. 가격, API 제공 범위, 심사 조건은 구현 시 다시 확인한다. 매출·절감률·고객 수·유료 전환 실적을 가정해서 실제 성과처럼 쓰지 않는다.

저장소 검토 기준은 Tabula의 커밋 d6335bf이다. README와 핵심 재고·발주·인증·화면 코드를 정적으로 검토했다. 전체 애플리케이션 실행, 실제 고객 계정 연결, 주문 전송 및 결제 테스트는 수행하지 않았다. 아래는 구현 완료 보고서가 아니라 실행 가능한 재설계 명세다.

## 1. 먼저 결정할 제품 방향

### 1.1 사용자가 구매하는 결과

매장 주인이 알고 싶은 것은 다음 네 가지다.

1. 오늘 무엇을 얼마나 주문해야 하는가?
2. 어느 기존 공급업체에서 언제 도착하고 총 얼마가 드는가?
3. 이미 주문한 물건이 제대로 오는가?
4. 실제 받은 수량과 청구 금액이 맞는가?

Tabula는 이 네 가지 업무를 하나의 작업 목록으로 연결한다. 사장은 예외와 큰 지출을 승인하고, 시스템은 반복 계산·문서 정리·상태 추적을 맡는다.

### 1.2 첫 제품의 경계

| 포함 | 이후 확장 | 초기 제품에서 제외 |
|---|---|---|
| POS 한 개, Sheets/CSV, 기존 공급업체 이메일 | 두 번째 POS, 회계 연동, 승인된 공급업체 API | 경쟁 매장 간 데이터 공유·에이전트 토론 |
| SKU 단위 재고 보충·PO·입고 | 매장 간 재고 이동, 공급업체 성과 비교 | ecosystem health, 가상 매장 네트워크 |
| 승인·예산·감사 기록 | 제한된 자동 발주 | 블록체인에 수요 신호를 기록하는 기능 |
| 기존 결제 상태 추적, SaaS 구독 결제 | 공급업체 결제, 조건이 맞는 국제 stablecoin 지급 | 범용 지갑, 자체 토큰, 대출, 자체 에스크로 |

공급업체 마켓플레이스를 처음부터 만들지 않는다. 매장의 기존 거래 관계를 제품 안에서 운영할 수 있게 하는 것이 먼저다. 신규 업체 탐색은 별도 승인 경로로 남긴다.

### 1.3 핵심 성공 단위

단순한 recommendation 생성이 아니라 한 건의 재주문이 공급업체 확인, 입고, 청구서 대조까지 완료된 것을 제품의 기본 성과 단위로 삼는다. 결제 연동 이전에도 주문과 입고가 완료되면 가치를 검증할 수 있다.

## 2. 어떤 소상공인부터 시작할 것인가

소상공인 전체를 하나의 시장처럼 취급하면 안 된다. POS가 같아도 음식점의 원재료 소비와 펫용품점의 완제품 판매는 재고 계산 방식이 다르다.

| 업종 | 재고 특성 | 초기 적합성 판단 | 주요 추가 난점 |
|---|---|---|---|
| 독립 펫용품점 | 사료·간식·모래 등 반복 판매 SKU | 우선 인터뷰할 1순위 가설 | 포장 크기, 유통기한, 공급업체별 지역 제한 |
| 뷰티·스킨케어 소매점 | 바코드가 있는 반복 구매 상품 | 강한 대안 가설 | 색상·용량 구분, 유통기한, 정품·판매권 |
| 장난감·취미용품점 | SKU가 명확하고 기존 Tabula 코드와 가까움 | 접근 가능한 실제 고객이 있으면 우선 | 시즌성·신제품·단종·낮은 반복 판매 |
| 식료품·편의점 | 반복 수요가 많음 | 포장 상온 상품에 한정해 확장 | 폐기, 신선식품, 직배송, 품절 시 대체 상품 |
| 카페·음식점 | 메뉴 판매로 원재료 소비 추정 | 초기에는 미룸 | 레시피/BOM, 수율, 계량, 폐기, Toast 접근 조건 |
| 의류·선물 부티크 | 사이즈·색상·계절별 상품 | 초기 우선순위 낮음 | 시즌 종료 후 재주문 불필요, Faire 구매 API 제약 |

제안 ICP: 1–3개 매장, 담당 바이어가 따로 없거나 사장이 발주를 겸함, 300–3,000개 활성 SKU, 3–15개 반복 거래 공급업체, 최소 주 1회 발주, 90일 이상 판매 기록을 제공할 수 있는 매장. 숫자는 시장 통계가 아니라 파일럿 모집 조건이다.

펫용품점을 첫 가설로 추천하지만, 실제로 연결 가능한 장난감 매장 고객이 있다면 그 고객의 반복 판매 상품부터 시작하는 편이 낫다. 기존 코드의 장난감 예시는 실제 고객 확보 증거가 아니다. 인터뷰 전에는 업종별 POS 점유율을 단정하지 않는다.

초기 SKU 범위는 포장 완제품·고정 단위·반복 조달 상품으로 제한한다. 처방 제품, 생체 동물, 신선·냉동 상품, 복잡한 제조 원재료는 별도 모델이 준비된 뒤 지원한다.

## 3. 실제 쓰는 시스템과 커넥터 우선순위

### 3.1 시장 근거를 해석하는 방법

Square는 2024년 연간 보고서에서 전 세계 400만 이상 판매자가 자사 생태계를 이용했다고 밝혔다. Toast는 2025년 말 약 164,000개 운영 장소를 보고했다. 두 숫자는 대상·기간·단위가 달라 점유율 순위로 직접 비교할 수 없다. [S01][S02]

Intuit의 Small Business Insights 조사 페이지는 재무 관리에 스프레드시트를 사용한다는 응답 53%를 제시한다. 이는 Sheets가 재고 시스템 1위라는 뜻도, 미국 소매점 53%가 Sheets로 재고를 관리한다는 뜻도 아니다. 다만 스프레드시트 수입 기능이 현실적인 온보딩 경로라는 근거가 된다. 조사 범위는 미국·캐나다·영국·호주 등의 소기업이다. [S03]

따라서 아래 순위는 전체 SMB 시장점유율 순위가 아니라 Tabula에 필요한 데이터·연동 가능성·개발 비용을 합친 구현 우선순위다.

| 연결 대상 | 가져올 데이터 | Tabula에서의 역할 | 제안 단계 | 확인할 제약 |
|---|---|---|---|---|
| Square | Catalog, Orders, Inventory, Locations, Vendors | 첫 POS·현재 재고 기준 | P0 기본 가설 | 판매 Orders API와 공급업체 PO는 다름 |
| Google Sheets | 공급업체 목록, 단가표, SKU 매핑, 실사 수량 | 유연한 입력·보조 관리 | P0 | 행 이동, 권한, 수식, API quota |
| CSV/Excel 업로드 | 기존 재고·판매·미입고 주문 | 계정 연결 전 빠른 시작 | P0 | 파일 단위·날짜·통화 검증 |
| 공급업체 이메일/PDF | 주문 확인, 가격표, invoice, 배송 안내 | 실제 구매 업무의 연결점 | P0 | 문서 추출 오류, 수취인 검증, 주문 식별 |
| Shopify/POS | 상품·variant·판매·위치별 재고 | 두 번째 POS·온라인 판매 | P1 또는 첫 고객에 맞춰 P0로 교체 | 과거 주문 권한, PO API 제한 |
| QuickBooks Online | Vendor, Bill, PurchaseOrder, 지급 기록 | 장부와 구매 업무 대조 | P1 | 요금제·entity 지원; 장부 기록이 송금은 아님 |
| Clover | 상품·주문·재고 | 오프라인 소매 확장 | P2 | OAuth·지역별 endpoint·앱 배포 |
| Lightspeed Retail | 상품·판매·재고·입고 | 전문 소매 확장 | P2 | X-Series와 R-Series를 서로 다른 커넥터로 취급 |
| Xero | 공급업체 연락처·매입 청구서·PO | 회계 확장 | P2 | API 요금·권한·국가별 수요 |
| Toast | 메뉴·판매·장소 | 음식점 확장 | P3 | 파트너 신청·인증, 식재료 재고 모델 필요 |
| WooCommerce·Amazon 판매 채널 | 상품·판매 주문 | 파일럿에서 수요가 확인되면 추가 | 보류 | 중복 주문·재고 기준 충돌 |

Square, Clover, Lightspeed, Toast, QuickBooks, Xero의 제공 범위는 각 공식 개발자 문서로 확인했다. 이 표는 모든 entity의 쓰기 권한과 상업적 이용 승인이 이미 확보됐다는 뜻이 아니다. [S04][S09][S10][S11][S12][S13]

실행 원칙: 첫 5개 파일럿이 공통으로 쓰는 POS부터 만든다. Square와 Shopify를 동시에 완성하는 것은 목표가 아니다. 플랫폼별 앱 심사·개발자 계정·OAuth 승인은 외부 의존성으로 일정에 별도 표시한다.

### 3.2 Square 커넥터 명세

- OAuth로 판매자 계정에 접근하고 token은 서버에서 암호화해 보관한다.
- 매장 위치를 선택하게 한다. 동일 판매자의 모든 위치를 자동 합산하지 않는다.
- 상품 variant와 바코드, 단가, 판매 line item, 취소·환불, 재고 상태를 가져온다.
- 초기 판매 기록은 확보 가능한 범위에서 90–365일을 목표로 하되 실제 데이터 범위를 화면에 표시한다.
- 이후 webhook + 변경분 polling + 야간 전체 대조를 조합한다.
- 재고 관련 webhook이 들어오면 provider의 최신 상태를 조회해 정규화한다. webhook 순서를 신뢰하지 않는다.
- 판매 이벤트는 수요 계산에 사용한다. POS가 이미 반영한 현재 재고에서 판매 수량을 또 차감하지 않는다.
- 주문 발송 시에는 현재 재고를 올리지 않는다. 실제 입고 승인 뒤에만 provider가 지원하는 재고 변경 경로를 사용한다.

공식 API 목록에서 Catalog·Orders·Inventory·Vendors는 확인했다. 검토한 공개 목록에서 일반 supplier PO 생성 API는 확인하지 못했다. 따라서 Tabula가 자신의 PO를 저장·전송하는 구조로 설계한다. Square 화면의 PO 기능 존재를 곧바로 API 제공으로 해석하지 않는다. [S04][S05]

### 3.3 Shopify 커넥터 명세

- GraphQL Admin API를 사용하고 stable API version을 고정한다.
- catalog/variants, inventory item, location, sales order line, refund 및 재고 상태를 정규화한다.
- 대량 초기 읽기는 bulk operations를 사용한다. [S07]
- 기본 주문 접근은 최근 60일이며 더 오래된 주문에는 승인된 read_all_orders 범위가 필요하다. 승인 전에는 CSV 보완 경로를 제공한다. [S06]
- Stocky는 2026년 8월 31일 종료됐다. Stocky API를 신규 설계의 기반으로 삼지 않는다.
- 공식 안내 기준 Shopify의 PO API는 일반 제공 상태가 아니며 physical inventory preview에 일부 읽기 기능이 있다. native PO 쓰기를 MVP 필수 의존성으로 두지 않는다. [S08]
- 기존 Shopify/Faire 연동이 이미 입고 수량을 올리는지 확인한다. 같은 입고를 Tabula가 다시 올리지 않도록 연결마다 inventory write owner를 정한다.

### 3.4 Sheets·CSV 커넥터 명세

온보딩에서 판매, 재고, 공급업체 가격표, 미입고 주문 중 어떤 파일인지 먼저 선택한다. 한 파일을 만능 테이블로 가정하지 않는다.

| 입력 유형 | 최소 필드 | 추가 권장 필드 |
|---|---|---|
| 재고 | SKU 또는 barcode, 위치, 현재 수량, 기준 시각 | 판매 가능 수량, 손상 수량, 품절 기록 |
| 판매 | 거래 식별자, 거래 시각, SKU, 수량 | 취소·환불, 할인, 채널, 재고 복원 여부 |
| 공급업체 가격표 | 공급업체, supplier SKU, 주문 단위, 단가, 통화 | case pack, MOQ, 리드타임, 가격 유효일 |
| 미입고 주문 | PO 번호, 공급업체, SKU, 잔여 수량 | 주문일, ETA, 확인 여부, 이미 받은 수량 |

열 이름 자동 매핑은 초안만 만든다. 예를 들어 Case, Qty, Cost가 각각 상자 수인지 개수인지 상자 가격인지 사용자에게 미리보기로 확인시킨다. USD 단가와 KRW 단가를 숫자만 보고 비교하지 않는다.

Google Sheets에서는 읽을 파일·탭을 사용자가 선택하고, 15–60분 주기 polling을 기본 제안으로 둔다. 전체 행마다 API를 호출하지 않고 범위 단위 batch read와 checksum으로 변경을 찾는다. 공식 quota의 기본값은 읽기·쓰기 각각 프로젝트당 분당 300회, 사용자/프로젝트당 분당 60회다. [S14]

행 번호를 상품 ID로 쓰지 않는다. external_row_id를 매핑하거나 SKU+location+source key로 안정적인 식별자를 만든다. 기본은 읽기 전용이며, writeback을 켜면 Tabula 전용 결과 탭을 사용한다. 기존 수식과 사용자의 단가표를 임의로 덮어쓰지 않는다.

CSV 파일 hash, import ID, 행 key를 저장해 동일 파일 재업로드가 판매량·재고를 두 번 늘리지 않게 한다. Excel macro는 실행하지 않는다. CSV export의 formula injection도 처리한다.

### 3.5 회계 연결의 역할

QuickBooks는 재고의 매초 변화보다 공급업체 장부, invoice, 미지급금 대조에 사용한다. 실제 지급을 확인한 뒤 BillPayment 같은 장부 객체를 연결하며, 그 객체 생성이 은행 송금을 수행한다고 표현하지 않는다. PO 기능은 QuickBooks 요금제 제한도 확인한다. [S11]

재고 입고와 회계 bill 생성이 각각 수량을 증가시키는지 integration별 검증이 필요하다. 한 수신 건에 두 시스템이 독립적으로 재고를 추가하는 설계는 금지한다.

## 4. 현재 Tabula 코드에서 살릴 것과 바꿀 것

### 4.1 확인한 구현 상태

| 코드 | 확인한 내용 | 판단·조치 |
|---|---|---|
| clawbot/agents/inventory_agent.py | 재고 조회·부족 수량·바코드 도구를 사용하는 agent | 도구와 schema 재사용, 수량 계산은 결정적 서비스로 이동 |
| clawbot/tools/db_inventory.py | MongoDB 재고와 stock_transactions, reorder point 조회 | 거래 원장·위치·tenant·멱등성 보강 필요 |
| clawbot/tools/db_procurement.py | 공급업체·catalog·quote·procurement item 모델 | 구매 데이터 모델의 출발점으로 재사용 |
| clawbot/tools/sales_history.py | MongoDB 판매량·월별 패턴 집계 | POS 수입과 SKU별 일별 수요 계산 추가 |
| clawbot/agents/procurement_agent.py | 공급업체 탐색과 주문 요약 생성 | 검증된 기존 공급업체 경로를 먼저 붙임 |
| clawbot/agents/pending_orders.py | 전화번호별 마지막 주문을 메모리 dict에 보관 | 영속 PO·revision·approval 테이블로 대체 |
| clawbot/agents/universal_agent.py | 확인 tool이 pending 항목을 제거하고 confirmed를 반환 | 공급업체 접수 또는 결제 성공으로 표현하지 않게 상태 재설계 |
| demo-ui/src/data.ts | output JSON을 import해 시장·추천 데이터를 구성 | live API 기반 화면으로 교체, demo data는 별도 모드 |
| demo-ui/src/pages/OrdersPage.tsx | 추천 목록과 Approve 표시 | 실제 PO 화면·API mutation으로 교체 |
| demo-ui/src/components/ui.tsx | ActionChip이 이벤트 없는 span | button·권한·로딩·실패 상태를 지원하는 컴포넌트로 변경 |
| demo-ui/src/pages/InventoryPage.tsx | 실제 재고 API fetch 존재 | 검색·표·스캔 UX를 확장 가능 |
| clawbot/auth/auth0.py | JWT 검증 helper 존재 | 검토한 재고·발주 route에는 적용이 확인되지 않아 실제 enforcement 필요 |
| api/main.py, 여러 agent route app | API 진입점이 분산 | 한 FastAPI application으로 묶고 domain router 분리 |
| clawbot/api/server.py | 별도 ThreadingHTTPServer와 메시지 polling | 제품용 API와 통합; macOS 의존 흐름은 보조 데모로 분리 |
| YHack_2026/agentic-marketplace/, simulation 화면 | 매장 간 토론·집계·Solana devnet 검증 | 핵심 제품 배포에서 제외하고 archive/demo로 보존 |

위 판단의 코드 출처는 문서 끝의 R01–R10이다. 저장소 파일 목록과 검토 코드에서는 Stripe의 실제 결제·정산 구현이나 Square/Shopify OAuth connector를 확인하지 못했다. 전체 배포 상태를 검증한 것은 아니므로, 저장소 밖에 운영 코드가 있으면 추가 검토해야 한다.

### 4.2 바로 해결할 구체적인 문제

1. adjust_stock()는 재고 $inc와 거래 기록 insert를 별도로 수행한다. 재고 업데이트와 원장 기록 전체가 하나의 transaction으로 묶이지 않는다. 또한 거래 ID에 초 단위 시각을 사용하므로 같은 SKU의 같은 초 변경에서 충돌 가능성이 있다. UUID/고유 event ID와 transaction 경계를 도입한다.
2. 재고·공급업체 조회에서 tenant/location 범위가 확인되지 않는다. 다중 매장 SaaS 전환 전 tenant 격리가 필요하다.
3. quote 저장의 광범위한 except Exception: pass는 실제 DB 장애까지 중복으로 오인할 수 있다. 중복 key만 따로 처리하고 나머지는 실패로 기록한다.
4. supplier catalog 매칭은 문자열·정규식 첫 일치에 의존한다. 50ml/100ml, 1개/12개입을 구분하는 명시적 SKU mapping으로 바꾼다.
5. 일부 agent loop는 while True다. 최대 tool step, timeout, 비용 budget, 취소 신호가 필요하다.
6. 주요 화면의 성공처럼 보이는 표시를 실제 주문·지급 상태와 연결해야 한다. UI의 Approved는 Supplier accepted와 다르다.

### 4.3 저장소 정책과 제품 정책 정리

현재 AGENTS/PRICE_DISCOVERY_PLAYBOOK은 가격 탐색과 공급업체 연락 금지를 중심으로 작성돼 있다. 새 제품 요구사항과 충돌하므로, 실제 구현 단계에는 가격 탐색 도구와 승인된 주문 실행 도구의 경계를 명시하는 정책 개정이 필요하다. 이번 작업은 설계 조사이며 공급업체에게 연락하거나 결제를 실행하지 않는다.

기존 규칙에 맞춰 agent implementation은 clawbot/agents/ 안에서 확장한다. 새로운 top-level agent runtime을 여러 개 만들지 않는다. runtime identity/session 관련 파일이 저장소에 포함된 흔적은 production 이전에 별도 검토하고, 실제 credential이 있다면 제거·교체한다. 이 문서에는 credential 내용을 수집하거나 복사하지 않았다.

## 5. 공급업체를 연결하는 현실적인 구조

### 5.1 공급망은 merchant별 실제 거래 관계에서 시작한다

첫 온보딩 때 매장의 최근 invoice 3–5개, 공급업체 단가표, 미입고 주문 목록을 받는다. 이를 통해 supplier master와 상품 대응표를 만든다.

Supplier 레코드에는 다음을 저장한다.

- 이름, merchant account number, 주문 이메일·portal URL, 담당자.
- 서비스 지역, 배송 가능 매장, 배송 요일, 주문 마감 시각과 timezone.
- MOQ, 상품별 order multiple, 최소 주문 금액, 무료배송 기준, 운임 규칙.
- 기본 lead time과 실제 관측 lead time 분포, 휴무일.
- 통화, 결제 조건, credit hold 여부, 확인된 지급 수단의 provider reference.
- relationship_status, ordering_channel, verified_at, 검증한 사용자.

브랜드명과 distributor는 다르다. 같은 브랜드 제품이 여러 distributor를 통해 오더라도 supplier SKU와 단가 계약은 별개로 저장한다. Merchant A에게 받은 단가를 Merchant B에게 노출하지 않는다.

### 5.2 채널별 주문 지원 수준

| 채널 | 실행 방법 | 자동화 수준 | 성공 판정 |
|---|---|---|---|
| 이메일 발주 | 사전 검증 주소에 PO PDF/CSV와 확인 링크 전송 | P0 | 발송→접수 확인→납기 확인을 구분 |
| 공급업체 확인 페이지 | 만료되는 링크로 수량·가격·ETA 입력 | P0 | 인증된 담당자가 명시적으로 확인 |
| 공식 supplier API | 계약·권한 확보 후 PO create/status/cancel | P1 | supplier order ID와 응답 저장 |
| EDI/cXML | 거래처 합의 후 표준 문서 교환 | P2 | business acknowledgement까지 추적 |
| 기존 B2B portal | 주문 목록 export·deep link·사람이 최종 제출 | 초기 보조 | 사람이 등록한 confirmation ID |
| 브라우저 자동화 | 별도 허용과 안정성 검증 뒤 좁게 적용 | 후순위 | 접수 번호 대조, timeout 시 중복 제출 금지 |

EDI를 도입한다면 PO, acknowledgement, shipping notice, invoice의 거래처별 specification과 test certification이 필요하다. 표준 이름이 같다고 supplier mapping까지 자동으로 끝나는 것은 아니다.

### 5.3 확인한 실제 연결 후보와 한계

- Phillips Pet Food & Supplies: 공식 지원 페이지에 이메일 주문과 온라인 주문 경로가 있다. 펫용품 파일럿의 기존 거래처인 경우 활용 후보가 된다. Tabula용 API나 자동 주문 계약이 확인된 것은 아니다. [S18]
- Faire: 브랜드용 API가 존재하지만 공식 소매점 지원 문서는 retailer용 API token/key 및 custom direct integration을 제공하지 않는다고 명시한다. Tabula가 Faire 구매를 일반 API로 자동 제출할 수 있다고 약속하지 않는다. [S16][S17]
- Amazon Business: Ordering API가 실제로 존재하고 고객 onboarding이 필요하다. API 접근 승인과 제품 범위가 맞을 때 소모품 구매 확장 후보가 된다. 재판매 상품의 주 공급망으로 자동 선택하지 않는다. [S19]
- 지역 distributor·브랜드 직거래: 먼저 기존 invoice와 담당자 이메일로 연결한다. 공급업체가 Tabula에 가입해야만 주문을 받는 구조는 피한다.

### 5.4 공급업체 확인 페이지 세부 명세

화면에는 merchant, 배송지, PO 번호, revision, 상품별 supplier SKU, 주문 단위와 수량, 단가, 요청 납기를 표시한다. 공급업체는 전체 수락, 부분 수락, 가격 변경 제안, ETA 변경, 공급 불가를 선택할 수 있다.

가격·수량 변경은 원본 PO를 덮어쓰지 않고 counteroffer revision으로 만든다. merchant가 승인하면 새 버전을 확정한다. 대체 상품은 barcode·규격·용량을 표시하고 명시적 승인 전에는 주문하지 않는다.

링크 조회 GET은 읽기만 수행한다. 이메일 보안 스캐너가 링크를 열었다고 주문이 수락되지 않도록 한다. 실제 수락은 POST와 nonce, 유효기간, 수취인 확인을 거친다. 금액이 크거나 민감한 변경에는 추가 인증을 요구한다.

### 5.5 신규 공급업체 탐색은 별도 보조 업무

인터넷에서 찾은 가격은 public_listing이며 계약 단가가 아니다. 신규 공급업체는 candidate 상태로 만들고 정품·규격, 납품 가능 지역, merchant account, MOQ, 최종 운임, 지급 상대방을 확인한 뒤 approved로 승격한다.

검색 결과를 읽은 agent가 바로 주문·지급하는 경로는 만들지 않는다. 기존 가격 탐색 코드는 사장이 공급업체 선택을 판단하는 데 쓰고, 자동 보충은 검증된 공급업체와 SKU만 대상으로 한다.

## 6. 상품·단위·재고 데이터의 기준

### 6.1 동일 상품 판별

우선순위는 provider item ID → merchant SKU → 정확한 barcode/GTIN → 승인된 supplier SKU mapping이다. 텍스트 유사도는 후보를 찾는 데만 사용한다.

동일 브랜드라도 용량, 맛, 색상, 포장 수량, 지역 규격이 다르면 별도 variant다. 매장 A의 SKU 문자열이 매장 B의 같은 상품을 뜻한다고 가정하지 않는다.

### 6.2 기준 단위와 주문 단위

예: 판매 단위 1봉, supplier 주문 단위 1상자, 상자당 12봉. 데이터는 base_uom=each, order_uom=case, units_per_order_uom=12를 보관한다. 48봉 보충은 4상자 주문으로 표시한다.

수량과 금액은 floating point 기반 계산을 피한다. 수량은 필요한 정밀도의 Decimal, 금액은 통화별 minor unit 또는 Decimal로 저장한다. 상자 원가·개당 원가·운임 포함 원가를 별도 필드로 관리한다.

### 6.3 어떤 시스템을 기준으로 할지 정한다

| 데이터 | 기본 기준 시스템 | Tabula 역할 |
|---|---|---|
| 판매 거래 | POS 또는 commerce platform | 수입·중복 제거·수요 계산 |
| 현재 매장 재고 | 매장이 선택한 POS/IMS | 읽기 모델·차이 감지·승인된 입고 반영 |
| 공급업체 SKU 매핑·조건 | Tabula의 승인된 기록 | 변경 이력과 출처 관리 |
| Tabula에서 만든 PO | Tabula | revision·approval·전송·접수 기록 |
| 회계 bill | 선택한 회계 시스템 | 원문·PO·입고와 매칭 |
| 실제 지급 상태 | payment provider/은행 증빙 | webhook 대조·audit 기록 |

동일 판매가 Shopify→Square→회계 프로그램으로 복제돼도 한 번만 수요에 반영한다. merchant별 원본 채널과 origin order ID를 보관한다. 원본을 식별할 수 없으면 여러 판매 source를 합산하지 않고 검토 대상으로 둔다.

### 6.4 재고 값은 의미별로 분리한다

on_hand, reserved, damaged, available, confirmed_inbound, unconfirmed_ordered를 구분한다. provider의 available에 reserved 차감이 이미 반영돼 있으면 다시 차감하지 않는다. unconfirmed_ordered는 중복 주문을 막는 데는 사용하지만 확정 입고처럼 품절 위험을 제거하는 데 사용하지 않는다.

과거 재고가 없으면 현재 수량과 판매 기록만으로 과거의 모든 품절 시간을 복원할 수 없다. 해당 구간의 수요 보정은 추정으로 표시하고, 연결 시점부터 재고 상태 이력을 쌓는다.

## 7. 자동 재고 보충 엔진

### 7.1 LLM의 역할과 계산기의 역할

LLM은 문서 추출, 상품 mapping 후보, 공급업체 응답 해석, 추천 설명을 담당한다. 최종 주문 수량·총액·예산·권한 판정은 결정적인 코드로 계산한다. 같은 입력과 같은 정책 버전에서는 같은 발주 결과가 나와야 한다.

Google Trends·Reddit·지역 행사 데이터는 보조 정보다. 외부 trend 상승만으로 실제 매장의 자동 주문량을 늘리지 않는다. 판매 데이터 또는 사장이 등록한 행사와 함께 검증한 경우에만 제한된 조정치를 적용한다.

### 7.2 초기 알고리즘

초기에는 해석 가능한 이동평균·요일 패턴·merchant min/max를 기본값으로 삼는다. 판매가 드문 상품은 최근 7일 평균만으로 판단하지 않고 더 긴 구간, 간헐 수요 모델 또는 수동 min/max를 선택한다. 복잡한 모델은 시간 순서 backtest에서 단순 기준보다 좋아질 때 도입한다.

개념식:

```
lead_time = 주문부터 사용 가능한 입고까지의 시간
review_period = 다음 정기 발주까지의 간격
target_stock = forecast_demand(lead_time + review_period) + safety_stock
inventory_position = usable_on_hand + relevant_confirmed_inbound - commitments_not_already_subtracted
raw_order_qty = max(0, target_stock - inventory_position)
order_qty = round_up_to_supplier_pack_and_minimum(raw_order_qty)
```

이 집계식만으로 결정을 끝내지 않는다. 날짜별 projected stock을 만들어, inbound 도착 전에 발생하는 품절을 따로 찾는다. 늦게 도착하는 큰 주문은 오늘의 품절을 해결하지 못한다.

발주 전에 반드시 다음 제약을 반영한다.

- 매장 영업일, supplier 영업일·마감 시각·배송 요일.
- 열린 PO의 미입고 잔량과 확인 여부.
- case pack, line MOQ, supplier 최소 금액.
- 보관 공간, 유통기한, 단종·판매 중지.
- 주간 구매 budget, 승인되지 않은 예약 지출, 이미 확정된 지출.
- 할인·행사·대량 일회성 판매, 반품과 재판매 가능 여부.
- 다른 매장에서 가져올 수 있는 재고와 운송 비용.

### 7.3 숫자 예시

다음은 실제 고객 데이터가 아닌 계산 예시다.

| 항목 | 값 |
|---|---|
| 사용 가능한 현재 재고 | 18개 |
| 일평균 수요 | 6개 |
| 공급업체 lead time | 4일 |
| 다음 정기 발주 간격 | 7일 |
| safety stock | 12개 |
| 확정된 입고 | 0개 |
| 상자 크기 | 12개 |

목표 재고는 6 × (4+7)+12 = 78개, 보충량은 78-18 = 60개, 주문은 5상자다. 동시에 현재 재고는 약 3일 만에 소진되고 납기는 4일이므로 1일의 예상 품절 구간을 표시한다. 시스템은 5상자 주문과 별개로 긴급 배송 또는 매장 간 이동 가능성을 보여준다.

### 7.4 예산 최적화

무료배송 기준을 맞추기 위해 필요 없는 재고를 늘리는 것을 자동으로 좋은 선택으로 판정하지 않는다. 후보 주문별 운임, 재고 보유 비용, 예상 품절 손실, 유통기한, 판매 마진을 함께 비교한다.

초기에는 설명 가능한 우선순위 휴리스틱을 사용한다: 품절 임박한 반복 판매 상품 → 높은 재고 회전 상품 → 주문 주기가 긴 필수 상품. 고객 데이터가 쌓이면 mixed integer optimization 등으로 확장할 수 있지만 MVP 의존성은 아니다.

### 7.5 정확도 평가

rolling-origin backtest로 미래 정보 유출을 막고, 동일 기간의 단순 이동평균·merchant 기존 reorder rule과 비교한다. WAPE/MASE 등 오차 지표와 함께 품절 일수, 평균 재고 가치, 폐기, 주문 횟수를 측정한다. 실제 재고 기록이 없는 구간의 품절 감소는 확정 성과로 보고하지 않는다.

## 8. 여러 AI agent의 역할과 권한

여러 agent는 책임이 분리된 작업 모듈로 구현한다. 각각 독립적인 서버나 공개 채팅 캐릭터일 필요는 없다. 기존 clawbot/ 내부의 공통 schema·도구·실행 기록을 공유한다.

| 역할 | 입력 | 출력 | 허용되는 자동 작업 | 직접 할 수 없는 작업 |
|---|---|---|---|---|
| Data onboarding | CSV, 가격표, 상품 목록 | mapping 후보와 오류 목록 | schema 제안·중복 후보 탐지 | 확인 없는 SKU 병합 |
| Inventory analyst | 정규화 판매·재고 | 부족 위험·추천 근거 | 계산 서비스 호출·설명 | 임의 수량 수정 |
| Purchasing assistant | 보충 후보·supplier 조건 | PO draft·총액·예외 | 검증된 catalog로 초안 생성 | 신규 supplier 자동 등록·계약 |
| Supplier coordinator | 발주 응답·배송 안내 | 접수·납기·변경 제안 | 승인 범위의 상태 추적 | 승인 금액 초과·대체품 확정 |
| Receiving/reconciliation | PO·수령 기록·invoice | 차이·미납품·중복 invoice | 대조·credit 요청 초안 | 실제 받지 않은 수량 입고 확정 |
| Owner assistant | 질문·해당 merchant 업무 기록 | 답변·실행 제안 | 읽기·승인 화면 준비 | 정책 우회·임의 지급 |

payment 실행과 budget 승인은 agent persona가 아닌 별도의 정책·실행 서비스가 담당한다. MCP는 이 내부 도구를 노출하는 adapter로 활용할 수 있지만, 원장·queue·idempotency를 대신하지 않는다.

모든 agent output에는 run_id, tenant_id, source_refs, data_as_of, schema_version, model_version, proposed_actions, warnings를 둔다. 실측 calibration 없이 LLM이 만든 confidence 97%를 정량 신뢰도처럼 표시하지 않는다. 대신 "판매 기록 28일뿐", "supplier 확인 전", "단위 미확정" 같은 근거를 보여준다.

문서·이메일·웹페이지는 데이터로 취급한다. 그 안의 지시문이 시스템 권한이나 지급 정보를 변경하지 못하게 한다. tool은 tenant와 사용자 권한을 서버에서 다시 검증하고, 모델이 넘긴 tenant ID를 신뢰하지 않는다.

각 실행에 tool call 수, 총 timeout, token/비용 상한을 둔다. 재시도 가능한 추출 실패와 사람이 해결할 business exception을 구분한다. 모든 SKU마다 매시간 LLM을 부르는 구조는 피하고, 계산은 batch로 수행하며 변화나 예외가 있을 때만 설명을 생성한다.

## 9. 승인과 자동화 수준

| 모드 | 동작 | 최초 제공 |
|---|---|---|
| Observe | 데이터를 읽고 기존 발주와 비교 | 연결 직후 |
| Review | PO 초안을 만들고 사장이 승인하면 전송 | 초기 파일럿 |
| Autopilot | 검증된 supplier/SKU/예산 범위에서 반복 발주 | 몇 차례 정상 발주·입고 검증 후 |

발주 자동화와 지급 자동화는 별개다. 자동으로 PO를 보낼 권한이 있다고 invoice를 자동 지불할 권한이 생기는 것은 아니다.

예시 정책은 approved_supplier_only, 주문당 최대 $300, 주간 $1,500, 단가 변동 최대 3%, 알려진 case pack, 신선한 재고 데이터, 미확인 기존 PO 없음이다. 숫자는 추천 시작점이 아니라 설명용 예시이며 merchant가 설정한다.

다음 상황은 자동화를 중지하고 task로 보낸다: 데이터 stale, 단위 불명, 신규 지급 계좌, 신규 supplier, 예상보다 큰 가격 상승, 공급업체 미응답, 부족한 budget, 같은 품목의 미확인 주문, policy revision 변경.

승인은 PO revision과 금액·수취인·배송지·정책 version에 묶는다. 승인 뒤 수량이나 단가를 바꾸면 이전 승인은 무효가 된다. 두 사람이 동시에 승인해도 발송은 한 번만 일어나야 한다.

## 10. 발주·입고·결제 상태 모델

하나의 status=done으로 모든 것을 표현하지 않는다.

| 객체 | 상태 예시 | 중요한 구분 |
|---|---|---|
| PO | draft, awaiting_approval, approved, sending, sent, supplier_confirmed, partially_received, received, closed, cancel_requested, cancelled, exception | 취소 요청은 공급업체 취소 완료와 다름 |
| Supplier acknowledgement | pending, accepted, partially_accepted, counteroffer, rejected | 이메일 발송은 주문 수락이 아님 |
| Receipt | draft, verified, posted, corrected | 배송사 delivered는 수령 수량 검증이 아님 |
| Invoice | received, extracted, matched, discrepancy, approved, recorded | invoice 금액 승인과 은행 지급은 별도 |
| Payment | draft, authorized, processing, succeeded, failed, returned, refunded | ACH 처리 시작을 확정 지급으로 표시하지 않음 |

PO line별 ordered, confirmed, received, rejected/damaged, cancelled, outstanding 수량을 보관한다. 부분 입고 8/10이면 잔량 2를 유지하고, supplier가 잔량 취소를 확인했을 때만 줄인다. 반환·credit note·대체 발송도 원본 PO와 연결한다.

수령 확인, invoice 수신, 지급일은 서로 다른 순서로 발생할 수 있다. Net 30은 입고 후 지급을 만들 수 있지만, 선결제 supplier는 입고 전 승인 지급이 필요하다. three-way match를 모든 거래의 선행 조건으로 강제하지 않고, payment terms별 정책을 둔다.

## 11. Stripe·ACH·stablecoin 결제 설계

### 11.1 세 종류의 돈 흐름을 분리한다

1. 매장 → Tabula: 월 구독료. Stripe Billing/Checkout의 일반 SaaS 결제로 처리한다.
2. 매장 → 공급업체: 물품 대금. supplier의 기존 invoice·은행 지급 경로 또는 적합성이 확인된 provider 연결을 사용한다.
3. Tabula가 중간에서 수납하고 공급업체에 지급: marketplace/platform 흐름. Connect·funding·책임·onboarding 조건을 별도로 검증해야 한다.

2번이 필요하다고 무조건 3번을 만들지 않는다. 처음에는 기존 거래 결제 수단을 유지하고 PO·invoice·payment reference만 연결해도 구매 자동화 가치를 제공할 수 있다.

### 11.2 미국 수납 요율의 계산 예시

공식 미국 Stripe pricing 조회 기준 일반 domestic online card는 2.9%+$0.30, ACH Direct Debit은 0.8%에 $5 상한, 일반 stablecoin payments는 1.5%다. 별도의 Link stablecoin 항목에는 2027년 1월 1일까지 0.8%의 promotional rate와 이후 +0.2%가 표시돼 있었다. 상품·계약·자격이 다르므로 혼용하지 않는다. [S20]

아래는 일반 수납 처리비만의 예시다. supplier payout 견적이나 전체 국제 송금 비용이 아니다.

| 거래액 | 온라인 카드 2.9%+$0.30 | ACH 0.8%, 최대 $5 | 일반 stablecoin 수납 1.5% |
|---|---|---|---|
| $100 | $3.20 | $0.80 | $1.50 |
| $500 | $14.80 | $4.00 | $7.50 |
| $1,000 | $29.30 | $5.00 | $15.00 |
| $5,000 | $145.30 | $5.00 | $75.00 |

Connect 비용, invoice/Billing 비용, 은행 확인, 실패·반환, FX, funding, supplier payout, on/off-ramp 비용은 제외했다. 따라서 "stablecoin이라 가장 싸다"는 제품 약속은 근거가 없다. 국내 달러 B2B에서는 ACH가 유리할 가능성이 크다. 카드의 외상 기간·보상이나 supplier 할인 조건까지 포함하면 merchant의 선택이 달라질 수 있다.

ACH는 지연 확인 방식이며 실패·분쟁 위험이 있다. 결제 시작을 즉시 정산 완료로 처리하지 않는다. [S21]

### 11.3 수납과 지급의 API 지원은 다르다

Stripe의 stablecoin payments는 고객으로부터 stablecoin을 받는 상품이다. Connect 지원이 표시돼 있어도 임의의 법인 supplier wallet에 모든 경우 지급할 수 있다는 뜻은 아니다. [S22]

검토한 Connect stablecoin payouts 문서는 미국 platform 대상 private preview이고 수취인이 개인 또는 sole proprietor여야 하며 회사·비영리법인은 아직 지원하지 않는다고 명시한다. 일반 wholesale supplier 법인을 이 경로로 지급하는 것을 초기 설계의 전제로 삼지 않는다. [S23]

Global Payouts는 별도 상품이며 Treasury/funding과 사업 모델 조건을 가진다. API가 존재한다는 사실만으로 Tabula가 merchant 자금을 임의로 모아 supplier에게 지급할 수 있다고 해석하지 않는다. [S24]

### 11.4 권장 도입 순서

| 단계 | 실제 기능 | 출시 조건 |
|---|---|---|
| P0 | Tabula 구독 결제, supplier 기존 결제 링크·상태 기록 | 물품대금 custody 없음 |
| P1 | 적합성이 확인된 supplier 수납 계정에 ACH/card 결제 연결 | supplier onboarding·mandate·refund/return 검증 |
| P2 | 특정 국제 거래의 stablecoin 경로 | 법인·국가·통화 지원과 전체 비용을 실거래로 확인 |

국제 stablecoin 후보로 Bridge의 orchestration API를 조사할 수 있다. 공식 제품은 fiat/stablecoin 변환과 이동을 설명하지만 Tabula 계약 요율이나 모든 국가의 법인 수취 가능성이 공개 자료만으로 확정되지는 않는다. [S25]

### 11.5 Stablecoin을 쓸 가치가 있는 조건

- 실제 공급업체가 해외에 있고 기존 송금 비용 또는 시간 문제가 큼.
- supplier가 받을 법정통화/지갑을 선택할 수 있고 그 경로가 provider에서 지원됨.
- fiat funding, 변환, network, off-ramp, FX, platform fee를 합한 총비용이 대안보다 낮음.
- 수취 금액·도착 예상 시간·견적 유효기간을 주문 전에 확정할 수 있음.
- 환불·오송금·미납품·가격 변경 처리 방식이 정리돼 있음.

국내 미국 공급업체와의 반복 주문만 검증된 상태라면 stablecoin은 후순위가 맞다. 한국 등 특정 국가 공급업체 지급을 지원한다고 미리 표기하지 않는다.

### 11.6 Payment adapter 계약

```
quote_payment(invoice_id, payer_ref, payee_ref, rail)
  -> amount_debited, amount_received, all_fees, fx_rate,
     estimated_arrival, quote_expires_at, eligibility

authorize_payment(quote_id, invoice_revision, approval_id)
execute_payment(payment_id, idempotency_key)
get_payment_status(provider_payment_id)
reconcile_provider_event(event_id)
request_refund(payment_id, amount, reason)
```

backend는 confirmed payee, 승인된 invoice revision, 중복 지급 여부, 사용 가능한 budget을 검증한다. invoice PDF 안의 새 은행 계좌나 wallet 주소는 자동으로 beneficiary record를 변경하지 못한다. 확정 금액/수취인 변경에는 새 승인이 필요하다.

PaymentIntent 생성 후 redirect 성공 페이지에 도달한 것만으로 paid 처리하지 않는다. 서명 검증된 webhook과 provider 조회로 상태를 기록한다. Stripe의 멱등성 key와 Tabula 내부 고유 지급 operation ID를 함께 사용한다. [S26]

## 12. 매장 주인에게 보여줄 frontend

### 12.1 기본 방향

기존 React/Vite/TypeScript/Tailwind 기반을 유지한다. 제품 목적 때문에 Next.js로 전면 이전할 필요는 없다. 앱은 mobile에서도 승인과 입고가 가능해야 하고, desktop에서는 많은 SKU를 빠르게 검토할 수 있어야 한다.

화면의 중심은 agent 목록보다 해야 할 업무다. 추천 기본 메뉴는 Today / Inventory / Orders / Suppliers / Bills / Connections이고, automation과 팀 권한은 Settings로 둔다. 검색과 Ask Tabula는 보조 진입점으로 둔다.

### 12.2 온보딩: 첫 추천까지 최소 경로

1. 매장 종류·위치·timezone 선택.
2. Square 또는 지원 POS 연결; CSV로 시작하기도 제공.
3. 판매·재고 import 범위와 마지막 동기화 시각 표시.
4. 기존 supplier·가격표·미입고 주문을 연결.
5. 상위 반복 판매 SKU의 supplier mapping·단위 확인.
6. 현재 재고가 부정확한 항목은 간단한 실사 task 생성.
7. 예산·승인 기본값을 설정하고 Observe/Review 모드로 시작.

회계 계정·은행·wallet 연결은 첫 추천의 필수 단계가 아니다. 현재 재고가 없으면 정확한 자동 보충을 준비했다고 표시하지 않는다. 연결 실패 시 sample demo를 별도 배지로 보여주고 실제 데이터와 섞지 않는다.

### 12.3 화면별 명세

| 화면 | 핵심 내용 | 주 행동 | 필수 예외 상태 |
|---|---|---|---|
| Today | 오늘 결정할 주문, 미확인 supplier, 늦은 입고, invoice 차이 | Review order, Check delivery | stale data, 연결 끊김, budget 초과 |
| Inventory | SKU·사진·수량·예상 소진일·입고 예정·supplier | 수량 확인, 보충 계획 보기 | 단위 불명, 음수 수량, 이중 source |
| Orders | supplier별 PO·총액·ETA·확인 상태 | 승인·전송·수정·취소 요청 | 전송 결과 불명, 가격 변경, 부분 수락 |
| Suppliers | 거래 조건·품목·마지막 가격·납기 실적 | catalog 수입, 연락처 검증 | 납품 불가 지역, 오래된 가격표 |
| Receiving | 오늘 도착할 PO, scan, 수량·손상 기록 | Receive items | 부분 입고, 초과 입고, 다른 SKU |
| Bills | invoice·PO·입고 나란히 대조 | 차이 해결, 승인, 결제 준비 | 중복 invoice, 새 계좌, 세금·운임 차이 |
| Connections | 연결 계정·권한·범위·상태·마지막 성공 시각 | 재연결, sync, 해제 | revoked, rate limited, backfill 중 |

### 12.4 Today 화면의 예시

샘플 데이터 기준으로 "오늘 검토할 발주 3건", "예상 구매액 $842", "납기 확인 필요 1건"을 상단에 표시한다. 아래 supplier 카드에는 상품 수, 총액, ETA, 품절 위험 상품을 보여준다.

재고 추천을 열면 다음 정보를 한 화면에서 확인할 수 있어야 한다.

- 현재 18개, 하루 약 6개 판매, 3일 뒤 소진 예상.
- supplier 납기는 4일, 5상자/60개 주문 제안.
- item subtotal, 운임, 세금/추정 여부, 총 승인 금액.
- 주문하지 않았을 때의 예상 문제와 계산 기준 날짜.
- 수량 수정, 이번만 제외, 다음 주까지 보류, 승인 후 보내기.

수정 이유를 "이미 전화로 주문함", "현재 수량이 틀림", "판매 예상이 과함", "가격이 높음", "단종 예정" 등으로 남길 수 있게 한다. 이유는 모델 평가에 사용하되 한 번의 거절을 영구 선호로 학습시키지 않는다.

### 12.5 시각·상호작용 규칙

- 차분한 밝은 배경, 강한 본문 대비, 한 가지 주 행동 색상을 사용한다. 기존 Tabula의 따뜻한 색상은 살릴 수 있다.
- status는 색상과 텍스트를 함께 사용한다. Awaiting supplier와 Received를 명확히 구분한다.
- 표의 숫자는 오른쪽 정렬, 단위·통화를 항상 표시한다.
- mobile에서는 supplier별 카드와 하단 승인 버튼, desktop에서는 고정 열과 상세 drawer를 사용한다.
- 버튼마다 loading·disabled·success·error를 구현한다. 발주·지급은 낙관적 성공 표시를 하지 않는다.
- 충분한 touch target, keyboard navigation, focus 상태, screen reader label을 제공한다.
- scan 기능에는 카메라 권한 거절·barcode 미인식 시 수동 입력 경로가 필요하다.
- chatbot은 도구 실행 전에 구조화된 주문 미리보기로 연결한다. 대화 문장만으로 금액·수취인 변경을 숨기지 않는다.
- 전송 후에는 Undo 버튼 대신 실제 가능한 "취소 요청"을 제공한다. 취소 가능 시간을 보장하지 않는다.

### 12.6 화면에 넣지 않을 요소

owner-facing 첫 화면에서 agent 토론 transcript, token 수, chain network, raw JSON, model confidence 숫자, ecosystem 점수는 제거한다. 사용자가 검토할 수 있는 주문 근거·원문·상태 이력은 계속 제공한다.

## 13. 권장 backend 구조

### 13.1 기술 선택

| 영역 | 제안 | 이유 |
|---|---|---|
| Web | 기존 React + Vite + TypeScript | 현재 화면·컴포넌트 재사용 |
| Server state | TanStack Query 등 한 가지 query cache | stale·retry·mutation 처리 일관화 |
| API | FastAPI 단일 app, domain router | 기존 Python/Pydantic 코드 활용 |
| Operational DB | PostgreSQL + migration tooling | PO·승인·원장·예산의 transaction과 고유 제약 |
| Existing data | MongoDB에서 선택적으로 이관 | big-bang rewrite를 피하고 canonical store는 하나로 정함 |
| Async work | SQS 같은 durable queue + Python worker | webhook, import, 발주 전송의 재시도·DLQ |
| Document storage | S3 호환 object storage | 원본 invoice·PO·추출 근거 저장 |
| Auth | 기존 Auth0 연결을 실제 route에 적용 | identity와 조직 membership 분리 |
| Realtime UI | SSE 또는 짧은 polling | import·agent·주문 상태 업데이트 |
| Cache | 필요할 때 Redis | 원장/승인의 유일한 저장소로 쓰지 않음 |
| Observability | 구조화 log·trace·error reporting | connector→PO→provider 추적 |

이 선택들은 제안이며 저장소에 이미 PostgreSQL/AWS production이 구성됐다는 뜻이 아니다. 초기에는 API와 worker를 소수의 container로 운영하고 Kubernetes·다수 microservice를 요구하지 않는다.

### 13.2 모듈 구조 제안

```
clawbot/api/          단일 FastAPI app과 router
clawbot/connectors/   square, shopify, sheets, accounting adapters
clawbot/domain/       catalog, inventory, purchasing, receiving, billing
clawbot/agents/       기존 agent와 문서·응답 해석 역할
clawbot/workflows/    import, reconcile, replenish, order execution
clawbot/policies/     approval, spend, supplier eligibility
clawbot/persistence/  PostgreSQL models, migrations, repositories
clawbot/payments/     quote, provider adapter, ledger reconciliation
demo-ui/src/          실제 운영 화면과 별도 demo fixtures
```

모든 외부 쓰기는 domain service를 거치고 동일한 권한·idempotency 검사를 받는다. MCP, web UI, batch worker가 각각 별도의 주문 규칙을 구현하지 않는다.

### 13.3 처리 흐름

```
Provider webhook -> 서명 검증 -> raw event 저장/중복 제거 -> durable queue
Worker -> 최신 provider 상태 조회 -> 정규화 -> 재고/판매 읽기 모델 갱신
계획 job -> forecast + supplier 제약 + budget -> recommendation/PO draft
사용자 또는 정책 승인 -> immutable revision 승인 -> outbox 기록
Sender worker -> supplier 채널 전송 -> 접수 상태 확인
입고/Invoice -> 수량·금액 대조 -> 회계 export/승인된 지급 경로
```

외부 이벤트는 순서가 뒤바뀌거나 여러 번 도착할 수 있다고 가정한다. 외부 API를 포함한 전체 작업에 "exactly once"를 약속하지 않는다. 내부 unique constraint, outbox, provider idempotency, 재조회로 결과가 한 번만 반영되도록 설계한다.

## 14. 데이터베이스 최소 명세

| 테이블 | 주요 필드·책임 |
|---|---|
| tenants, users, memberships | 조직, 역할, 사용자 identity, location 권한 |
| locations | timezone, 영업일, 배송 주소, provider location mapping |
| connector_accounts | provider, external merchant ID, encrypted credential ref, scopes, status |
| sync_cursors, connector_events | cursor, event ID, source timestamp, raw payload ref, processed 상태 |
| products, variants | 내부 ID, SKU, barcode, 규격, base unit, active/discontinued |
| external_item_mappings | provider object ID와 variant의 대응, 검증 상태 |
| inventory_snapshots | variant/location/source별 수량·기준 시각 |
| inventory_movements | 고유 source event, delta, reason, receipt/ref, actor |
| sales_orders, sales_lines | origin 거래 ID, 시각, 수량, 반품·취소 상태 |
| suppliers, supplier_accounts | 연락처, merchant account, 주문 채널, 계약 조건 |
| supplier_items | supplier SKU, variant mapping, case pack, MOQ, 단가·통화·유효일 |
| supplier_quotes | 가격·운임·ETA·원문·유효기간·견적 유형 |
| forecasts, replenishment_plans | 입력 cutoff, 모델/정책 version, 제안 수량·근거 |
| purchase_orders, po_lines, po_revisions | 확정 revision, 금액, line별 수량과 supplier 상태 |
| approvals, budget_reservations | 승인 범위·한도·사용자·만료, 예약된 지출 |
| supplier_acknowledgements | supplier 응답과 counteroffer, confirmation ID |
| receipts, receipt_lines | 실제 수령·손상·거절·게시 상태와 수정 이력 |
| invoices, invoice_lines, match_results | supplier invoice key, 원문, 추출값, PO/입고 대조 |
| payment_orders, provider_transactions | 지급 승인, beneficiary ref, 상태, provider event |
| documents, extraction_runs | 원본 hash, 저장 위치, parser/model version, 검토 상태 |
| outbox, job_runs, audit_events | 재시도·외부 쓰기·행동 이력 |

공통 필드는 tenant_id, UUID 식별자, created/updated 시각, source reference, 필요한 경우 revision이다. tenant 범위가 있는 foreign key와 unique constraint를 사용한다. DB row-level policy를 보조 방어로 적용할 수 있지만 API membership 검사도 유지한다.

필수 고유 제약 예시:

```
(tenant_id, provider, external_event_id)
(tenant_id, provider, external_order_id, external_line_id)
(tenant_id, supplier_id, normalized_invoice_number)
(tenant_id, po_id, revision, action_type)       # 발주 전송 operation
(tenant_id, payment_operation_id)              # invoice 분할 지급은 별도 operation
```

invoice 번호가 재사용되는 공급업체는 회계연도·통화·원문 hash를 이용한 검토 규칙을 추가한다. 번호 충돌을 자동 삭제하지 않는다. 환불·분할 지급·credit note 때문에 invoice당 payment 1개라는 단순 제약은 부적절하다.

금전 흐름을 직접 운영하게 되는 단계에는 journal entry와 entry line을 둔 복식 원장을 추가한다. 통화별 차변/대변 합계 검증, 수수료와 원금 구분, provider balance 대조를 한다. 단순 payment status 목록을 정산 원장으로 간주하지 않는다.

## 15. API 계약과 connector 인터페이스

### 15.1 내부 API 제안

| Endpoint | 목적 | 필수 조건 |
|---|---|---|
| POST /v1/connectors/{provider}/authorize | OAuth 시작 | membership·state binding |
| GET /v1/connectors/{id}/status | 연결·sync 상태 | tenant 범위 |
| POST /v1/imports | 파일 수입 job | 파일 타입·크기·hash 검증 |
| POST /v1/imports/{id}/confirm-mapping | 열/단위 매핑 확정 | import revision |
| GET /v1/inventory | 위치별 재고·신선도 | pagination·filter |
| POST /v1/replenishment-runs | 발주 계획 계산 | data cutoff·policy version |
| GET /v1/recommendations | 근거 포함 추천 | stale 상태 표시 |
| POST /v1/purchase-orders | draft 생성 | supplier·SKU 검증 |
| POST /v1/purchase-orders/{id}/approve | revision 승인 | 금액·권한·budget 원자적 검증 |
| POST /v1/purchase-orders/{id}/send | supplier 전송 예약 | 승인 revision·idempotency key |
| POST /v1/purchase-orders/{id}/cancel-request | 취소 요청 | supplier 완료 응답 별도 |
| POST /v1/receipts | 부분/전체 수령 기록 | line mapping·중복 검증 |
| POST /v1/invoices | invoice 수입 | document hash·supplier key |
| POST /v1/payments/quotes | 비용·수취액 비교 | 지원 rail만 반환 |
| POST /v1/payments/{id}/approve | 지급 승인 | invoice revision·payee |
| POST /v1/payments/{id}/execute | 지급 실행 | 정책·고유 operation |
| GET /v1/tasks | owner가 해결할 예외 | 우선순위·관련 객체 |
| GET /v1/audit-events | 행동·상태 변경 조회 | 역할 기반 접근 |

오래 걸리는 import·agent·전송 작업은 202 Accepted와 job ID를 반환한다. HTTP 성공 자체를 supplier 접수로 표시하지 않는다. mutation의 응답에는 최신 version과 실제 현재 상태를 포함한다.

### 15.2 Connector 공통 계약

```
authorize / refresh / revoke
discover_locations
backfill_catalog(cursor)
backfill_sales(start, end, cursor)
fetch_inventory(location, cursor)
normalize_event(raw_event)
reconcile(checkpoint)
post_receipt(receipt, operation_id)        # provider가 지원하고 write owner일 때만
health / capabilities
```

capabilities는 sales_read, inventory_read, inventory_write, supplier_read, po_read, po_write 등을 실제 지원 여부로 선언한다. 없는 API를 agent가 호출할 수 있는 것처럼 tool list에 넣지 않는다.

## 16. 운영 신뢰성과 보안 요구사항

1. 동기화: webhook signature, 저장 후 ack, event dedupe, 재시도 backoff, dead-letter queue, 야간 대조.
2. 외부 결과 불명: 주문 API가 timeout됐을 때 다시 create하지 않고 operation ID/상태 조회로 확인한다. 이메일도 발송 기록을 확인하고 불명 상태를 owner task로 보낸다.
3. 트랜잭션: 승인+budget 예약+outbox 기록을 한 DB transaction으로 묶는다. worker 장애 후에도 재개 가능해야 한다.
4. 권한: owner/manager/receiver/bookkeeper 역할을 분리한다. receiver는 수량 확인을 할 수 있지만 지급 계좌를 바꿀 수 없다.
5. 데이터 접근: OAuth 최소 권한, 암호화된 token, credential을 prompt/log에 넣지 않기, tenant별 조회 제한.
6. 파일: 원본 document 접근 URL 만료, MIME/크기 검증, 악성 파일 검사, parser 실패 격리.
7. 감사: actor, before/after, 이유, approval, provider reference, 시간 기록. 수정은 이력을 남긴다.
8. 복구: DB backup·복구 연습, raw event replay, connector credential revoke와 재연결.
9. 데이터 단절: 마지막 성공 시각을 표시하고 정해진 freshness 기준을 넘으면 자동 발주 중지.
10. 종료·export: merchant가 PO·공급업체 mapping·거래 이력을 내보내고 계정을 해제할 수 있게 한다.

Gmail 전체 inbox 접근은 초기 필수 기능으로 만들지 않는다. restricted scope는 추가 verification과 경우에 따라 security assessment를 요구한다. 전용 수신 주소로의 전달과 문서 업로드로 먼저 시작하고, 직접 Gmail 연결은 사용자 가치가 충분할 때 진행한다. [S15]

정식 감사나 certification을 받기 전에는 SOC 2 등 인증이 완료됐다고 표시하지 않는다. 이 요구사항은 실제 고객의 재고·지출을 자동 처리하는 기능에 필요한 제품 조건이다.

## 17. 경쟁 제품과 차별화 가설

| 제품 | 공식 자료에서 확인한 기능 | Tabula에 주는 의미 |
|---|---|---|
| Square Retail | supplier 관리·PO·입고 | 기본 PO 화면만으로는 충분하지 않음 [S05] |
| Shopify + Sidekick | 재고 분석·재주문 추천·PO/transfer 초안 | 챗봇+재고 추천은 이미 플랫폼 기능 [S08] |
| Prediko | AI 재고 계획·발주·supplier 연계·AI agent | "AI inventory agent"라는 표현만으로 차별화 안 됨 [S27] |
| Inventory Planner | 수요 계획·supplier 조건·PO 관리 | forecasting 자체도 기존 시장 [S28] |
| MarketMan | 음식점 재고·레시피·invoice·발주·회계 연결 | 음식점은 기능 깊이와 경쟁 부담이 큼 [S29] |
| Choco | distributor 주문 처리·ecommerce·AI | 이메일 주문 자동화도 경쟁이 존재 [S30] |

차별화 가설: 특정 업종의 소형 매장이 기존 supplier를 유지하면서, 데이터 정리부터 supplier 응답·부분 입고·invoice 차이까지 적은 설정으로 처리한다. 이 조합이 경쟁사보다 낫다는 점은 아직 증명되지 않았다. 실제 비교 파일럿에서 온보딩 시간·예외 해결률·주간 절약 시간으로 검증해야 한다.

장기 자산은 merchant가 승인한 SKU↔supplier mapping, pack size, 실제 lead time, 단가 변경, 주문·입고·invoice의 연결 이력이다. 모든 매장 데이터를 공유해야 생기는 네트워크 효과를 전제로 하지 않아도 된다.

## 18. 고객 검증과 가격 실험

### 18.1 먼저 볼 자료와 물어볼 질문

- 지난 두 번의 발주 과정을 화면 또는 실제 문서로 보여줄 수 있는가?
- POS, 재고 파일, 회계 프로그램, supplier portal을 각각 무엇을 쓰는가?
- 주문할 수량은 어떻게 결정하는가? 품절·과잉재고를 최근에 언제 겪었는가?
- supplier는 이메일·전화·portal 중 어떤 방식으로 주문을 받는가?
- 매주 발주와 invoice 확인에 실제 몇 분이 드는가?
- 재고 수량은 얼마나 믿을 만한가? 마지막 실사는 언제인가?
- 이미 주문한 물건을 두 번 주문하는 일이 있는가?
- 자동 발주를 허용할 상품·금액 범위는 무엇인가?
- 결제 비용·해외 송금이 실제 불편인가, 아니면 주문 업무가 더 큰가?
- 현재 기능을 사용하기 위해 월 얼마를 지불할 의사가 있는가?

"AI agent를 쓰고 싶은가?"보다 현재 업무의 자료와 시간을 확인한다. supplier를 아예 바꾸기 싫다는 반응을 제품 실패로 보지 않고 기존 관계를 지원하는 설계에 반영한다.

### 18.2 파일럿 설계

초기 목표는 동일 업종·유사 POS의 5개 매장과 각 매장의 주요 supplier 2–3곳이다. 첫 1–2주에는 shadow mode로 merchant의 실제 발주와 추천을 비교한다. 이후 owner 승인 방식으로 전송하고 최소 3회의 발주→입고 cycle을 관찰한다.

모든 품목을 한 번에 자동화하지 않고, 신뢰할 수 있는 상위 50–200개 반복 판매 SKU부터 시작한다. 수입 데이터 정리를 사람이 도왔으면 assisted onboarding 시간으로 기록한다.

### 18.3 측정할 지표

| 지표 | 정의 |
|---|---|
| Time to first useful plan | 연결 시작부터 owner가 검토 가능한 첫 계획까지 |
| Weekly ordering minutes | 추천 검토·supplier 확인·입고·invoice 업무의 실제 시간 |
| Unchanged approval rate | 수량·supplier 수정 없이 승인된 추천 비율 |
| Execution completion rate | supplier 확인과 입고까지 완료된 전송 PO 비율 |
| Exception rate | 추가 사람 개입이 필요한 발주·입고 비율 |
| Inventory accuracy | 표본 실사와 시스템 수량의 차이 |
| Duplicate execution count | 중복 발주·중복 재고 게시·중복 지급 건수 |
| Support minutes/account | 창업자가 고객 한 곳을 유지하는 데 쓰는 시간 |
| Retention and paid usage | 반복 사용·실제 지불·해지 이유 |

품절 감소와 매출 상승은 seasonality와 판매 조건 영향을 받는다. 단순 전후 비교만으로 모두 Tabula 효과라고 말하지 않는다. 구매 시간·중복 제거·invoice 차이 탐지는 초기에도 더 직접 측정할 수 있다.

### 18.4 가격 실험 가설

첫 가격 실험은 매장당 월 $99–$249 범위에서 문제 강도와 지원 비용을 보고 진행할 수 있다. 이는 조사로 확인된 시장 가격이나 지불 의향이 아니라 테스트 범위다. 초기에는 재고를 많이 구매하도록 유도하는 GMV 수수료보다 정액 구독이 이해하기 쉽다.

순가치 계산은 절약한 실제 업무 시간 × merchant가 인정하는 시간 가치 + 검증된 오류/손실 감소 - 추가 비용 - 구독료로 한다. 매출 증가액을 그대로 순이익처럼 계산하지 않는다.

## 19. 구현 순서와 출시 기준

아래는 1–2명의 개발자와 협조적인 design partner를 가정한 순서 제안이다. 앱 심사·고객 데이터 품질·결제 승인 때문에 기간은 달라질 수 있다. 주차보다 완료 기준을 우선한다.

| 단계 | 작업 | 완료 기준 |
|---|---|---|
| 0: 고객/데이터 확인 | 인터뷰, 실제 파일, supplier 주문 흐름 | 한 업종·한 POS·반복 SKU·주문 채널 선정 |
| 1: 운영 기반 | tenant/auth, DB schema, inventory event, outbox | 고객 간 데이터 분리·중복 이벤트 검증 |
| 2: 실제 연결 | POS 하나 + CSV/Sheets + 미입고 주문 | 샘플 거래·재고·환불이 원본과 일치 |
| 3: 추천 | deterministic replenishment·unit mapping·budget | merchant 기존 발주와 비교할 수 있는 근거 |
| 4: 실제 발주 | PO revision·approval·email·supplier acknowledgement | 한 실제 PO가 supplier에게 확인됨 |
| 5: 입고/청구 | partial receipt·invoice extraction·match | 3회 이상 전체 cycle 추적 |
| 6: 제한 자동화 | approved SKU·supplier·예산 조건 | 장애·중복·가격 변경 시 멈춤 검증 |
| 7: 확장 | 회계·두 번째 POS·지원되는 결제 | 고객 유지·반복 사용과 운영비 검증 |

YC 이전 핵심 데모는 connector가 실제 데이터를 읽고, 한 SKU의 보충량을 설명하며, supplier별 PO를 만들고, owner 승인 후 접수 상태를 추적하고, 부분 입고 차이를 보여주는 흐름이다. 실제 전송·결제가 없으면 화면에 demo/sandbox를 명확히 표시한다.

### 19.1 구현 백로그

| ID | 우선순위 | 요구사항 | 완료 판정 |
|---|---|---|---|
| CORE-01 | P0 | tenant membership과 route auth | 다른 tenant의 객체 ID로 접근 불가 |
| CORE-02 | P0 | DB migration과 unique event key | 같은 event 반복 처리 시 결과 불변 |
| CON-01 | P0 | 첫 POS OAuth/backfill | 실제 계정 데이터 표본 대조 |
| CON-02 | P0 | webhook·reconciliation | webhook 유실 후 polling으로 복원 |
| IMP-01 | P0 | CSV·Sheets mapping preview | 잘못된 단위가 승인 전 차단 |
| CAT-01 | P0 | supplier SKU·case pack mapping | 12개입 상품이 주문·입고에서 일치 |
| INV-01 | P0 | 재고 source owner | 판매 또는 입고 중복 반영 없음 |
| PLAN-01 | P0 | 수요·lead time·열린 PO 반영 | 숫자 예시와 boundary case 통과 |
| PO-01 | P0 | 영속 PO·revision·approval | 서버 재시작 뒤 승인 상태 유지 |
| PO-02 | P0 | budget 예약+outbox | 동시 승인 시 한 번 전송 |
| SUP-01 | P0 | 이메일·확인 페이지 | 발송/수락/변경 제안을 구분 |
| REC-01 | P0 | 부분 입고·손상 | 잔량 유지 및 재고 한 번 게시 |
| BILL-01 | P1 | invoice 추출·대조 | 중복·단가·수량 차이 task 생성 |
| ACC-01 | P1 | QuickBooks 기록 export | 재고 이중 반영 없는 장부 대조 |
| PAY-01 | P0 | SaaS 구독 | 물품대금과 분리된 billing |
| PAY-02 | P1 | supplier 지급 adapter | 지원 모델·onboarding·return 경로 확인 |
| PAY-03 | P2 | 국제 stablecoin 파일럿 | 실제 총비용과 법인 수취 지원 검증 |
| UI-01 | P0 | Today와 order detail | 버튼이 실제 상태·권한과 연동 |
| UI-02 | P0 | mobile receiving | scan 실패 시 수동 입력 가능 |
| OPS-01 | P0 | logs·DLQ·alert·backup | 실패 event 재처리·복구 확인 |

### 19.2 반드시 검증할 실패 사례

- 같은 판매 webhook 10번 수신, 환불이 판매보다 먼저 도착.
- 같은 PO를 두 명이 동시에 승인.
- 주문 제출 후 네트워크 timeout, supplier가 실제로는 접수함.
- 10상자 주문 중 8상자 입고, 1상자 손상, 나머지 backorder.
- supplier가 12개입을 24개입으로 변경함.
- 주문 승인 뒤 단가·shipping fee가 올라감.
- 같은 invoice가 이메일과 업로드로 두 번 들어옴.
- 은행 승인 뒤 ACH가 반환됨.
- supplier 문서에 새로운 계좌 또는 지시문이 들어옴.
- POS 권한 취소, webhook 장기 유실, Sheets 열 위치 변경.
- scheduler와 수동 실행이 동시에 같은 SKU의 보충을 계산.
- tenant A의 agent가 tenant B의 PO ID를 tool argument로 제출.

이 테스트들은 실제 지출·재고 중복과 고객 간 데이터 노출을 막기 위한 출시 gate다. UI 색상 등 낮은 위험의 변경에 같은 수준의 테스트 부담을 주지 않는다.

## 20. YC 지원에 반영할 내용

지원서의 중심은 특정 매장 주인의 반복 구매 업무와 실제 해결 증거다. agent 수, ecosystem 크기, stablecoin 기술 자체를 중심 성과로 내세우지 않는다.

| 질문 | 설명할 내용 | 필요한 증거 |
|---|---|---|
| 누구의 문제인가? | 선택한 업종·규모·발주 담당자 | 인터뷰와 실제 workflow |
| 무엇을 하는가? | POS→보충 계획→기존 supplier 발주→입고 대조 | 작동하는 한 cycle |
| 왜 지금 가능한가? | 접근 가능한 commerce API와 비정형 문서 처리 | 실제 connector·추출 정확도 |
| 기존 도구와 무엇이 다른가? | 적은 설정, 기존 supplier 지원, 예외 해결 | 경쟁 대안 대비 시간·완료율 |
| 얼마나 진행됐는가? | 실제 연결 매장·발주·활성 사용·매출 | 로그·거래·고객 확인 |
| 어떻게 커지는가? | 한 업종의 구매 workflow를 반복 가능한 제품으로 확장 | 온보딩·지원 비용 감소 |

첫 고객의 3회 발주를 제대로 처리한 기록이 가상 매장 수십 개의 시뮬레이션보다 제품 가설을 더 직접 검증한다. 아직 사용자·매출·발주가 없다면 현재 단계와 다음 검증을 솔직히 구분한다.

핵심 기술적 진전으로 주장할 수 있는 후보는 다양한 source의 상품·단위 정규화, 예산·승인이 보장되는 외부 실행, supplier 응답·부분 입고·invoice의 연결이다. 그 성능은 실제 자료로 측정한 뒤 기재한다.

## 21. 남아 있는 확인 사항

| 항목 | 현재 상태 | 제품 결정에 미치는 영향 |
|---|---|---|
| 첫 업종과 실제 design partner | 가설 | 펫용품·뷰티·기존 접근 가능한 매장 중 선정 |
| 고객의 실제 POS 분포 | 미확인 | 첫 connector 우선순위를 바꿀 수 있음 |
| 현재 재고 정확도 | 미확인 | 자동 보충 전에 실사 작업이 필요할 수 있음 |
| supplier별 주문 접수 방식 | 일부 공식 경로만 조사 | 자동 전송 범위를 결정 |
| 플랫폼 앱 심사·과거 주문 접근 승인 | 미확보 | backfill 범위와 출시 일정 |
| supplier 결제 모델의 provider 승인 | 미확보 | 실제 supplier payment 출시 gate |
| 국제 stablecoin의 특정 국가·법인 경로 | 미검증 | 홍보 기능으로 약속하지 않음 |
| 고객 지불 의향·지원 비용 | 미검증 | 가격·업종 선택의 핵심 |
| 저장소 밖 운영 코드 | 미검토 | 재사용 범위가 달라질 수 있음 |

이 문서의 다음 구현 단위는 tenant/auth와 첫 POS 수입을 갖춘 실제 데이터 경로, supplier SKU mapping, 승인 가능한 PO다. 결제와 두 번째 POS는 해당 경로가 실제 매장에서 반복 사용되는지 확인하면서 추가한다.

## 출처: 공식 자료

모든 링크는 이번 조사에서 검색 또는 본문 열람으로 확인했다. 제공사의 기능 설명은 제품 지원 범위를 확인하는 데 사용했으며, 그 자체를 독립적인 성능 검증으로 취급하지 않았다.

- S01 Block 2024 Form 10-K — Square 판매자 수
- S02 Toast 2025 Form 10-K — 운영 장소 수
- S03 Intuit QuickBooks Small Business Insights — 도구 사용과 조사 방법
- S04 Square API Reference
- S05 Square purchase orders
- S06 Shopify API access scopes
- S07 Shopify GraphQL bulk operations
- S08 Shopify: Stocky에서 inventory management로 전환
- S09 Clover OAuth · Webhooks
- S10 Lightspeed X-Series API · Inventory updates
- S11 QuickBooks BillPayment API · PO 작성 안내
- S12 Toast partner integration
- S13 Xero invoices · Purchase orders
- S14 Google Sheets API usage limits
- S15 Gmail API scopes
- S16 Faire retailer POS integrations 및 custom API 제한
- S17 Faire developer API
- S18 Phillips Pet Food & Supplies 주문 지원
- S19 Amazon Business Ordering API
- S20 Stripe pricing — 국가별 페이지와 상품별 요율 확인 필요
- S21 Stripe ACH Direct Debit
- S22 Stripe stablecoin payments
- S23 Stripe Connect stablecoin payouts 및 수취인 제한
- S24 Stripe Global Payouts
- S25 Bridge orchestration
- S26 Stripe idempotent requests
- S27 Prediko purchase order management · 2026년 9월 제품 업데이트
- S28 Inventory Planner supplier management
- S29 MarketMan platform
- S30 Choco distributor platform

## 출처: Tabula 코드

- R01 README
- R02 재고 DB 작업
- R03 조달 DB 작업
- R04 Pending orders · Universal agent
- R05 Orders 화면 · 공통 UI
- R06 Frontend data · Inventory 화면
- R07 Auth helper · Inventory routes
- R08 Procurement agent · Procurement routes
- R09 Sales history · Requirements
- R10 AGENTS · Price discovery playbook
