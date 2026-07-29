"""
알림 발송 파이프라인을 실행한다. 매시간 도는 알림 워크플로의 진입점.

    cd backend && python -m scripts.run_notifications

ENABLE_REAL_TOSS_PUSH 가 켜져 있지 않으면 모의 발송으로 떨어진다.
"""
import io
import sys

from notify.scheduler import run_notification_pipeline
from paths import load_env_file


def main() -> None:
    # 워크플로 로그에서 한글이 깨지지 않게 stdout 을 UTF-8 로 다시 연다.
    if hasattr(sys.stdout, "detach"):
        sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding="utf-8")

    load_env_file()
    run_notification_pipeline()


if __name__ == "__main__":
    main()
