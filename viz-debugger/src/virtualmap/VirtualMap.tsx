/**
 * src/virtualmap/VirtualMap.tsx (260927 신설 — 가상 맵 뷰 노드)
 *
 * **Unity 또는 2D 맵.** 어느 쪽인지는 노드가 아니라 **연결 관리**가 정한다 — 「가상 맵」 대상에
 * Unity 주소를 넣으면 Unity 화면을, 비워 두면 2D 맵을 그린다. 버튼을 둘로 늘리지 않는다(260927 지시).
 *
 * ## 2D 맵이 그리는 것
 *
 * 전부 **대본과 기록 열**에서 온다 — 화면이 계산해 지어 넣는 값이 없다.
 *
 *   방 · 문       대본의 `params.virtual_map` (Unity 씬에서 뽑은 503호 경계와 같은 값 · `places/`)
 *   @ 자리        「가상 맵에서 @ 위치 확인」이 끝난 뒤에만 찍힌다
 *   장치 경로     그 장치의 「경로 탐지」가 끝난 뒤에만 그린다
 *   장치 위치     「이동 시작」 전에는 출발점, 「이동 완료 확인」이 판정에 들어가면 경로 끝.
 *                 그 사이는 경로 위를 시간 비율로 옮긴다(대본 편이라 실측 위치가 없다 — 카드에 그렇게 적는다)
 *
 * 전부 **재생 머리까지 흘러온 기록**으로 판정한다 — 되감으면 맵도 따라 되감긴다(`VZ-N-03`).
 */

import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { useConnections, connectionAddress } from '../shared/connections.ts';
import { displayMission, useMission } from '../data/scenario.ts';
import { useSlotBindings } from '../data/slots.ts';
import { getLang } from '../shared/language.ts';
import placesTopology from '../../../places/places.json';
import type { ScenarioEvent } from '../model/types.ts';

type Point = { x: number; z: number };

type MapDevice = {
  slot: string;
  start: Point;
  path: Array<[number, number]>;
  path_task: string;
  move_start_task: string;
  arrive_task: string;
};

type MapSpec = {
  place?: string;
  bounds: { x_min: number; x_max: number; z_min: number; z_max: number };
  door?: Point;
  locate_task: string;
  target: Point;
  devices: MapDevice[];
};

/** 대본이 준 맵 자료. 모양이 안 맞으면 null — 맵이 없는 편이다. */
function mapSpecOf(params: Record<string, unknown>): MapSpec | null {
  const spec = params.virtual_map as MapSpec | undefined;
  if (spec === undefined || spec === null || typeof spec !== 'object') return null;
  if (typeof spec.bounds?.x_min !== 'number' || !Array.isArray(spec.devices)) return null;
  return spec;
}

const SLOT_COLORS = ['#3d8bfd', '#f08c2e', '#8a63d2', '#2fb380'];
const PAD = 0.8;

/** 경로 위 비율 `f` 자리. 구간 길이로 나눈다 — 꼭짓점 수로 나누면 짧은 구간에서 빨라진다. */
function along(path: Array<[number, number]>, f: number): Point {
  if (path.length === 0) return { x: 0, z: 0 };
  if (path.length === 1 || f <= 0) return { x: path[0][0], z: path[0][1] };
  const lengths = path.slice(1).map((p, i) => Math.hypot(p[0] - path[i][0], p[1] - path[i][1]));
  const total = lengths.reduce((a, b) => a + b, 0);
  let left = Math.min(1, f) * total;
  for (let i = 0; i < lengths.length; i += 1) {
    if (left <= lengths[i] || i === lengths.length - 1) {
      const r = lengths[i] === 0 ? 1 : Math.min(1, left / lengths[i]);
      return { x: path[i][0] + (path[i + 1][0] - path[i][0]) * r, z: path[i][1] + (path[i + 1][1] - path[i][1]) * r };
    }
    left -= lengths[i];
  }
  const last = path[path.length - 1];
  return { x: last[0], z: last[1] };
}

/** 머리까지 흘러온 사건 중 그 태스크의 첫 사건(상태가 맞는 것). */
function firstAt(trace: readonly ScenarioEvent[], taskId: string, headSec: number, statuses: readonly string[]): ScenarioEvent | null {
  return trace.find((event) => event.nodeId === taskId && event.atSec <= headSec && statuses.includes(event.status)) ?? null;
}

