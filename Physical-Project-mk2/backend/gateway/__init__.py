"""gateway — WS 게이트웨이(Kafka 소비자이면서 WebSocket 서버).

브라우저는 Kafka·MQTT에 직접 붙지 않고 이 게이트웨이만 통한다(아키텍처 §7-1). Phase 1은
그 얇은 선행인 **echo**까지다 — 구독 관리·인증·재접속 캐시·명령 번역은 Phase 5/7.

implements: BE-T-03
"""
