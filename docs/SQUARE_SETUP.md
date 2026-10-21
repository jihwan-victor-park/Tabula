# Square 연결 설정 (CP4)

Square 작업은 두 갈래로 나뉜다. **둘은 서로 기다리지 않는다.**

| | Sandbox 개발 | App Marketplace 등재 |
|---|---|---|
| 목적 | 우리 코드가 Square API와 실제로 맞물리는지 검증 | Square 판매자들이 앱을 찾아 설치하게 하는 배포 채널 |
| 필요한 것 | 무료 Square Developer 계정 + Sandbox 앱 | 제품 완성도, 보안·개인정보 문서, Square 심사 |
| 지금 상태 | 코드 준비 완료(mock으로 테스트됨). **실제 Sandbox 호출은 아직 하지 않음** | 시작 전. CP7 이후 검토 |

파일럿 매장 몇 곳을 OAuth로 직접 연결할 때 Marketplace 등재가 필요한지는 **Square 문서에서 확인이 필요하다**. 확인 전에는 "등재 없이도 파일럿 연결 가능"이라고 가정하지 않는다.

## 1. 직접 등록해야 할 것

1. **Square Developer 계정**: https://developer.squareup.com 에서 가입한다. Square 판매자 계정으로도 로그인할 수 있다.
2. **애플리케이션 생성**: Developer Dashboard → *Applications* → *+*. 이름은 예를 들어 `Tabula (dev)`.
3. **Sandbox 테스트 판매자**: Dashboard → *Sandbox test accounts*. 기본 테스트 계정이 있으며, *Open in Square Dashboard*에서 테스트 location·상품·주문을 만들 수 있다.
4. **OAuth 설정**: 앱 → *OAuth* 탭에서 **Sandbox** 쪽을 고른다.
   - *Redirect URL*: `https://<내 API 주소>/v1/connectors/square/callback`. 로컬에서는 공개 HTTPS 터널(ngrok, Cloudflare Tunnel 등)의 주소를 쓴다.
   - *Application ID*와 *Application secret*을 확인한다. 화면에서 복사해 아래 환경변수에 넣는다.
5. **Webhook 구독**: 앱 → *Webhooks* → *Subscriptions*에서 **Sandbox**를 고른다.
   - URL: `https://<내 API 주소>/v1/connectors/square/webhook`
   - 이벤트: `inventory.count.updated`, `order.created`, `order.updated`, `catalog.version.updated`
   - 구독을 만든 뒤 *Signature key*를 확인한다.

## 2. 환경변수 (비밀값은 채팅·git에 넣지 않는다)

`.env`(git 제외) 또는 배포 환경의 secret store에 넣는다. 값은 Developer Dashboard에서 복사한다.

```bash
SQUARE_ENVIRONMENT=sandbox                   # mock(기본) | sandbox | production
SQUARE_APPLICATION_ID=                       # Dashboard → Credentials (Sandbox 탭)
SQUARE_APPLICATION_SECRET=                   # Dashboard → OAuth (Sandbox) → Application secret
SQUARE_REDIRECT_URL=https://<api>/v1/connectors/square/callback   # 등록한 값과 정확히 같게
SQUARE_WEBHOOK_SIGNATURE_KEY=                # Webhooks → 구독 → Signature key
SQUARE_WEBHOOK_URL=https://<api>/v1/connectors/square/webhook     # 구독에 등록한 URL과 정확히 같게(서명 계산에 포함)
SQUARE_API_VERSION=2024-10-17                # 고정 버전. Dashboard의 앱 API 버전과 맞춘다
TABULA_TOKEN_ENCRYPTION_KEY=                 # 저장 토큰 암호화 키. 아래 명령으로 한 번 생성해 secret store에 보관
```

암호화 키는 다음 명령으로 만든다. 출력값을 `.env`에 직접 넣고, 다른 곳에 붙여넣지 않는다.

