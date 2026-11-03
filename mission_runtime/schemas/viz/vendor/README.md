# 가시화 파트 스키마 사본 (vendored)

여기 있는 세 파일은 **우리가 만든 것이 아니다.** 가시화 파트의 계약을 그대로 복사해
두었고, 우리 디스크립터가 그 계약을 지키는지 이 저장소 단독으로 검증하기 위한
것이다(`tests/test_viz_descriptors.py`).

| 파일 | 출처 |
|---|---|
| `component-descriptor.schema.json` | `visualization/contracts/component-descriptor.schema.json` |
| `datasource.schema.json` | `visualization/contracts/datasource.schema.json` |
| `renderer.schema.json` | `visualization/contracts/renderer.schema.json` |

출처 저장소: `github.com/choBottle/Physical-Project-mk2` · `main` @ `a6942082a`
(2026-11-02 기준). 내용을 **고치지 않는다** — 고쳐야 할 이유가 생기면 그쪽 계약을
RFC 로 바꾸는 것이 순서다(GOVERNANCE.md 「Across parts」).

통합하면 이 디렉터리는 지우고 `visualization/contracts/` 를 직접 참조한다.
