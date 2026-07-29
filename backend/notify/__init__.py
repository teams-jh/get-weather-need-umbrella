"""알림 발송.

scheduler       발송 대상 판정과 파이프라인. weather_all.json 을 읽어 거점별
                날씨를 사용자 설정과 맞춰 본다.
toss            토스 스마트 메시지 전송. ENABLE_REAL_TOSS_PUSH 가 꺼져 있으면
                모의 발송으로 떨어진다.
manual_message  캠페인 템플릿 확인용 단건 발송. 워크플로에서 수동 실행한다.
"""