```bash
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

- `SQUARE_ENVIRONMENT=production`은 `TABULA_ENV=production`이 아니면 서버가 거부한다. 개발 중에는 실제 판매자 계정에 닿을 수 없다.
- 키를 교체할 때는 새 키를 `TABULA_TOKEN_ENCRYPTION_KEY`에, 이전 키를 `TABULA_TOKEN_ENCRYPTION_KEYS_OLD`에 넣는다.

## 3. 연결 순서 (API)

1. `POST /v1/connectors/square/authorize` → 응답의 `authorize_url`을 브라우저에서 열고 Sandbox 판매자로 승인한다.
2. Square가 `/v1/connectors/square/callback`으로 돌려보낸다. 연결이 생성되고, 토큰은 암호화되어 저장된다.
3. `GET /v1/connectors/{id}/external-locations` → `POST /v1/connectors/{id}/locations`로 Square location과 Tabula location을 **하나씩** 연결한다. 이 location의 재고 기준은 Square가 된다.
4. `POST /v1/connectors/{id}/sync {"kind": "catalog"}`
   - SKU나 바코드가 일치하는 상품은 매핑 **제안**이 생긴다. `/v1/external-mappings/{id}/decision`에서 사람이 확정한다.
   - 일치하지 않는 상품은 `/v1/connectors/{id}/adopt-items`로 새로 만든다.
5. `POST /v1/connectors/{id}/sync {"kind": "sales"}`는 기본으로 최근 90일을 가져온다. `{"kind": "inventory"}`는 현재 재고를 가져온다.
6. worker를 실행한다: `python -m clawbot.workflows.connector_worker` (import worker와 별도).

## 4. 동작 원칙 (명세 3.2)

- 위치는 판매자가 고른다. 같은 판매자의 location을 자동으로 합산하지 않는다.
- 판매는 Square의 order ID + line UID로 저장한다(`key_scheme=provider_line`). 같은 주문이 CSV로 이미 들어와 있으면 이중으로 집계하지 않고 검토 대상으로 돌린다.
- 재고는 snapshot으로 저장한다. Square가 재고를 소유한 location에는 Tabula가 재고를 쓰지 않는다.
- webhook은 서명을 확인한 뒤 원본을 먼저 저장하고, event_id로 중복을 제거한다. 처리할 때는 이벤트 본문을 믿지 않고 Square에서 현재 상태를 다시 조회한다.
- 동기화가 끝난 기간은 sales coverage로 기록한다. 그 기간 안의 판매 없는 날은 "판매 0"으로 본다.

## 5. 항목별 상태 — mock 검증 vs Sandbox 실호출 검증

Sandbox 열은 `scripts/square_sandbox_check.py`가 통과한 항목만 ✓로 바꾼다. **지금은 자격증명이 없어 Sandbox 실호출은 한 번도 하지 않았다.**

| 항목 | 구현 | mock 검증 | Sandbox 실호출 |
|---|---|---|---|
| OAuth 연결(state 1회용·브라우저 binding·토큰 암호화) | ✓ | ✓ | ✗ 미검증 |
| 상품(catalog) 가져오기 → 매핑 제안 | ✓ | ✓ | ✗ |
| 재고(counts) 가져오기 → snapshot | ✓ | ✓ | ✗ |
| 완료 주문·환불 가져오기 | ✓ | ✓ | ✗ (실제 환불이 별도 order로 오는지 확인 필요) |
| webhook 서명 검증·원본 저장·event_id 중복 제거 | ✓ | ✓ | ✗ (공개 HTTPS 터널 필요) |
| access token 갱신(만료 7일 전, 거부 시 needs_reauth) | ✓ | ✓ | ✗ |
| 연결 해제 → 재연결(같은 판매자: 위치 연결·이력 유지) | ✓ | ✓ | ✗ |
| 정기 동기화(판매 15분·재고 30분) + 야간 최근 3일 재대조(누락 webhook 복구 기록) | ✓ | ✓ | ✗ |
| 판매 원본 소유권: 위치별 files ↔ Square, 전환 시각 이후만 Square | ✓ | ✓ | (정책 — Sandbox 무관) |
| 환불 ≠ 재입고: 환불은 수요를 줄이고, 재입고 여부를 모르면 재고에 더하지 않음 | ✓ | ✓ | ✗ (Square가 재입고를 어디에 기록하는지 확인 필요) |
| 입고를 Square 재고에 반영(쓰기) | ✗ 읽기 전용 | — | — |

### 판매 원본 규칙 (CSV ↔ Square)

- 위치마다 판매 원본은 하나다. 기본은 **files**(업로드)다. Square 위치를 연결해도 판매 원본은 자동으로 바뀌지 않는다.
- **Connections → "Use Square for sales"**로 전환 시각 T를 정한다(기본: 지금).
  - T 이후 판매는 Square에서만 받는다. 같은 기간의 CSV 행은 미리보기에서 오류가 된다.
  - T 이전 Square 주문은 기록하지 않는다. 그 기간은 파일이 기준이다.
  - 현재 원본이 이미 T 이후 판매를 기록했다면 전환이 거부된다. 더 늦은 T를 고른다. 같은 판매가 두 번 세어지지 않게 하기 위해서다.
- 되돌리기(Square → files)도 같은 규칙을 따른다.

### 환불 규칙

- 환불은 그 날의 순판매(수요)를 줄인다.
- 재고에는 **재입고가 확인된 환불만** 더한다. CSV의 `Restocked` 열이 yes인 경우다. Square Orders API의 환불은 재입고 여부를 알려주지 않으므로 "모름"으로 저장하고 더하지 않는다. Square가 재고를 소유한 위치라면 Square 재고 reading에 이미 반영된다.
- 입고 대조 화면에서는 재입고 여부를 모르는 환불을 따로 보여준다. 차이가 0이어도 그것만으로 확인 완료로 보지 않는다.

## 6. 사용자가 설정할 것 (한 번에)

비밀값은 `.env` 또는 secret store에만 넣는다. 채팅·git에 넣지 않는다.

1. Square Developer 계정 → 앱 생성 → **Sandbox** 탭.
2. `.env`에 다음 값을 넣는다(값은 Dashboard에서 복사).
   - `SQUARE_ENVIRONMENT=sandbox`
   - `SQUARE_APPLICATION_ID`, `SQUARE_APPLICATION_SECRET`
   - `TABULA_TOKEN_ENCRYPTION_KEY` (위 2절 명령으로 생성)
3. 공개 HTTPS 주소를 하나 준비한다. ngrok 또는 Cloudflare Tunnel로 `127.0.0.1:5173`(UI + `/v1` 프록시)을 노출한다.
   - `SQUARE_REDIRECT_URL=https://<터널>/v1/connectors/square/callback` — Square OAuth(Sandbox)에 같은 값을 등록한다.
   - `TABULA_UI_URL=https://<터널>` — 연결 후 Connections 화면으로 돌아오는 주소.
   - Webhook 구독 URL `https://<터널>/v1/connectors/square/webhook`, 이벤트 `order.created`, `order.updated`, `inventory.count.updated`, `catalog.version.updated`, `refund.created`, `refund.updated`, `oauth.authorization.revoked`.
   - `SQUARE_WEBHOOK_URL`(같은 URL), `SQUARE_WEBHOOK_SIGNATURE_KEY`.
   - 터널을 쓰면 dev 로그인(loopback 전용)이 막힌다. 그때는 터널 주소로 UI를 쓰지 말고, OAuth 콜백과 webhook만 터널로 받는다. 로컬 UI는 `127.0.0.1:5173` 그대로 쓴다.
4. Sandbox 테스트 판매자 Dashboard에서 location 1개, 상품 2–3개(SKU 입력), 재고, 결제·환불 몇 건을 만든다.
5. 앱 **Connections → Connect Square**로 Sandbox 판매자를 승인한다. 이어서 위치를 연결하고, catalog 동기화 후 매핑 제안을 확정한다.
6. 확인 명령을 실행한다.

   ```bash
   set -a; source .env; set +a
   .venv/bin/python scripts/square_sandbox_check.py
   ```

   결과는 `var/square_sandbox_report.json`에 저장된다. 통과한 항목만 위 표와 `docs/CHECKPOINTS.md`의 D 항목에 반영한다.
