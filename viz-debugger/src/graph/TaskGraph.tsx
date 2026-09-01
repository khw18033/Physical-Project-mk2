import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import type { Hardware, NodeKind, RefEdge, Task, TaskStatus } from '../model/types.ts';
import { dagLayout, treeLayout, NODE_HEIGHT, NODE_WIDTH, type Position } from './layout.ts';
import { STATE_STYLE } from './stateStyle.ts';

type Props = {
  tasks: Task[]; hardware: readonly Hardware[]; states: Record<string, { status: TaskStatus; attempt: number }>;
  layoutMode: 'dag' | 'tree'; selected?: string; dimUnrelated?: boolean; onOpen(task: Task): void;
  /**
   * 되돌아가는 엣지 (260831 노드 분화). **`deps` 가 아니라 별도로 받는다** — 레이아웃·깊이
   * 계산에 넣으면 순환이 된다. 그런데 그리지 않으면 사용자는 이 대본이 되돌아간다는 것을
   * 알 수 없다. 그래서 점선 + `↺ 문구` 로 **그리기만** 한다.
   */
  refEdges?: readonly RefEdge[];
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

export function TaskGraph({ tasks, hardware, states, layoutMode, selected, dimUnrelated, onOpen, refEdges }: Props) {
  // 자기 자리의 **실제 폭**을 잰다 (260901) — 배치가 폭을 모르면 화면 밖으로 나간다.
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [availableWidth, setAvailableWidth] = useState<number | null>(null);
  useEffect(() => {
    const host = hostRef.current;
    if (host === null) return;
    const measure = () => setAvailableWidth(host.clientWidth);
    measure();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure);
      return () => window.removeEventListener('resize', measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(host);
    return () => observer.disconnect();
  }, []);
  const layoutWidth = availableWidth ?? FALLBACK_WIDTH;

  const basePositions = useMemo(
    () => (layoutMode === 'dag' ? dagLayout(tasks, layoutWidth) : treeLayout(tasks, layoutWidth)),
    [layoutMode, tasks, layoutWidth],
  );
  const [movedPositions, setMovedPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [drag, setDrag] = useState<{ id: string; offsetX: number; offsetY: number } | null>(null);
  // **창 크기가 바뀌었다고 사용자가 옮긴 노드를 되돌리지 않는다** — 기준 배치만 다시 계산한다.
  // 그래서 이 의존 배열에 layoutWidth 가 없다 (260901).
  useEffect(() => setMovedPositions({}), [layoutMode]);
  const positions = useMemo(() => Object.fromEntries(tasks.map((task) => [task.id, movedPositions[task.id] ?? basePositions[task.id]])), [basePositions, movedPositions, tasks]);
  // 높이는 노드 위치에서 계산한다 (260831) — 노드 분화 뒤에는 한 열에 노드가 셋씩 쌓이고
  // 「임무 전체」 보기는 열일곱이라, 상수 높이면 아래쪽 노드와 참조 엣지 문구가 잘린다.
  const height = Math.max(
    layoutMode === 'dag' ? 390 : 690,
    ...Object.values(positions).map((position) => position.y + NODE_HEIGHT + ((refEdges?.length ?? 0) > 0 ? 70 : 30)),
  );
  // 폭은 **잰 자리 폭**과 실제 내용 중 큰 쪽이다 (260901). 접힌 배치는 잰 폭 안에 들어오므로
  // 보통 자리 폭 그대로이고, 사용자가 노드를 오른쪽으로 끌었거나 접기를 포기한 좁은 창
  // (MIN_COLS 미만)에서만 내용이 커져 가로 스크롤이 생긴다.
  const width = Math.max(layoutWidth, ...Object.values(positions).map((position) => position.x + NODE_WIDTH + 30));
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
  const startDrag = (event: ReactPointerEvent<HTMLButtonElement>, id: string) => {
    const canvas = event.currentTarget.parentElement; const position = positions[id]; if (!canvas || !position) return;
    const rect = canvas.getBoundingClientRect(); event.currentTarget.setPointerCapture(event.pointerId);
    setDrag({ id, offsetX: event.clientX - rect.left + canvas.scrollLeft - position.x, offsetY: event.clientY - rect.top + canvas.scrollTop - position.y });
  };
  const moveDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag) return; const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.max(0, Math.min(width - NODE_WIDTH, event.clientX - rect.left + event.currentTarget.scrollLeft - drag.offsetX));
    const y = Math.max(0, Math.min(height - NODE_HEIGHT, event.clientY - rect.top + event.currentTarget.scrollTop - drag.offsetY));
    setMovedPositions((current) => ({ ...current, [drag.id]: { x, y } }));
  };
  return <div className="graph-scroll" ref={hostRef}><div className={`graph-canvas ${drag ? 'is-dragging' : ''}`} style={{ height, width }} onPointerMove={moveDrag} onPointerUp={() => setDrag(null)} onPointerCancel={() => setDrag(null)}>
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
    </svg>
    {tasks.map((task) => {
      const state = states[task.id] ?? { status: 'pending' as const, attempt: 1 }; const style = STATE_STYLE[state.status];
      const device = hardware.find((item) => item.id === task.target); const dimmed = dimUnrelated && !relevant.has(task.id);
      const position = positions[task.id];
      return <button key={task.id} type="button" className={`task-node ${style.className} ${selected === task.id ? 'selected' : ''} ${dimmed ? 'dimmed' : ''}`} style={{ left: position.x, top: position.y }} onPointerDown={(event) => startDrag(event, task.id)} onDoubleClick={() => onOpen(task)}>
        <small>{task.id}{task.nodeKind ? <em className={`node-kind node-kind--${task.nodeKind}`}>{NODE_KIND_LABEL[task.nodeKind]}</em> : null}</small><strong>{task.title}</strong>
        <span className="state-label">{style.icon} {style.label}{state.status === 'rerunning' ? ` · attempt ${state.attempt}` : ''}</span>
        {/* 옛 편은 하드웨어 목록이 있어 기존 문구 그대로다. 대본(registry 세계)의 장비 실측
            상태는 남이 줄 데이터라 '오프라인'이라고 지어 말하지 않는다 — 미수신은 미수신이다.
            (칩 자체의 A/B 처리는 8/31 보류 항목 1 그대로 미결이다.) */}
        <span className={`device ${device?.connection ?? 'unknown'}`}>{task.target === null ? '대상 없음' : `${task.target} · ${device ? (device.connection === 'online' ? '온라인' : device.connection === 'maintenance' ? '점검' : '오프라인') : '상태 미수신'}`}</span>
      </button>;
    })}
  </div></div>;
}
