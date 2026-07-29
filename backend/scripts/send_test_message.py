"""
토스 스마트 메시지 단건 발송. 캠페인 템플릿 확인용으로 수동 실행한다.

    cd backend && python -m scripts.send_test_message

수신자와 템플릿 변수는 워크플로 입력에서 환경변수로 넘어온다.
"""
import io
import json
import sys

from notify.manual_message import send_test_message
from paths import load_env_file


def main() -> None:
    if hasattr(sys.stdout, "detach"):
        sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding="utf-8")

    load_env_file()
    print(json.dumps(send_test_message(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
