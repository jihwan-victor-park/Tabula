# 실제 고객 데이터 요청·익명화·비교 (CP0)

**현재 상태: 실제 고객 데이터는 아직 없다.** 지금까지의 검증은 모두 합성 데이터(`clawbot/devtools/seed_demo.py`)와 mock Square로 했다. 실제 파일을 받기 전에는 "고객 데이터로 검증됨"이라고 쓰지 않는다.

## 1. 매장에 요청할 최소 파일

| # | 파일 | 기간·내용 | 왜 필요한가 |
|---|---|---|---|
| 1 | 판매 내역 export (POS) | 최근 **90일 이상**, 거래 ID·날짜·SKU 또는 바코드·수량, 가능하면 환불 여부와 재입고 여부 | 수요 계산. 환불이 재입고됐는지 모르면 재고에 더하지 않는다 |
| 2 | 현재 재고 (실사 또는 POS 재고 보고서) | **기준 시각이 적힌** 한 시점 | 출발 재고 |
| 3 | 공급업체 단가표 | 주 공급업체 2–3곳, supplier SKU·포장 단위(상자당 몇 개)·단가 | 주문 단위 변환, 가격 근거 |
| 4 | 미입고 주문 목록 | 공급업체·주문 번호·SKU·남은 수량·확인 여부·예정일 | 중복 발주 방지. **주문 번호는 꼭 포함**(Tabula PO와 번호로만 연결) |
| 5 | 지난 발주 내역 | 최근 2–3개월, 날짜·공급업체·SKU·수량·단위 | 추천과 실제 발주 비교 (아래 3절) |
| 6 | invoice 3–5장 (선택) | 최근 것 | 단가·포장 단위 교차 확인. CP9 전까지는 참고용 |

고객에게 보낼 문장(영문) 예시:

> To try Tabula on your store we need: (1) a sales export for the last 90+ days from your POS, (2) a current stock count with the date/time it was taken, (3) price lists from your top 2–3 suppliers (supplier SKU, case pack, case cost), (4) your open/unreceived purchase orders with their PO numbers, and (5) your purchase orders from the last 2–3 months. Please run our anonymizer first or remove customer names, emails, phone numbers and card details — we never need them.

## 2. 익명화 (매장 쪽에서, 보내기 전에)

```bash
export PILOT_SALT='<매장이 정하고 보관하는 16자 이상 비밀값>'   # 파일과 함께 보내지 않는다
.venv/bin/python -m clawbot.devtools.anonymize sales_export.csv sales_anon.csv
```

- 고객 이름·이메일·전화·카드·주소·직원 열은 **삭제**한다.
- 주문·거래 ID는 salt로 **해시**한다. 같은 ID는 같은 토큰이 되므로 한 주문의 줄이 묶이고 재수입 중복 제거도 그대로 된다. salt 없이는 되돌릴 수 없다.
- SKU·바코드·수량·가격·날짜·공급업체 이름은 남긴다. 상품 매핑에 필요하다. 매장이 원하면 `--hash-skus`로 SKU도 해시할 수 있지만, 그때는 단가표도 같은 salt로 해시해야 한다.
- 실행 후 출력되는 drop / hash / keep 목록을 매장이 직접 확인한다.
- 받은 파일은 `data/pilot/`(git 제외)에만 둔다. 저장소·채팅에 올리지 않는다.

## 3. 받은 뒤 비교 순서

1. 앱에서 매장 workspace를 만들고 1–4번 파일을 **Data imports**로 올린다. 판매 파일은 미리보기가 파일 안의 첫·마지막 판매일을 제안하고, 사람이 export 기간과 맞는지 확인한다.
2. 단가표의 포장 단위와 상품 매핑을 확인한다.
3. 지난 발주 내역(5번)을 비교한다.

   ```bash
   .venv/bin/python -m clawbot.devtools.compare_orders data/pilot/<store>/past_orders.csv \
       --tenant <workspace id> --location <location id>
   ```

   - 각 발주일 아침(06:00 매장 시각)을 기준으로 계획을 다시 계산한다. 파일에 시각이 있으면 그 시각을 쓴다. 매장의 현재 계획은 바뀌지 않는다.
   - 결과는 `data/pilot/reports/compare-*.md|csv`에 저장된다. 항목별로 다음을 확인한다.
     - **수량 차이**: 실제 발주 vs 추천, 기본 단위 기준.
     - **단위 매핑 오류**: 주문 단위가 supplier item의 주문 단위와 다르거나 포장 수량을 모르는 경우.
     - **매핑 안 된 SKU.**
     - **그날 기준 누락 데이터**: 재고 reading 없음, 판매 이력 14일 미만, 가격 없음.
4. 차이가 큰 품목은 매장과 함께 이유(행사·계절·공간·최소 금액 등)를 기록한다. 이것이 정책 기본값을 바꿀 근거다.

알려진 한계: 외부 미입고 주문은 "각 날짜 당시"가 아니라 현재 알려진 상태로 계산된다.
