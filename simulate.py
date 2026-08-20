#!/usr/bin/env python3
"""취소표 발생 시나리오 시뮬레이션.

인터파크 API 조회만 가짜 데이터로 바꾸고, 감지 로직과 텔레그램 발송은
monitor.py의 실제 코드를 그대로 사용한다. 실제 알림이 어떻게 오는지
미리 확인하는 용도.

시나리오 (2초 간격):
  1주기: 전 회차 매진 (0석)
  2주기: 1회차(2PM)에 취소표 2석 발생  → 🎫 알림
  3주기: 1회차 3석으로 증가, 2회차(7PM)도 1석 발생 → 🎫 알림
  4주기: 다시 전부 매진 (알림 없음, 로그만)

실행:
  TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python3 simulate.py
"""

import os

# monitor는 import 시점에 환경변수를 읽으므로 먼저 설정한다
os.environ["GOODS_NAME"] = "[테스트] 2026 HYUNJAE 1st FANMEETING"
os.environ["POLL_INTERVAL"] = "2"
os.environ["MAX_RUNTIME_MIN"] = "0.2"  # 4주기 돌고 종료 (~12초)
os.environ["STARTUP_NOTIFY"] = "0"

import monitor  # noqa: E402

SCENARIO = {
    # cycle: {playSeq: remainCnt}
    0: {"001": 0, "002": 0},
    1: {"001": 2, "002": 0},
    2: {"001": 3, "002": 1},
    3: {"001": 0, "002": 0},
}

_calls = {"n": 0}


def fake_fetch(play_seq: str):
    cycle = min(_calls["n"] // len(monitor.PLAY_SEQS), max(SCENARIO))
    _calls["n"] += 1
    cnt = SCENARIO[cycle].get(play_seq, 0)
    monitor.log(f"  (시뮬레이션 {cycle + 1}주기, 회차 {play_seq} -> {cnt}석)")
    return [
        {"playSeq": play_seq, "seatGrade": "1", "seatGradeName": "전석", "remainCnt": cnt}
    ]


monitor.fetch_remain = fake_fetch

if __name__ == "__main__":
    print("=== 취소표 시나리오 시뮬레이션 시작 (텔레그램 알림 3건 발송 예정) ===")
    raise SystemExit(monitor.main())
