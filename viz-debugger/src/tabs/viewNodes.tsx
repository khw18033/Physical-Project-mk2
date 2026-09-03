/**
 * src/tabs/viewNodes.tsx (260903 — 노드 캔버스 1단계)
 *
 * **캔버스에 주입되는 뷰 노드 4종.** 이 파일이 `tabs/` 안에 있는 것이 요점이다 —
 * 통합 빌드만 이것을 등록하고(`integrated.tsx` → `registerViewNodes`), 단독 빌드는
 * 등록하지 않아 팔레트 자체가 뜨지 않는다. 캔버스 쪽(`src/canvas/`)은 이 파일을 모른다.
 *
 * 그렇게 하지 않으면 `tabs/data/` 스토어가 단독 번들에 딸려 들어와 **논문 측정축 D(계측
 * 오버헤드)가 오염된다.** `verify:standalone` 이 그 순간 실패한다 — `PlanApproval` 을
 * 프롭으로 주입하는 것과 같은 이유이고 같은 패턴이다.
 *
 * ## 1단계의 본문은 자리표시다
 *
 * 4종의 **요약 카드 규격**(3층 한 줄 + 위험도 등급 / 명령 수 + 4단계 위치 / 스파크라인 /
 * 대표 프레임 + 탐지 수)과 **확대 오버레이**는 2단계다(지시서 §5·§8). 지금은 「누가 줄
 * 데이터인지」를 적는 자리표시만 그린다 — 골격이 먼저 서야 그 위에 얹을 수 있다.
 *
 * **영상 노드의 계약은 지금 적어 둔다**: 캔버스에서는 탭처럼 떠나지 않으므로
 * `VideoOverlayView` 를 그대로 접힌 카드에 넣으면 노드를 셋 놓는 순간 프레임 루프가 셋
 * 돈다(`VZ-I-06`). **접힘 = 정지 프레임 · 확대 = 재생**이다. 2단계가 이 줄을 지켜야 한다.
 */

import { PendingSource } from '../shared/PendingSource.tsx';
import type { ViewNodeEntry } from '../canvas/types.ts';

/**
 * 팔레트 네 칸. **팔레트는 이 목록을 훑기만 한다** — 종류를 늘릴 때 팔레트 코드를 고치지
 * 않는다는 것이 `VZ-N-01` 의 뒷문장이다.
 */
export const VIEW_NODE_RENDERERS: readonly ViewNodeEntry[] = [
  {
    kind: 'device-risk',
    label: '장치 · 위험',
    hint: 'VZ-U-01 · VZ-I-03 · VZ-I-08 · VZ-U-03 — 연결/배터리/자기보고 3층과 위험도 등급',
    summary: () => <PendingSource id="device-cards" inline />,
  },
  {
    kind: 'control',
    label: '제어',
    hint: 'VZ-O-01 · 02 · 05 — 이 태스크가 낸 명령 수와 마지막 명령의 4단계 위치',
    summary: () => <PendingSource id="command-result" inline />,
  },
  {
    kind: 'metrics',
    label: '지표',
    hint: 'VZ-I-04 · VZ-C-03 — 이 구간의 지표 요약(2단계에 스파크라인)',
    summary: () => <PendingSource id="metrics-query" inline />,
  },
  {
    kind: 'video',
    label: '영상',
    hint: 'VZ-I-06 · 07 · 09 — 대표 프레임과 탐지 수 (접힘은 정지 프레임)',
    summary: () => <PendingSource id="video-stream" inline />,
  },
];
