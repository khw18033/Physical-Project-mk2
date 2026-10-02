/**
 * src/capability/sample.ts (260920 신설 — 기능 상태 패널 이식)
 *
 * **연결 관리의 「테스트」가 켜졌을 때만 읽는 자료.** 이 파일은 `CapabilityClient` 하나만
 * 열고, 그 클라이언트도 `source.kind === 'sample'` 일 때만 연다
 * (`verify:capability-source` 가 소스에서 확인한다).
 *
 * ## 붙잡아 둔 **실제 응답**이다
 *
 * 2026-09-20 에 `status_ui` 서버(`--control local --port 8765`)를 띄우고 받은 것을 **바이트
 * 그대로** 두었다. 탐지의 시료(`door_example/`)와 같은 성격이다 — 지어낸 목이 아니라 그
 * 서비스가 실제로 내놓은 값이고, 그래서 화면이 「테스트 자료」라고 적되 값은 손대지 않는다.
 *
 *   capability-sample/functions.json   GET /api/functions — 기능 4 · 노드 6
 *   capability-sample/labels.json      GET /api/labels    — ko/en 한 쌍
 *
 * **그래도 실제 클러스터가 아니다.** 그때 그 노트북의 설정(`status_ui.example.json` ·
 * `providers.status_ui.example.json`)으로 계산된 한 장면이고, k3s 에 붙으면 노드도 판정도
 * 다르다. 배지가 끌 수 없게 붙어 있는 이유다.
 *
 * ## `config` 만 손으로 적는다
 *
 * `GET /api/config` 의 응답에는 그 서버를 띄운 **PC 의 절대경로**(`config_path` ·
 * `providers_manifest` · `labels_path`)가 들어 있다. 저장소에 남길 값이 아니라서 화면이
 * 실제로 읽는 `control` 만 옮겨 적었다 — 나머지는 우리가 안 쓴다.
 *
 * ## JSON 을 우리 모양으로 미리 바꿔 두지 않는다
 *
 * 서버 응답 그대로(snake_case)여야 테스트 경로가 `parse.ts` 를 탄다. 미리 바꿔 두면
 * 파서가 깨져도 테스트에서는 멀쩡해 보인다.
 */

import functionsJson from '../../capability-sample/functions.json' with { type: 'json' };
import labelsJson from '../../capability-sample/labels.json' with { type: 'json' };

/**
 * `GET /api/config` 중 화면이 쓰는 만큼. 붙잡은 그 판은 검토용이라 `local` 이었고,
 * 요청과 실제가 같아서 화면의 폴백 줄은 안 뜬다.
 */
export const SAMPLE_CONFIG: Record<string, unknown> = {
  control: { requested: 'local', active: 'local', reason: null, namespace: 'default' },
};

/** `GET /api/labels` — 받은 그대로. */
export const SAMPLE_LABELS = labelsJson as unknown as Record<string, unknown>;

/** `GET /api/functions` — 받은 그대로. 기능·노드가 한 응답에 같이 온다. */
export const SAMPLE_FUNCTIONS = functionsJson as unknown as Record<string, unknown>;
