# 백엔드 정본 스키마 사본 (vendored)

`server/` 아래 네 파일은 **우리가 만든 것이 아니다.** 백엔드가 소유한 공통 데이터
계약의 사본이고, 우리 메시지가 그 계약을 지키는지 이 저장소 단독으로 검증하기 위한
것이다(`tests/test_server_contract_conformance.py`).

| 파일 | 출처 |
|---|---|
| `server/message.schema.json` | `server/contracts/common/message.schema.json` |
| `server/detections.schema.json` | `server/contracts/common/detections.schema.json` |
| `server/frame-reference.schema.json` | `server/contracts/common/frame-reference.schema.json` |
| `server/object-reference.schema.json` | `server/contracts/common/object-reference.schema.json` |

출처 저장소: `github.com/choBottle/Physical-Project-mk2` · `main` @ `a6942082a`
(2026-11-02 기준). GOVERNANCE.md 가 "The backend owns the canonical data contracts in
`server/contracts/common/`. Other parts follow them" 이라고 정했으므로 **내용을
고치지 않는다.** 바꿔야 하면 그쪽에 RFC 를 연다.

통합하면 이 디렉터리는 지우고 `server/contracts/common/` 을 직접 참조한다 — 통합
저장소의 `scripts/check_contracts.py` 가 이미 그 방식으로 우리 예제를 검사한다.
