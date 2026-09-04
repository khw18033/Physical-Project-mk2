import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { ViewNodeCard } from '../canvas/ViewNodeCard.tsx';
import type { ViewNodeEntry, ViewNodeInstance, ViewScope } from '../canvas/types.ts';
import type { Hardware, NodeKind, RefEdge, Task, TaskStatus } from '../model/types.ts';
import { dagLayout, viewNodeLayout, NODE_HEIGHT, NODE_WIDTH, VIEW_NODE_HEIGHT, VIEW_NODE_WIDTH, type Attached, type Position } from './layout.ts';
import { STATE_STYLE } from './stateStyle.ts';

type Props = {
  tasks: Task[]; hardware: readonly Hardware[]; states: Record<string, { status: TaskStatus; attempt: number }>;
  selected?: string; dimUnrelated?: boolean; onOpen(task: Task): void;
  /**
   * 되돌아가는 엣지 (260831 노드 분화). **`deps` 가 아니라 별도로 받는다** — 레이아웃·깊이
   * 계산에 넣으면 순환이 된다. 그런데 그리지 않으면 사용자는 이 대본이 되돌아간다는 것을
   * 알 수 없다. 그래서 점선 + `↺ 문구` 로 **그리기만** 한다.
   */
  refEdges?: readonly RefEdge[];
  /**
   * 뷰 노드 층 (260903 — 노드 캔버스 1단계). **없으면 지금까지와 한 픽셀도 다르지 않다** —
   * 단독 전달본과 렌더러 주입이 없는 빌드가 그렇다.
   *
   * 실행 노드와 **절대 섞지 않는다**: 여기 들어오는 것은 `deps` 도 상태(8상태)도 갖지
   * 않고, 아래 깊이·배치 계산은 `tasks` 만 본다.
   */
  canvas?: CanvasLayer;
};

/** 캔버스가 그래프에 넘겨주는 것 — 무엇을 그릴지와, 사용자가 만졌을 때 무엇을 할지. */
export type CanvasLayer = {
  nodes: readonly ViewNodeInstance[];
  /** 등록되지 않은 종류면 null (단독 빌드에서 열린 통합 구성 등). */
  entryOf(kind: string): ViewNodeEntry | null;
  /** 연결이 곧 범위 (`VZ-N-02`) — 계산은 `canvas/scope.ts` 하나에 있다. */
  scopeOf(taskId: string | null): ViewScope;
  /** 팔레트가 꺼낼 노드를 붙일 태스크. 한 번 누르면 골라진다. */
  pickedTaskId: string | null;
  onPick(taskId: string | null): void;
  onMove(id: string, position: Position): void;
  onBind(id: string, taskId: string | null): void;
  onRemove(id: string): void;
  /**
   * 지금 확대된 뷰 노드 (260903 2단계). **문자열 하나다** — 배열이면 둘이 열리고,
   * 둘이 열리면 분할 화면이고, 분할 화면은 곧 탭이 된다 (지시서 §6).
   */
  zoomedId: string | null;
  onZoom(id: string | null): void;
  /** 방금 안내줄이 가리킨 노드. 잠깐 반짝이고 스스로 꺼진다 (260903). */
  highlightedId: string | null;
};

/** 노드 문법 5종의 화면 표기 — 마일스톤을 왜 이렇게 쪼갰는지가 노드 위에 보인다. */
const NODE_KIND_LABEL: Record<NodeKind, string> = {
  sense: '관측', decide: '판정', act: '구동', verify: '검증', report: '보고',
};

/**
 * 폭을 아직 못 쟀을 때의 대비값 (260901). 옛 `.graph-canvas` 의 `min-width` 와 같은 값이라
 * 첫 프레임의 배치가 예전과 같고, 잰 값이 들어오면 곧바로 그 폭에 맞춰 접힌다.
 */
const FALLBACK_WIDTH = 1120;
/**
 * 캔버스가 아무리 작아도 이만큼은 된다 (260904). **옛 바닥값 그대로다** — 잰 값이 이보다
 * 작게 나오는 창(아주 낮은 창·개발 도구를 아래에 띄운 화면)에서 지금보다 나빠지지 않는다.
 */
const MIN_CANVAS_HEIGHT = 390;
/** 페이지 아래 여백(`main` 의 `padding-bottom`). 캔버스가 창 밑에 딱 붙으면 답답하다. */
const PAGE_BOTTOM = 40;

