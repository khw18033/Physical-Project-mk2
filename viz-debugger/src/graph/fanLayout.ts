/**
 * src/graph/fanLayout.ts (260909 신설 — 시연 대본 §4)
 *
 * **8분할 뷰포인트의 원형 배치.** 깊이 배치(`layout.ts`)의 결과를 **덮는 한 겹**이고,
 * 배치 엔진 자체는 한 줄도 고치지 않는다 (지시서 §4 「레이아웃 엔진 전체를 고치지 마라」).
 *
 * ## 왜 특례가 필요한가
 *
 * `dagLayout` 은 깊이로 열을 만든다. `T-A4-0`~`T-A4-7` 여덟은 **전부 `T-A3` 하나에**
 * 매달리므로 깊이가 같고, 그래서 한 열에 세로로 여덟이 쌓인다 — `ROW`(150) × 8 = 1,200px
 * 기둥이다. 순서도의 부채꼴은 그 모양이 아니고, 첫 화면에도 안 들어온다.
 *
 * 그래서 이 여덟만 부모 아래의 **원 둘레**로 옮긴다. 0도가 위, 시계 방향으로 45도씩
 * (§4). 나머지 노드는 손대지 않는다 — 들어온 좌표를 그대로 돌려준다.
 *
 * ## 특례의 경계
 *
 * **어디까지가 특례인가**: 이 파일과, `TaskGraph` 가 이 함수를 한 번 부르는 자리.
 * **어디부터가 기존 코드인가**: `dagLayout` 이 낸 좌표 전부. 이 함수는 선언된 여덟 개의
 * 키만 덮어쓰고 나머지 키는 입력 객체에서 그대로 옮긴다.
 *
 * 특례가 **선언으로만 걸린다**는 것이 요점이다 — 대본이 `viewpoints` 를 적지 않으면
 * 이 함수는 입력을 그대로 돌려주고, 다른 네 편의 배치는 한 픽셀도 달라지지 않는다.
 * 태스크 id 를 코드에 적어 두는 방식이 아니다.
 */

import { NODE_HEIGHT, NODE_WIDTH, type Position } from './layout.ts';

/**
 * 대본이 선언하는 8분할 묶음 (`scenarios/<id>.json` 의 `viewpoints`).
 * 배치가 이 선언 하나만 보고 원을 그린다.
 */
export type ViewpointGroup = {
  /** 여덟이 매달린 부모. 원의 중심이 이 노드 아래에 선다. */
  parentTaskId: string;
  /** 원 둘레에 놓을 태스크. 배열 차례가 곧 각도 차례다. */
  taskIds: readonly string[];
  /** 첫 노드의 각도. 0이면 위쪽이다. */
  startAngleDeg?: number;
  /** 노드 사이 각도. 여덟이면 45도. */
  stepDeg?: number;
};

/**
 * 원의 반지름. 노드 상자(180×110)가 이웃과 안 겹칠 만큼은 돼야 한다 — 여덟이 45도씩이면
 * 이웃 사이 거리가 `2r·sin(22.5°) ≈ 0.765r` 이므로, 가로로 가장 빡빡한 자리에서
 * `0.765r > NODE_WIDTH + 여유` 를 만족해야 한다. 260 이면 약 199px 로 상자 폭을 넘는다.
 * `verify:layout` 이 이 값으로 실제 겹침을 다시 잰다 — 손으로 맞춘 값을 믿지 않는다.
 */
const RADIUS = 260;

/**
 * 부모 노드 아래로 원의 중심을 얼마나 내리는가.
 *
 * 0도 노드는 중심 **바로 위**라 부모와 가로가 같다 — 세로로만 벌어져야 안 겹친다.
 * 부모 아래끝(`NODE_HEIGHT`)과 0도 노드 위끝(`CENTER_DROP - RADIUS - NODE_HEIGHT/2`)
 * 사이가 벌어지려면 `CENTER_DROP >= RADIUS + NODE_HEIGHT × 1.5` 이고, 여기에 통로 40을 준다.
 * 처음에 `NODE_HEIGHT + RADIUS + 40` 으로 잡았다가 `verify:layout` 이 겹침을 잡아 고쳤다 —
 * 손으로 맞춘 값을 믿지 않는다는 것이 그 검사의 쓸모다.
 */
const CENTER_DROP = RADIUS + NODE_HEIGHT * 1.5 + 40;

/**
 * 원형 배치를 **덮어씌운다.** 선언이 없거나 묶음의 태스크가 지금 화면에 없으면
 * 입력을 그대로 돌려준다 — 「이 마일스톤」 범위에서 여덟이 안 보일 때가 그렇다.
 *
 * 부모가 화면에 없으면 원의 중심을 잡을 수 없으므로 역시 그대로 둔다. 그때는 여덟이
 * 깊이 0 한 열에 서고, 그것이 원래 배치의 정답이다.
 */
export function applyFanLayout(
  base: Record<string, Position>,
  group: ViewpointGroup | null | undefined,
): Record<string, Position> {
  if (!group) return base;
  const parent = base[group.parentTaskId];
  if (parent === undefined) return base;
  const members = group.taskIds.filter((id) => base[id] !== undefined);
  if (members.length !== group.taskIds.length || members.length === 0) return base;

  const step = group.stepDeg ?? 360 / members.length;
  const start = group.startAngleDeg ?? 0;
  // 원의 중심은 부모 노드의 **가로 한가운데** 아래다. 노드 좌표는 상자의 왼쪽 위 모서리라
  // 반 폭·반 높이를 빼서 다시 모서리로 돌려놓는다.
  const cx = parent.x + NODE_WIDTH / 2;
  const cy = parent.y + CENTER_DROP;

  const moved: Record<string, Position> = { ...base };
  members.forEach((id, index) => {
    // 0도가 위, 시계 방향 (§4). 화면 y 는 아래로 자라므로 위가 -sin 이 아니라 -cos 다.
    const rad = ((start + index * step) * Math.PI) / 180;
    moved[id] = {
      x: Math.round(cx + RADIUS * Math.sin(rad) - NODE_WIDTH / 2),
      y: Math.round(cy - RADIUS * Math.cos(rad) - NODE_HEIGHT / 2),
    };
  });
  return moved;
}
