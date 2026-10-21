# 보안: 노출된 credential 정리와 교체 절차 (CP1.13)

작성 2026-10-21 · 저장소 `jihwan-victor-park/Tabula`는 **공개(PUBLIC)** 저장소이므로, 아래 항목은 이미 외부에 노출된 것으로 간주한다. 이 문서에는 비밀값을 적지 않는다.

## 1. 무엇이 노출됐나

초기 커밋 `d6335bf`(2026-04-29)부터 추적되던 파일을 조사했다. 조사 방법은 키 이름·형태·길이와 알려진 credential 패턴이다. 값은 출력하지 않았다.

| # | 항목 | 파일 | 무엇에 쓰이나 | 영향 | 조치 |
|---|---|---|---|---|---|
| 1 | OpenClaw **gateway 인증 토큰** | `.openclaw/openclaw.json`, `openclaw.json.bak`, `openclaw.json.bak.1` (같은 값 3곳) | 로컬 OpenClaw gateway(포트 18789)에 접속하는 클라이언트 인증 | gateway는 `bind: loopback`, tailscale off라서 **그 Mac 안의 프로세스만** 접속할 수 있다. 그 Mac에 로컬 접근하거나, 나중에 bind를 LAN/tailscale로 바꾸면 이 토큰으로 agent를 조종할 수 있다(iMessage 발송, tool 실행). | **폐기·재발급 필요** |
| 2 | OpenClaw **기기 identity 개인키**(Ed25519 PEM) | `.openclaw/identity/device.json` | 이 기기를 gateway에 페어링된 operator 기기로 식별 | 이 기기로 위장할 수 있다. | **재생성 + 재페어링 필요** |
| 3 | OpenClaw **operator 토큰** | `.openclaw/identity/device-auth.json`, `.openclaw/devices/paired.json` (같은 값) | 페어링된 operator 기기의 접근 토큰 | #2와 같다. | **폐기 필요** |
| 4 | 대화 기록·로그·메모리 DB | `.openclaw/agents/main/sessions/*.jsonl`, `.openclaw/logs/*.log`, `.openclaw/memory/main.sqlite` | agent 세션 기록 | 개인정보·업무 정보. API 키 패턴은 발견되지 않았다. | 추적 해제(삭제 불가 — 이력에 남음) |
| 5 | 개인 전화번호(끝자리 …9272) | `start.sh`, `demo.sh`, `whatsapp_bridge/server.js`, `.openclaw/*.json`, 세션 기록 | iMessage 수신자 기본값 | 개인정보(PII). 교체할 수 있는 credential은 아니다. | 코드에서 제거하고 환경변수로 대체 |

노출되지 않은 것(확인함):

- **Anthropic API 키**: `.openclaw/agents/main/agent/auth-profiles.json`은 처음부터 `.gitignore` 대상이었고, Git 이력에 한 번도 들어간 적이 없다. `.env`도 이력에 없다.
- 저장소 안의 Tabula 코드는 위 OpenClaw 토큰을 참조하지 않는다. 그래서 교체해도 **Tabula API·worker에는 영향이 없다**. 영향을 받는 것은 OpenClaw gateway와 거기에 페어링된 클라이언트뿐이다.
- AWS·GitHub·Twilio·Stripe·Square·Google 키 패턴은 발견되지 않았다.

## 2. 저장소에서 이미 한 조치 (이 브랜치)

- 위 런타임 파일을 `git rm --cached`로 **추적만 해제**했다. 로컬 파일은 그대로 둔다(gateway가 계속 쓴다).
- `.gitignore`에 런타임 상태, `.env.*`, `*.pem`/`*.key`, 전화번호 이름의 onboarding 파일을 추가했다.
- `.openclaw/openclaw.example.json`: 비밀값을 지운 설정 예시. 실제 설정은 각 기기의 `~/.openclaw/openclaw.json`이 기준이다(AGENTS.md와 같다).
- 전화번호를 환경변수로 옮겼다:
  - `start.sh` → `TABULA_DEFAULT_RECIPIENT`
  - `demo.sh` → `TABULA_DEMO_RECIPIENT`
  - JS 주석 → 555 예시 번호
- 재커밋 방지:
  - `scripts/secret_scan.py`: 패턴과 금지 경로를 검사하고, 값은 출력하지 않는다.
  - `.githooks/pre-commit`: 클론마다 `git config core.hooksPath .githooks`를 한 번 실행해야 켜진다.
  - `tests/test_secret_hygiene.py`: 테스트에서 매번 전체를 검사한다.

