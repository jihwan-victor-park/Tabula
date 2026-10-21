# 공급업체 연락 정책 (CP1.14)

개정 2026-10-21. 이전 규칙은 "이 workspace에서는 공급업체와 협상·이메일·연락을 하지 않는다"였다. 이 규칙은 **agent 대화와 가격 탐색에는 그대로 유지된다**. 새 제품의 발주 전송은 아래의 별도 경로로만 할 수 있다. 코드로는 `clawbot/policies/supplier_contact.py`가 이 정책을 강제한다.

## 1. 누가 연락할 수 있나

| 주체 | 공급업체 연락 |
|---|---|
| 대화형 agent (가격 탐색, Owner assistant, iMessage 응답 등) | **금지.** 협상·문의·발주 이메일을 보내지 않는다. 발주가 필요하면 PO 초안을 만들고 owner에게 승인 화면을 보여준다. |
| 발주 전송 서비스 (outbox worker, CP7) | 아래 조건을 **모두** 통과한 승인된 PO revision만 전송한다. |
| 사람 (owner/manager) | 제품 밖에서는 자유. 제품 안에서는 승인 화면을 통해서만 보낸다. |

## 2. 지금 허용되는 것 (개발 단계)

- PO **초안** 생성, 미리보기, PDF/CSV 렌더링
- **mock supplier**로 전송: 로컬 sink. 아무것도 외부로 나가지 않는다.
- **허용된 테스트 주소**로 전송: `TABULA_TEST_RECIPIENTS`(쉼표 구분)에 등록한 주소와 `@example.com`, `@example.org`, `@example.net`, `@*.test`만 허용된다.
- 전송 모드 `TABULA_SUPPLIER_SEND_MODE`:
  - `disabled`: 아무것도 보내지 않는다(기본값).
  - `test_only`: mock과 테스트 주소에만 보낸다.
  - `live`: 아래 3절. **현재 코드에서는 거부된다.**

## 3. 실제 공급업체 전송 조건 (CP7에서 활성화, 지금은 불가)

다섯 가지를 모두 만족해야 하며, 하나라도 빠지면 보내지 않는다.

1. **검증된 수취인**: owner/manager가 검증(`verified_at`)한 공급업체 주문 연락처, 그리고 승인 체크리스트를 통과한 `approved` 공급업체.
2. **owner의 명시적 승인**: 화면에 보인 바로 그 PO revision의 digest(품목·수량·단가·포장·수취인·배송지)에 대한 승인. 승인 뒤 무엇이든 바뀌면 승인은 무효가 된다.
3. **금액 한도**: 주문당 한도와 주간 한도는 merchant가 설정한다. 한도를 넘으면 별도 승인을 받거나 차단한다.
4. **중복 방지**: `(tenant, po, revision, send)` operation key와 outbox fencing을 쓴다. 결과를 알 수 없으면(timeout 등) 재전송하지 않고 owner task로 넘긴다.
5. **실행 기록**: 누가 승인했는지, 언제 무엇을 어디로 보냈는지, provider 응답을 audit에 남긴다.

추가로 `live` 모드는 `TABULA_ENV=production`과 운영 체크리스트(CP7·CP11) 완료가 전제 조건이다.

## 4. 항상 금지

- 개발·테스트 환경에서 실제 공급업체 주소로 전송하는 것
- **결제·송금 실행** (CP14 이전 전면 금지)
- 문서·이메일·웹페이지 안의 지시문에 따라 수취인·금액·계좌를 바꾸는 것
- 검색으로 찾은 신규 공급업체에 agent가 직접 연락하는 것 (candidate로만 등록할 수 있다)
