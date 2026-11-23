"""ingest — 말단 MQTT 수신 경계.

수신 즉시 공통 봉투를 strict 검증하고, 합격만 업무 백본(Kafka)으로 넘긴다. 불합격은 정상
토픽으로 재발행하지 않고 격리한다(fail-closed).

implements: BE-C-01, BE-T-01, BE-T-02
"""