function connectionPath(from: { x: number; y: number }, to: { x: number; y: number }) {
  const dx = to.x - from.x; const dy = to.y - from.y;
  if (Math.abs(dx) >= NODE_WIDTH + 20) {
    const forward = dx > 0; const x1 = from.x + (forward ? NODE_WIDTH : 0); const x2 = to.x + (forward ? 0 : NODE_WIDTH);
    const y1 = from.y + NODE_HEIGHT / 2; const y2 = to.y + NODE_HEIGHT / 2; const middle = (x1 + x2) / 2;
    return `M${x1},${y1} C${middle},${y1} ${middle},${y2} ${x2},${y2}`;
  }
  const downward = dy >= 0; const x1 = from.x + NODE_WIDTH / 2; const x2 = to.x + NODE_WIDTH / 2;
  const y1 = from.y + (downward ? NODE_HEIGHT : 0); const y2 = to.y + (downward ? 0 : NODE_HEIGHT); const middle = (y1 + y2) / 2;
  return `M${x1},${y1} C${x1},${middle} ${x2},${middle} ${x2},${y2}`;
}

/**
 * **줄바꿈 엣지** — 밴드 마지막 열에서 다음 밴드 첫 열로 되돌아가는 연결선 (260901).
 *
 * 그대로 `connectionPath()` 에 맡기면 화면을 가로지르는 긴 곡선이 된다. 오른쪽으로 빠져나가
 * 밴드 사이 통로로 내려온 뒤 왼쪽으로 달려 다음 밴드의 왼쪽으로 들어간다.
 *
 * **되돌아가는 참조 엣지(점선 `↺`)와 반드시 구별되어야 한다** — 하나는 「줄바꿈」이고
 * 하나는 「루프」다. 이쪽은 **실선 파랑 + `↵`**, 저쪽은 점선 주황 + `↺` 다.
 */
function wrapPath(from: Position, to: Position): string {
  const x1 = from.x + NODE_WIDTH;
  const y1 = from.y + NODE_HEIGHT / 2;
  const x2 = to.x;
  const y2 = to.y + NODE_HEIGHT / 2;
  const lane = (from.y + NODE_HEIGHT + to.y) / 2; // 두 밴드 사이 통로
  const turn = x1 + 30;
  const entry = Math.max(6, x2 - 30);
  return `M${x1},${y1} C${turn},${y1} ${turn},${lane} ${turn - 12},${lane} L${entry + 12},${lane} C${entry},${lane} ${entry},${y2} ${x2},${y2}`;
}

/**
 * **범위 엣지** — 태스크에서 그 태스크에 연결된 뷰 노드로 내려오는 선 (260903).
 *
 * 셋째 선 종류다. 앞의 둘과 섞이면 안 된다 — 실행 흐름(실선 회색 · 화살표) · 되돌아감
 * (점선 주황 `↺`) · 줄바꿈(실선 파랑 `↵`) 과 달리 이것은 **흐름이 아니라 소속**이라
 * 화살표를 달지 않고 점선 초록으로 그린다. 이 선이 있고 없고가 「연결 ↔ 전역」의
 * 가장 큰 차이다(`VZ-N-02` — 두 상태는 화면에서 구별되어야 한다).
 */
function bindPath(from: Position, to: Position): string {
  const x1 = from.x + NODE_WIDTH / 2;
  const y1 = from.y + NODE_HEIGHT;
  const x2 = to.x + VIEW_NODE_WIDTH / 2;
  const y2 = to.y;
  const middle = (y1 + y2) / 2;
  return `M${x1},${y1} C${x1},${middle} ${x2},${middle} ${x2},${y2}`;
}