function placeLabel(placeId: string | undefined): string {
  if (placeId === undefined) return '';
  const place = (placesTopology as { places: Array<{ place_id: string; label: string; label_en?: string }> }).places
    .find((item) => item.place_id === placeId);
  if (place === undefined) return placeId;
  return getLang() === 'en' ? place.label_en ?? place.label : place.label;
}

function TwoDMap({ headSec, zoom }: { headSec: number; zoom: boolean }) {
  useLang();
  useMission();
  const bindings = useSlotBindings();
  const { view, trace } = displayMission();
  const spec = mapSpecOf(view.params);
  if (spec === null) return <p className="vn-line vn-dim">{t('vmap.noData')}</p>;

  const word = view.targetWord ?? null;
  const token = '@';
  const targetName = word ?? token;
  const { x_min, x_max, z_min, z_max } = spec.bounds;
  const width = x_max - x_min + PAD * 2;
  const height = z_max - z_min + PAD * 2;
  // 위에서 내려다본 그림 — x 는 오른쪽, z 는 위로 간다(문이 위쪽 벽에 선다).
  const sx = (x: number) => x - x_min + PAD;
  const sy = (z: number) => z_max - z + PAD;

  const located = firstAt(trace, spec.locate_task, headSec, ['done']) !== null;
  const slotLabel = (slot: string) => view.slots?.find((item) => item.id === slot)?.label ?? slot;

  // **실행기가 모는 판은 진행을 기록으로 남긴다** (260929). 그 판에서는 대본 시각으로 옮기지 않는다 — 실제 걸음이
  // 대본보다 느리거나 빠르면 지도만 앞서 간다.
  const liveProgress = trace.some((event) => event.kind === 'progress' && typeof event.payload?.slot === 'string');
  const devices = spec.devices.map((device, index) => {
    const pathShown = firstAt(trace, device.path_task, headSec, ['done']) !== null;
    const started = firstAt(trace, device.move_start_task, headSec, ['running', 'done']);
    const arrived = firstAt(trace, device.arrive_task, headSec, ['awaiting_evaluation', 'done']);
    const progressed = trace.filter((event) => event.kind === 'progress' && event.atSec <= headSec
      && event.payload?.slot === device.slot && typeof event.payload?.fraction === 'number').at(-1);
    // 도착 시각은 대본이 정한 것을 쓴다 — 아직 안 흘러온 사건을 기다리면 이동 중에 비율을 낼 수 없다.
    const plannedArrive = view.events.find((event) => event.nodeId === device.arrive_task
      && (event.status === 'awaiting_evaluation' || event.status === 'done'))?.atSec ?? null;
    let fraction = 0;
    if (arrived !== null) fraction = 1;
    else if (progressed !== undefined) fraction = Math.max(0, Math.min(1, progressed.payload!.fraction as number));
    else if (!liveProgress && started !== null && plannedArrive !== null && plannedArrive > started.atSec) {
      fraction = Math.max(0, Math.min(1, (headSec - started.atSec) / (plannedArrive - started.atSec)));
    }
    const at = fraction === 0 ? device.start : along(device.path, fraction);
    return {
      ...device,
      color: SLOT_COLORS[index % SLOT_COLORS.length],
      mark: String(index + 1),
      bound: bindings[device.slot] ?? null,
      pathShown,
      moving: (started !== null || progressed !== undefined) && arrived === null && fraction < 1,
      fraction,
      at,
    };
  });

  const fmt = (value: number) => value.toFixed(1);
  const grid: number[] = [];
  for (let x = Math.ceil(x_min); x <= Math.floor(x_max); x += 1) grid.push(x);
  const gridZ: number[] = [];
  for (let z = Math.ceil(z_min); z <= Math.floor(z_max); z += 1) gridZ.push(z);

  return <div className={`vmap${zoom ? ' vmap--zoom' : ''}`}>
    <svg className="vmap__svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t('vmap.aria')}>
      <rect className="vmap__room" x={sx(x_min)} y={sy(z_max)} width={x_max - x_min} height={z_max - z_min} />
      {grid.map((x) => <line key={`gx${x}`} className="vmap__grid" x1={sx(x)} x2={sx(x)} y1={sy(z_max)} y2={sy(z_min)} />)}
      {gridZ.map((z) => <line key={`gz${z}`} className="vmap__grid" x1={sx(x_min)} x2={sx(x_max)} y1={sy(z)} y2={sy(z)} />)}
      {spec.door !== undefined && <>
        <line className="vmap__door" x1={sx(spec.door.x) - 0.45} x2={sx(spec.door.x) + 0.45} y1={sy(spec.door.z)} y2={sy(spec.door.z)} />
        <text className="vmap__label" x={sx(spec.door.x)} y={sy(spec.door.z) - 0.25} textAnchor="middle">{t('vmap.door')}</text>
      </>}
      {devices.map((device) => device.pathShown && <polyline key={`p-${device.slot}`} className="vmap__path"
        stroke={device.color} points={device.path.map(([x, z]) => `${sx(x)},${sy(z)}`).join(' ')} />)}
      {located && <g className="vmap__target">
        <circle cx={sx(spec.target.x)} cy={sy(spec.target.z)} r={0.35} />
        <text className="vmap__label" x={sx(spec.target.x)} y={sy(spec.target.z) + 0.75} textAnchor="middle">{targetName}</text>
      </g>}
      {devices.map((device) => <g key={`d-${device.slot}`} className={`vmap__device${device.moving ? ' vmap__device--moving' : ''}`}>
        <circle cx={sx(device.at.x)} cy={sy(device.at.z)} r={0.3} fill={device.color} />
        <text className="vmap__mark" x={sx(device.at.x)} y={sy(device.at.z) + 0.12} textAnchor="middle">{device.mark}</text>
      </g>)}
    </svg>
    <ul className="vmap__legend">
      {devices.map((device) => <li key={device.slot}>
        <i style={{ background: device.color }}>{device.mark}</i>
        {t('vmap.slotLine', { slot: slotLabel(device.slot), device: device.bound ?? t('vmap.unbound'), x: fmt(device.at.x), z: fmt(device.at.z) })}
        {device.moving && <small> · {t('vmap.moving', { pct: Math.round(device.fraction * 100) })}</small>}
      </li>)}
      <li>{located
        ? t('vmap.targetAt', { target: targetName, x: fmt(spec.target.x), z: fmt(spec.target.z) })
        : t('vmap.targetUnknown', { target: targetName })}</li>
    </ul>
    {zoom && <p className="vn-line vn-dim">{t('vmap.twoDLine', { place: placeLabel(spec.place) })}</p>}
  </div>;
}