**한계:** 파일 추적을 해제해도 **이전 커밋에는 값이 그대로 남아 있다**. 공개 저장소이므로 교체가 유일한 해결책이다. 이력 재작성은 아래 4절을 참고한다.

## 3. 직접 해야 하는 교체 절차 (순서대로)

gateway가 돌던 기기는 설정 경로로 보아 사용자 `mmm`의 Mac이다. 아래 작업은 **그 Mac에서** 한다. 이 개발 기기에는 `openclaw` CLI가 설치돼 있지 않아서, CLI 명령 이름은 확인하지 못했다. 정확한 명령은 OpenClaw 문서에서 확인한다. 아래는 설정 파일 기준의 절차다.

**영향과 순서:** gateway를 다시 시작하는 동안(수 분) iMessage agent가 응답하지 않는다. Tabula API는 영향이 없다. 사용이 적은 시간에 하고, 3-1 → 3-2 → 3-3 순서를 지킨다. 새 토큰을 먼저 만들고, 클라이언트를 바꾼 뒤, 옛 값이 남지 않았는지 확인하는 순서다.

### 3-1. gateway 토큰 교체 (#1)

1. gateway를 멈춘다. OpenClaw 앱/서비스 종료, 또는 문서에 나온 stop 명령을 쓴다.
2. 새 무작위 토큰을 만든다. 터미널에서 `openssl rand -hex 24`를 실행한다. 결과는 어디에도 붙여넣지 않는다.
3. `~/.openclaw/openclaw.json`의 `gateway.auth.token` 값을 새 토큰으로 바꾼다. 같은 폴더의 `openclaw.json.bak`, `openclaw.json.bak.1`은 옛 토큰을 담고 있으니 **삭제한다**(`trash` 권장).
4. 이 gateway에 접속하는 다른 클라이언트(같은 Mac의 OpenClaw CLI/앱 등)에 저장된 토큰도 새 값으로 바꾼다.
5. gateway를 다시 시작하고, 옛 토큰으로 접속이 거부되는지 확인한다.

### 3-2. 기기 identity와 operator 토큰 재발급 (#2, #3)

1. gateway를 멈춘 상태에서 `~/.openclaw/identity/device.json`과 `~/.openclaw/identity/device-auth.json`을 백업 폴더로 옮긴다(삭제하지 말고 이동).
2. `~/.openclaw/devices/paired.json`에서 옛 기기 항목을 제거한다. 문서에 페어링 해제(unpair/revoke) 명령이 있으면 그것을 쓴다.
3. OpenClaw를 시작해 **새 identity가 생성되는지** 확인하고, 다시 페어링한다. OpenClaw가 identity를 자동으로 다시 만들지 않으면, 문서의 "reset device identity" 절차를 따른다.
4. 정상 동작을 확인한 뒤 1번에서 옮긴 옛 파일을 완전히 삭제한다.

### 3-3. 확인

- 새 `~/.openclaw/openclaw.json`과 identity 파일이 **저장소 폴더 안에 있지 않은지** 확인한다. 저장소의 `.openclaw/`는 이제 Git이 무시하지만, 실제 설정은 홈 디렉터리에 두는 것이 원칙이다.
- 저장소에서 `python3 scripts/secret_scan.py --all` 결과가 깨끗한지 확인한다.

## 4. Git 이력 재작성 (별도 확인 필요 — 아직 하지 않음)

교체를 마치면 옛 값은 쓸모없어지므로, 이력 재작성은 **필수가 아니라 선택**이다. 개인 전화번호와 대화 기록을 공개 이력에서 지우고 싶다면 아래를 할 수 있다. 다만 다음 위험이 있다:

- `git filter-repo`로 `.openclaw/` 런타임 파일과 전화번호를 모든 커밋에서 제거한 뒤 **force push**해야 한다. 모든 커밋 해시가 바뀐다.
- 다른 사람이 가진 클론·fork, GitHub 캐시, 검색엔진 캐시에는 남을 수 있다. 완전히 지우려면 GitHub Support에 cached view 삭제를 요청해야 한다.
- 진행 중인 브랜치(`cp1-foundation`)를 rebase해야 한다.

명시적으로 요청하기 전에는 이 작업을 하지 않는다.