export function TaskGraph({ tasks, hardware, states, selected, dimUnrelated, onOpen, refEdges, canvas }: Props) {
  // 자기 자리의 **실제 폭과 높이**를 잰다 (260901 폭 · 260904 높이) — 배치가 폭을 모르면
  // 화면 밖으로 나가고, 높이를 모르면 남는 세로를 안 쓰면서 필요 이상으로 접는다.
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [available, setAvailable] = useState<{ width: number; height: number } | null>(null);
  useEffect(() => {
    const host = hostRef.current;
    if (host === null) return;
    /**
     * 세로는 자기 `clientHeight` 로 잴 수 없다 — 그 값이 곧 내용 높이라 자기를 되먹인다.
     * **창 바닥까지 남은 자리**를 잰다: 창 높이 − 캔버스 시작 y − 아래에 깔린 것.
     *
     * 「아래에 깔린 것」(범례·안내줄·패널 아래 여백)은 고정 픽셀로 적지 않고 **패널 바닥과
     * 캔버스 바닥의 차이로 잰다** — 캔버스가 커지면 패널도 같이 커지므로 이 차이는 캔버스
     * 높이와 무관하고, 그래서 이 계산이 순환하지 않는다.
     */
    const measure = () => {
      const rect = host.getBoundingClientRect();
      const panel = host.closest('.graph-panel');
      const below = panel === null ? 0 : Math.max(0, panel.getBoundingClientRect().bottom - rect.bottom);
      const viewport = typeof window === 'undefined' ? 0 : window.innerHeight;
      setAvailable({
        width: host.clientWidth,
        height: Math.max(MIN_CANVAS_HEIGHT, Math.round(viewport - rect.top - below - PAGE_BOTTOM)),
      });
    };
    measure();
    // 창 높이만 바뀌면 자리 크기는 그대로라 ResizeObserver 가 안 깨어난다 — 둘 다 듣는다.
    window.addEventListener('resize', measure);
    if (typeof ResizeObserver === 'undefined') {
      return () => window.removeEventListener('resize', measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(host);
    return () => { window.removeEventListener('resize', measure); observer.disconnect(); };
  }, []);
  const layoutWidth = available?.width ?? FALLBACK_WIDTH;
  /** 아직 못 쟀으면 `undefined` — 배치는 높이를 모른 채 옛 규칙(폭 최대 열)으로 붙인다. */
  const layoutHeight = available?.height;

  /**
   * 태스크마다 붙은 뷰 노드 수. 배치가 이만큼 아래를 밀어내지 않으면 뷰 노드가 그 열의
   * 다음 태스크와 겹친다 (`verify:layout` 의 겹침·최대 y 검사).
   */
  const attached = useMemo<Attached>(() => {
    const counts = new Map<string, number>();
    for (const node of canvas?.nodes ?? []) {
      if (node.taskId === null) continue;
      counts.set(node.taskId, (counts.get(node.taskId) ?? 0) + 1);
    }
    return counts;
  }, [canvas?.nodes]);
  /**
   * 기준 배치. **DAG 하나다** (260904 — 요구사항정의서 §7.10). 배치 모드 토글이 없어졌고
   * `treeLayout()` 은 지워지지 않은 채 부르는 곳만 `scripts/measure-representation.mjs` 로
   * 옮겨 갔다 — 「트리로 만들면 이만큼 나빠진다」를 숫자로 내는 도구다. 화면은 트리를
   * 언급하지 않는다.
   */
  const basePositions = useMemo(
    () => dagLayout(tasks, layoutWidth, attached, layoutHeight),
    [attached, tasks, layoutWidth, layoutHeight],
  );
  const [movedPositions, setMovedPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [drag, setDrag] = useState<{ id: string; offsetX: number; offsetY: number; startX: number; startY: number; kind: 'task' | 'view' } | null>(null);
  /**
   * 끄는 중인 뷰 노드의 자리. **끌 때마다 저장하지 않는다** — 뷰 노드의 좌표는
   * `localStorage` 에 있어서 pointermove 마다 쓰면 한 번 끄는 데 수백 번을 쓴다.
   * 손을 뗄 때 한 번 굳힌다.
   */
  const [viewDrag, setViewDrag] = useState<{ id: string; x: number; y: number } | null>(null);
  /** 끌지 않고 눌렀다 뗐으면 「고르기」다 — 팔레트가 이 태스크에 노드를 붙인다. */
  const movedRef = useRef(false);
  /**
   * 실행 노드의 이동 위치를 언제 버리는가 (260904 — 계기가 바뀌었다).
   *
   * 배치 모드 토글이 없어지면서 옛 계기(`[layoutMode]`)가 사라졌다. 새 계기는 **보고 있는
   * 태스크 집합이 바뀔 때**다 — 마일스톤을 옮기거나 「임무 전체」로 넘어가면 화면에 있는
   * 노드가 통째로 달라져서, 옛 자리를 들고 있어 봐야 남의 자리다.
   *
   * **창 크기는 계기가 아니다** — 폭·높이가 바뀌었다고 사용자가 옮긴 노드를 되돌리지 않는다
   * (`VZ-N-04` · 지시서 §1 「하지 말 것」). 그래서 이 의존 배열에 `layoutWidth`·`layoutHeight`
   * 가 없다. id 목록을 키로 쓰는 이유도 같다 — 배정이 바뀌어 `tasks` 배열의 정체성만
   * 새로워진 경우까지 되돌리면 안 된다.
   */
  const taskSetKey = tasks.map((task) => task.id).join(',');
  useEffect(() => setMovedPositions({}), [taskSetKey]);
  const positions = useMemo(() => Object.fromEntries(tasks.map((task) => [task.id, movedPositions[task.id] ?? basePositions[task.id]])), [basePositions, movedPositions, tasks]);
  /**
   * 뷰 노드의 기준 자리 — 연결한 태스크 **아래**, 전역이면 맨 아래 레인. 태스크를 끌면
   * 딸린 뷰 노드도 따라온다(옮긴 자리 기준으로 계산한다).
   */
  const viewBase = useMemo(
    () => viewNodeLayout(canvas?.nodes ?? [], positions, layoutWidth),
    [canvas?.nodes, positions, layoutWidth],
  );
  const viewPositions = useMemo(() => Object.fromEntries((canvas?.nodes ?? []).map((node) => {
    if (viewDrag !== null && viewDrag.id === node.id) return [node.id, { x: viewDrag.x, y: viewDrag.y }];
    // 사용자가 놓아 둔 좌표가 있으면 그것이 이긴다. **자동 배치가 다시 계산돼도 지우지
    // 않는다** — 태스크의 movedPositions 와 저장소가 다른 이유가 이것이다 (`VZ-N-04`).
    if (node.x !== null && node.y !== null) return [node.id, { x: node.x, y: node.y }];
    return [node.id, viewBase[node.id] ?? { x: 30, y: 55 }];
  })) as Record<string, Position>, [canvas?.nodes, viewBase, viewDrag]);
  // 높이는 노드 위치에서 계산한다 (260831) — 노드 분화 뒤에는 한 열에 노드가 셋씩 쌓이고
  // 「임무 전체」 보기는 열일곱이라, 상수 높이면 아래쪽 노드와 참조 엣지 문구가 잘린다.
  // 바닥값이 **잰 높이**다 (260904) — 작은 그래프도 화면 아래까지 자리를 차지한다. 옛 390 은
  // 16:9 모니터에서 아래를 통째로 비웠고, 노드를 아래로 끌어 놓을 자리도 없었다.
  const height = Math.max(
    layoutHeight ?? MIN_CANVAS_HEIGHT,
    ...Object.values(positions).map((position) => position.y + NODE_HEIGHT + ((refEdges?.length ?? 0) > 0 ? 70 : 30)),
    // 뷰 노드가 세로를 밀어낸다 — 캔버스가 따라 커지지 않으면 아래쪽 카드가 잘린다.
    ...Object.values(viewPositions).map((position) => position.y + VIEW_NODE_HEIGHT + 30),
  );
  // 폭은 **잰 자리 폭**과 실제 내용 중 큰 쪽이다 (260901). 접힌 배치는 잰 폭 안에 들어오므로
  // 보통 자리 폭 그대로이고, 사용자가 노드를 오른쪽으로 끌었거나 접기를 포기한 좁은 창
  // (MIN_COLS 미만)에서만 내용이 커져 가로 스크롤이 생긴다.
  const width = Math.max(
    layoutWidth,
    ...Object.values(positions).map((position) => position.x + NODE_WIDTH + 30),
    ...Object.values(viewPositions).map((position) => position.x + VIEW_NODE_WIDTH + 30),
  );
  /**
   * 밴드를 넘어가는 deps — **기준 배치**로 판정한다. 사용자가 노드를 끌었다고 선 모양이
   * 바뀌면 안 되기 때문이다. deps 는 낮은 깊이 → 높은 깊이라 한 밴드 안에서는 늘 오른쪽으로
   * 가므로, 왼쪽·아래로 가는 것이 곧 줄바꿈이다.
   */
  const wrapped = useMemo(() => {
    const set = new Set<string>();
    for (const task of tasks) {
      for (const dep of task.deps) {
        const from = basePositions[dep];
        const to = basePositions[task.id];
        if (from && to && to.x <= from.x && to.y > from.y) set.add(`${dep}-${task.id}`);
      }
    }
    return set;
  }, [basePositions, tasks]);
  const relevant = new Set<string>();
  if (dimUnrelated && selected) {
    const visit = (id: string) => { if (relevant.has(id)) return; relevant.add(id); tasks.find((task) => task.id === id)?.deps.forEach(visit); };
    visit(selected);
  }
  const startDrag = (event: ReactPointerEvent<HTMLElement>, id: string, kind: 'task' | 'view') => {
    const surface = event.currentTarget.parentElement;
    const position = kind === 'task' ? positions[id] : viewPositions[id];
    if (!surface || !position) return;
    const rect = surface.getBoundingClientRect(); event.currentTarget.setPointerCapture(event.pointerId);
    movedRef.current = false;
    setDrag({ id, kind, startX: event.clientX, startY: event.clientY, offsetX: event.clientX - rect.left + surface.scrollLeft - position.x, offsetY: event.clientY - rect.top + surface.scrollTop - position.y });
  };
  const moveDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag) return; const rect = event.currentTarget.getBoundingClientRect();
    const box = drag.kind === 'task' ? { w: NODE_WIDTH, h: NODE_HEIGHT } : { w: VIEW_NODE_WIDTH, h: VIEW_NODE_HEIGHT };
    const x = Math.max(0, Math.min(width - box.w, event.clientX - rect.left + event.currentTarget.scrollLeft - drag.offsetX));
    const y = Math.max(0, Math.min(height - box.h, event.clientY - rect.top + event.currentTarget.scrollTop - drag.offsetY));
    // 3px 안쪽의 흔들림은 「끌었다」가 아니다 — 누를 때 손이 조금 움직였다고 고르기가
    // 안 되면, 팔레트로 가는 유일한 길이 사람마다 되기도 하고 안 되기도 한다.
    if (Math.abs(event.clientX - drag.startX) > 3 || Math.abs(event.clientY - drag.startY) > 3) movedRef.current = true;
    if (drag.kind === 'task') setMovedPositions((current) => ({ ...current, [drag.id]: { x, y } }));
    else setViewDrag({ id: drag.id, x, y });
  };
  /** 손을 뗄 때 뷰 노드의 자리를 한 번만 굳힌다(저장은 여기서 일어난다). */
  const endDrag = () => {
    if (viewDrag !== null) canvas?.onMove(viewDrag.id, { x: viewDrag.x, y: viewDrag.y });
    setViewDrag(null);
    setDrag(null);
  };
  return <div className="graph-scroll" ref={hostRef}><div
    className={`graph-canvas ${drag ? 'is-dragging' : ''}`}
    style={{ height, width }}
    onPointerMove={moveDrag}
    onPointerUp={endDrag}
    onPointerCancel={endDrag}
    // 빈 자리를 누르면 고르기를 푼다 — 팔레트가 그때부터 전역 노드를 만든다.
    onPointerDown={(event) => { if (event.target === event.currentTarget) canvas?.onPick(null); }}
  >
    <svg className="edges" width={width} height={height} aria-hidden="true">
      <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
      {/* 되돌아가는 참조 엣지 — 점선 + ↺ 문구. 깊이·레이아웃 계산에는 들어가지 않는다 (260831). */}
      {(refEdges ?? []).map((edge) => {
        const from = positions[edge.from]; const to = positions[edge.to]; if (!from || !to) return null;
        const midX = (from.x + to.x) / 2 + NODE_WIDTH / 2;
        const midY = Math.max(from.y, to.y) + NODE_HEIGHT + 28;
        return <g key={`ref-${edge.from}-${edge.to}`}>
          <path className="edge edge--ref" d={`M${from.x + NODE_WIDTH / 2},${from.y + NODE_HEIGHT} C${from.x + NODE_WIDTH / 2},${midY} ${to.x + NODE_WIDTH / 2},${midY} ${to.x + NODE_WIDTH / 2},${to.y + NODE_HEIGHT}`} markerEnd="url(#arrow)" />
          <text className="edge__label" x={midX} y={midY + 14} textAnchor="middle">↺ {edge.label}</text>
        </g>;
      })}
      {tasks.flatMap((task) => task.deps.map((dep) => {
        const from = positions[dep]; const to = positions[task.id]; if (!from || !to) return null;
        const key = `${dep}-${task.id}`;
        const dim = dimUnrelated && (!relevant.has(dep) || !relevant.has(task.id)) ? ' dimmed' : '';
        // 줄바꿈(↵ · 실선 파랑)과 되돌아감(↺ · 점선 주황)은 **다른 것**이다. 섞이면 안 된다.
        if (wrapped.has(key)) {
          const lane = (from.y + NODE_HEIGHT + to.y) / 2;
          return <g key={key}>
            <path className={`edge edge--wrap${dim}`} d={wrapPath(from, to)} markerEnd="url(#arrow)" />
            <text className="edge__wrapmark" x={to.x + 6} y={lane - 6}>↵ 줄바꿈</text>
          </g>;
        }
        return <path key={key} className={`edge${dim}`} d={connectionPath(from, to)} markerEnd="url(#arrow)" />;
      }))}
      {/* 범위 엣지 (260903) — 태스크 → 그 태스크에 연결된 뷰 노드. 흐름이 아니라 소속이라
          화살표가 없다. **deps 가 아니다** — 깊이 계산은 위의 tasks 만 본다. */}
      {(canvas?.nodes ?? []).map((node) => {
        if (node.taskId === null) return null;
        const from = positions[node.taskId]; const to = viewPositions[node.id];
        if (!from || !to) return null;
        return <path key={`bind-${node.id}`} className="edge edge--bind" d={bindPath(from, to)} />;
      })}
    </svg>
    {tasks.map((task) => {
      const state = states[task.id] ?? { status: 'pending' as const, attempt: 1 }; const style = STATE_STYLE[state.status];
      const device = hardware.find((item) => item.id === task.target); const dimmed = dimUnrelated && !relevant.has(task.id);
      const position = positions[task.id];
      // 한 번 누르면 「고른 태스크」가 된다 (260903) — 팔레트가 여기에 뷰 노드를 붙인다.
      // 끌었으면 고르지 않는다. 더블클릭(액션 아이템)은 그대로다.
      return <button key={task.id} type="button" className={`task-node ${style.className} ${selected === task.id ? 'selected' : ''} ${canvas?.pickedTaskId === task.id ? 'is-picked' : ''} ${dimmed ? 'dimmed' : ''}`} style={{ left: position.x, top: position.y }} onPointerDown={(event) => startDrag(event, task.id, 'task')} onClick={() => { if (!movedRef.current) canvas?.onPick(task.id); }} onDoubleClick={() => onOpen(task)}>
        <small>{task.id}{task.nodeKind ? <em className={`node-kind node-kind--${task.nodeKind}`}>{NODE_KIND_LABEL[task.nodeKind]}</em> : null}</small><strong>{task.title}</strong>
        <span className="state-label">{style.icon} {style.label}{state.status === 'rerunning' ? ` · attempt ${state.attempt}` : ''}</span>
        {/* 옛 편은 하드웨어 목록이 있어 기존 문구 그대로다. 대본(registry 세계)의 장비 실측
            상태는 남이 줄 데이터라 '오프라인'이라고 지어 말하지 않는다 — 미수신은 미수신이다.
            (칩 자체의 A/B 처리는 8/31 보류 항목 1 그대로 미결이다.) */}
        <span className={`device ${device?.connection ?? 'unknown'}`}>{task.target === null ? '대상 없음' : `${task.target} · ${device ? (device.connection === 'online' ? '온라인' : device.connection === 'maintenance' ? '점검' : '오프라인') : '상태 미수신'}`}</span>
      </button>;
    })}
    {/* 뷰 노드 — 내용은 주입된 렌더러가 그린다. 여기까지가 캔버스가 아는 전부다. */}
    {(canvas?.nodes ?? []).map((node) => <ViewNodeCard
      key={node.id}
      node={node}
      entry={canvas!.entryOf(node.kind)}
      scope={canvas!.scopeOf(node.taskId)}
      position={viewPositions[node.id] ?? { x: 30, y: 55 }}
      picked={canvas!.pickedTaskId}
      zoomed={canvas!.zoomedId === node.id}
      highlighted={canvas!.highlightedId === node.id}
      onPointerDown={(event) => startDrag(event, node.id, 'view')}
      onBind={(taskId) => canvas!.onBind(node.id, taskId)}
      onRemove={() => canvas!.onRemove(node.id)}
      onZoom={() => canvas!.onZoom(node.id)} />)}
  </div></div>;
}
