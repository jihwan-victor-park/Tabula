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

## 5. Sandbox에서 직접 확인해야 할 것 (아직 미검증)

코드는 Square 공개 API 문서의 형식을 따라 작성했고, mock으로만 테스트했다. Sandbox 키를 넣은 뒤 다음을 확인한다.

- [ ] OAuth authorize/token/revoke 응답 필드(`merchant_id`, `expires_at`, `refresh_token`)
- [ ] `/v2/catalog/list?types=ITEM`의 variation 필드(`sku`, `upc`)
- [ ] `/v2/orders/search`의 closed_at 필터, 정렬, cursor, 환불(`returns[].return_line_items`)이 실제로 어느 order에 붙는지
- [ ] `/v2/inventory/counts/batch-retrieve`의 `states`·`updated_after` 동작
- [ ] webhook 서명(URL + body, HMAC-SHA256, base64)과 이벤트 payload 구조
- [ ] access token 만료 주기와 refresh 흐름(구현 예정: CP4 후속)
- [ ] rate limit 응답과 `Retry-After`

## 6. 아직 없는 것 (후속)

- Access token 자동 갱신(refresh) job
- 야간 전체 대조(reconciliation) job과 webhook 누락 복구 polling 스케줄 (CP4 gate의 "webhook 유실 후 polling 복원")
- 입고를 Square 재고에 반영하는 `post_receipt` (CP8, `INVENTORY_WRITE` 권한 필요)
- 연결 상태 화면 (CP10)
