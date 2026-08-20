# interpark-cancel-alert

인터파크(NOL 티켓) 공연의 **취소표(잔여좌석)를 10초 간격으로 감시**하다가, 좌석이 풀리는 순간 **텔레그램으로 알림**을 보내는 모니터입니다. GitHub Actions 위에서 24시간 무료로 돌아갑니다.

기본 설정은 **2026 HYUNJAE 1st FANMEETING [The Present for you]** (2026-09-12, 코엑스아티움 우리은행홀, 1회차 2PM / 2회차 7PM)를 감시하도록 되어 있으며, 환경변수만 바꾸면 다른 공연에도 쓸 수 있습니다.

> ⚠️ 이 도구는 **알림만** 보냅니다. 예매(결제)는 알림을 받고 본인이 직접 해야 합니다. 자동 예매(매크로 부정 예매)는 공연법상 불법이며 이 저장소는 이를 지원하지 않습니다.

## 동작 원리

- 인터파크 프론트 API `GET /v1/goods/{goodsCode}/playSeq/PlaySeq/{playSeq}/REMAINSEAT` 를 폴링 (로그인 불필요)
- 잔여석이 `0 → N`으로 바뀌거나 좌석 수가 늘어나면 텔레그램 발송
- GitHub Actions 잡은 최대 6시간이므로, 5시간마다 크론 + 자체 재실행(self re-dispatch)으로 잡을 갈아끼우며 상시 구동

## 설정 방법

### 1. 텔레그램 봇 만들기

1. 텔레그램에서 [@BotFather](https://t.me/BotFather) 에게 `/newbot` → 봇 이름 설정 → **봇 토큰** 을 받습니다 (`123456:ABC-...` 형태).
2. 방금 만든 봇에게 아무 메시지나 하나 보냅니다 (봇은 먼저 말을 걸 수 없음).
3. 브라우저에서 `https://api.telegram.org/bot<봇토큰>/getUpdates` 를 열면 `"chat":{"id": 123456789, ...}` 가 보입니다. 이 숫자가 **chat ID** 입니다.

### 2. 저장소 Secrets 등록

GitHub 저장소 → Settings → Secrets and variables → Actions → New repository secret:

| 이름 | 값 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather가 준 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 위에서 확인한 chat ID |

또는 CLI로: `gh secret set TELEGRAM_BOT_TOKEN` / `gh secret set TELEGRAM_CHAT_ID`

### 3. 시작

Actions 탭 → **ticket-monitor** → **Run workflow** 를 한 번 눌러주면 이후로는 스스로 이어달리기를 합니다.

멈추고 싶으면: Actions 탭에서 실행 중인 런을 Cancel 하고, 저장소 Settings → Actions에서 워크플로우를 Disable 하면 됩니다.

## 다른 공연 감시하기

`.github/workflows/monitor.yml` 의 `env` 에 아래 변수를 추가/수정하세요. 공연 코드는 공연 페이지 URL(`tickets.interpark.com/goods/26011954`)의 숫자입니다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `GOODS_CODE` | `26011954` | 공연 코드 |
| `GOODS_NAME` | HYUNJAE 팬미팅 | 알림에 표시할 이름 |
| `PLAY_SEQS` | `001,002` | 감시할 회차 (콤마 구분) |
| `PLAY_SEQ_LABELS` | 9/12 2PM/7PM | 회차 라벨 JSON |
| `POLL_INTERVAL` | `10` | 평상시 폴링 주기(초). Actions에서는 30초 사용 |
| `BACKOFF_AFTER` | `3` | 연속 실패 N회면 백오프 모드 진입 |
| `BACKOFF_INTERVAL` | `300` | 백오프 모드 폴링 주기(초). 성공하면 즉시 평상시로 복귀 |
| `FAILURE_ALERT_AFTER` | `10` | 연속 실패 N회에 경고 알림 1회 |
| `HEARTBEAT_HOURS` | `0` | N시간마다 생존신고 메시지 (0=끔) |
| `STARTUP_NOTIFY` | `1` | 시작 시 첫 조회 결과 발송 — 잡이 ~5시간마다 교체되므로 이것이 생존신고 역할 (0=끔) |

## 로컬에서 돌리기 (선택)

GitHub Actions 대신 항상 켜져 있는 맥/서버에서 돌려도 됩니다:

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
python3 monitor.py
# 백그라운드: nohup python3 monitor.py >> monitor.log 2>&1 &
```

## 알아둘 점 / 한계

- **크론 지연**: GitHub Actions 스케줄은 몇 분씩 지연될 수 있습니다. self re-dispatch가 백업으로 들어가 있어 실질 공백은 잡 교체 시 수십 초 수준입니다.
- **저장소 비활성 60일**: 공개 저장소에서 60일간 커밋 등 활동이 없으면 GitHub가 스케줄 워크플로우를 자동 비활성화합니다. 알림 메일이 오면 다시 활성화해 주세요.
- **잡 교체 시 중복 알림**: 잡이 교체될 때 상태가 초기화되므로, 그 시점에 좌석이 열려 있으면 알림이 한 번 더 올 수 있습니다 (놓치는 것보다 낫다는 설계).
- **차단 가능성**: 10초 간격은 하루 약 17,000회 요청입니다. 인터파크가 GitHub(Azure) IP를 차단하면 조회 실패 경고 알림이 옵니다. 그 경우 `POLL_INTERVAL`을 늘리거나 로컬 실행으로 전환하세요.
- **이용약관**: 자동화된 조회는 인터파크 이용약관에 저촉될 수 있습니다. 개인적인 알림 용도로만, 본인 책임하에 사용하세요.

## License

MIT