/**
 * 가상 맵 노드 본문. **Unity 주소가 있으면 Unity, 없으면 2D 맵.**
 *
 * Unity 는 주소가 가리키는 웹 화면(WebGL 빌드 · 스트리밍 페이지)을 그대로 띄운다 — 이 화면은 Unity 와
 * 말을 주고받지 않는다. 확대에서는 2D 맵을 접어서 함께 둔다: Unity 가 안 떴을 때 볼 것이 있어야 한다.
 */
export function VirtualMap({ headSec, zoom = false }: { headSec: number; zoom?: boolean }) {
  useLang();
  useConnections();
  const unity = connectionAddress('digital-twin', 'base').trim();
  if (unity === '') return <TwoDMap headSec={headSec} zoom={zoom} />;
  return <div className={`vmap vmap--unity${zoom ? ' vmap--zoom' : ''}`}>
    {/* 카드에서는 끌기가 먼저다 — 틀 안이 누름을 삼키면 노드를 못 옮긴다. 조작은 확대에서 한다. */}
    <iframe className="vmap__unity" src={unity} title={t('vmap.unityTitle')} style={zoom ? undefined : { pointerEvents: 'none' }} />
    <p className="vn-line vn-dim">{t('vmap.unityLine', { url: unity })}</p>
    {zoom && <details className="vmap__fallback">
      <summary>{t('vmap.show2d')}</summary>
      <TwoDMap headSec={headSec} zoom />
    </details>}
  </div>;
}
