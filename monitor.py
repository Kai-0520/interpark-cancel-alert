#!/usr/bin/env python3
"""Interpark(NOL 티켓) 취소표 모니터 → Telegram 알림.

지정한 공연(goodsCode)의 회차별 잔여좌석을 주기적으로 조회해서,
잔여석이 0 → N으로 바뀌는 순간 텔레그램으로 알림을 보낸다.

의존성 없음 (Python 3.9+ 표준 라이브러리만 사용).

환경변수:
  TELEGRAM_BOT_TOKEN  (필수) BotFather에서 발급받은 봇 토큰
  TELEGRAM_CHAT_ID    (필수) 알림 받을 채팅 ID
  GOODS_CODE          공연 코드 (기본: 26011954)
  GOODS_NAME          알림에 표시할 공연 이름
  PLAY_SEQS           감시할 회차, 콤마 구분 (기본: "001,002")
  PLAY_SEQ_LABELS     회차 라벨 JSON (기본: {"001": "9/12(토) 2PM", ...})
  POLL_INTERVAL       평상시 폴링 주기(초, 기본 10)
  BACKOFF_AFTER       이 횟수만큼 연속 실패하면 백오프 모드 진입 (기본 3)
  BACKOFF_INTERVAL    백오프 모드의 폴링 주기(초, 기본 300) — 차단이 풀릴 시간을 벌어줌
  FAILURE_ALERT_AFTER 이 횟수 연속 실패 시 경고 알림 1회 발송. 0 = 끔 (기본 10)
  MAX_RUNTIME_MIN     이 시간(분)이 지나면 정상 종료. 0 = 무한 (기본 0)
  HEARTBEAT_HOURS     N시간마다 생존 신고 메시지. 0 = 끔 (기본 0)
  STARTUP_NOTIFY      시작 시 첫 조회 결과를 텔레그램으로 발송. 1=켬 (기본 1)
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

GOODS_CODE = os.environ.get("GOODS_CODE", "26011954")
GOODS_NAME = os.environ.get(
    "GOODS_NAME", "2026 HYUNJAE 1st FANMEETING [The Present for you]"
)
PLAY_SEQS = [s.strip() for s in os.environ.get("PLAY_SEQS", "001,002").split(",") if s.strip()]
PLAY_SEQ_LABELS = json.loads(
    os.environ.get("PLAY_SEQ_LABELS", '{"001": "9/12(토) 2PM", "002": "9/12(토) 7PM"}')
)
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "10"))
BACKOFF_AFTER = int(os.environ.get("BACKOFF_AFTER", "3"))
BACKOFF_INTERVAL = float(os.environ.get("BACKOFF_INTERVAL", "300"))
MAX_RUNTIME_MIN = float(os.environ.get("MAX_RUNTIME_MIN", "0"))
HEARTBEAT_HOURS = float(os.environ.get("HEARTBEAT_HOURS", "0"))
STARTUP_NOTIFY = os.environ.get("STARTUP_NOTIFY", "1") == "1"

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

API_URL = "https://api-ticketfront.interpark.com/v1/goods/{goods}/playSeq/PlaySeq/{seq}/REMAINSEAT"
BOOKING_URL = f"https://tickets.interpark.com/goods/{GOODS_CODE}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": BOOKING_URL,
}

# 연속 조회 실패가 이 횟수에 도달하면 한 번만 경고 알림을 보낸다 (0이면 경고/복구 알림 끔)
FAILURE_ALERT_THRESHOLD = int(os.environ.get("FAILURE_ALERT_AFTER", "10"))


def log(msg: str) -> None:
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    print(f"[{now}] {msg}", flush=True)


def send_telegram(text: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode(
        {"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    try:
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=15) as resp:
            ok = json.loads(resp.read()).get("ok", False)
            if not ok:
                log("텔레그램 응답이 ok=false")
            return ok
    except Exception as e:  # noqa: BLE001 - 알림 실패로 모니터가 죽으면 안 됨
        log(f"텔레그램 전송 실패: {e}")
        return False


def fetch_remain(play_seq: str):
    """회차별 잔여좌석 리스트를 반환. [{seatGradeName, remainCnt, ...}, ...]"""
    url = API_URL.format(goods=GOODS_CODE, seq=play_seq)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    return (data.get("data") or {}).get("remainSeat") or []


def seat_label(play_seq: str) -> str:
    return PLAY_SEQ_LABELS.get(play_seq, f"회차 {play_seq}")


def main() -> int:
    if not BOT_TOKEN or not CHAT_ID:
        log("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 필요합니다.")
        return 1

    deadline = (
        time.monotonic() + MAX_RUNTIME_MIN * 60 if MAX_RUNTIME_MIN > 0 else None
    )
    next_heartbeat = (
        time.monotonic() + HEARTBEAT_HOURS * 3600 if HEARTBEAT_HOURS > 0 else None
    )

    # 회차별 마지막 상태: {playSeq: {seatGradeName: remainCnt}}
    last_state: dict[str, dict[str, int]] = {}
    consecutive_failures = 0
    failure_alerted = False

    log(
        f"모니터 시작: {GOODS_NAME} (goods={GOODS_CODE}, 회차={PLAY_SEQS}, "
        f"주기={POLL_INTERVAL:.0f}초)"
    )

    # 시작 알림: 첫 조회 결과를 함께 보내서, 이 실행 환경에서 인터파크 조회와
    # 텔레그램 발송이 모두 정상인지 즉시 확인할 수 있게 한다.
    if STARTUP_NOTIFY:
        parts = []
        for seq in PLAY_SEQS:
            try:
                remain = fetch_remain(seq)
                total = sum(int(r.get("remainCnt") or 0) for r in remain)
                parts.append(f"  · {seat_label(seq)}: {total}석")
            except Exception as e:  # noqa: BLE001
                parts.append(f"  · {seat_label(seq)}: 조회 실패 ({e})")
        send_telegram(
            f"🚀 모니터 시작 — {GOODS_NAME}\n"
            + "\n".join(parts)
            + f"\n({POLL_INTERVAL:.0f}초 간격 감시 중)"
        )

    while True:
        if deadline and time.monotonic() >= deadline:
            log(f"MAX_RUNTIME_MIN({MAX_RUNTIME_MIN:.0f}분) 도달, 정상 종료")
            return 0

        cycle_failed = False
        for seq in PLAY_SEQS:
            try:
                remain = fetch_remain(seq)
            except Exception as e:  # noqa: BLE001
                cycle_failed = True
                log(f"[{seq}] 조회 실패: {e}")
                continue

            current = {
                r.get("seatGradeName", f"등급{r.get('seatGrade')}"): int(r.get("remainCnt") or 0)
                for r in remain
            }
            previous = last_state.get(seq)

            newly_available = [
                (grade, cnt)
                for grade, cnt in current.items()
                if cnt > 0 and (previous is None or previous.get(grade, 0) == 0)
            ]
            increased = [
                (grade, cnt)
                for grade, cnt in current.items()
                if previous is not None and 0 < previous.get(grade, 0) < cnt
            ]

            if newly_available or increased:
                lines = [f"🎫 취소표 발생! {GOODS_NAME}", f"📅 {seat_label(seq)}"]
                for grade, cnt in newly_available + increased:
                    lines.append(f"  · {grade}: {cnt}석")
                lines.append(f"👉 {BOOKING_URL}")
                msg = "\n".join(lines)
                log(f"[{seq}] 알림 발송: {current}")
                send_telegram(msg)
            elif previous != current:
                log(f"[{seq}] 상태 변경(가용석 없음): {previous} -> {current}")

            last_state[seq] = current

        if cycle_failed:
            consecutive_failures += 1
            if consecutive_failures == BACKOFF_AFTER:
                log(
                    f"연속 {consecutive_failures}회 실패 → 백오프 모드 진입 "
                    f"({BACKOFF_INTERVAL:.0f}초 간격으로 찔러보기)"
                )
            if (
                FAILURE_ALERT_THRESHOLD > 0
                and consecutive_failures >= FAILURE_ALERT_THRESHOLD
                and not failure_alerted
            ):
                failure_alerted = True
                send_telegram(
                    f"⚠️ 모니터 경고: 잔여석 조회가 {consecutive_failures}회 연속 실패 중입니다. "
                    f"(차단 또는 API 변경 가능성) {BACKOFF_INTERVAL:.0f}초 간격으로 재시도하며 "
                    f"복구되면 자동으로 빠른 감시로 돌아갑니다. — {GOODS_NAME}"
                )
        else:
            if consecutive_failures >= BACKOFF_AFTER:
                log(f"조회 성공 → 평상시 간격({POLL_INTERVAL:.0f}초)으로 복귀")
            if failure_alerted:
                send_telegram(
                    f"✅ 모니터 복구: 잔여석 조회가 다시 정상입니다. "
                    f"{POLL_INTERVAL:.0f}초 간격 감시 재개. — {GOODS_NAME}"
                )
            consecutive_failures = 0
            failure_alerted = False

        if next_heartbeat and time.monotonic() >= next_heartbeat:
            next_heartbeat = time.monotonic() + HEARTBEAT_HOURS * 3600
            state_txt = ", ".join(
                f"{seat_label(s)}: {sum(last_state.get(s, {}).values())}석"
                for s in PLAY_SEQS
            )
            send_telegram(f"💓 모니터 정상 작동 중 — {GOODS_NAME}\n{state_txt}")

        # 실패가 이어지면 간격을 넓혀 방화벽 차단이 풀릴 시간을 벌고,
        # 성공하면 즉시 평상시 간격으로 복귀한다
        if consecutive_failures >= BACKOFF_AFTER:
            time.sleep(BACKOFF_INTERVAL)
        else:
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("중단됨")
        sys.exit(0)
