"""storage — 성격별 저장 경계.

Phase 1은 목적 인터페이스(`TelemetryWriter.write`)와 placeholder 구현까지다. Phase 2에서
이 함수 몸통만 TSDB로 교체하고 ingest·인터페이스는 건드리지 않는다.

implements: BE-S-01
"""
