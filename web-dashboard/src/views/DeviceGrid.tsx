/**
 * src/views/DeviceGrid.tsx
 *
 * VZ-U-01 — 구역 장치 현황판. **이번 범위는 이 화면 하나까지다.**
 *
 * 화면이 하지 않는 것을 적어 둔다(하면 계약이 무너진다).
 *  - stale 판정 — 서버가 한다. 여기서는 받은 availability를 읽기만 한다.
 *  - 좌표 변환  — 백엔드가 한다. 여기에는 변환 코드가 없다.
 *  - 명령 발행  — 만들지 않는다. 아래 시나리오 버튼은 목 서버 안의 왕복을 트리거할 뿐이다.
 */

import { useEffect } from 'react';
import {
  DISPLAY_STATUS_LABEL,
  RENDER_MERGE_WINDOW_MS,
  SHOW_RENDER_COUNTER,
  ZONE_BOARD_REFRESH_MS,
  guardedMean,
  playScenario,
  startDataLayer,
  store,
  type DisplayStatus,
} from '../data/index.ts';
import { useConnectionStatus, useEntities, useRenderRate, useRole, useZoneSummary } from '../data/hooks.ts';
import { DeviceCard } from './DeviceCard.tsx';

/** 현재 설계 전제는 구역 1개(VZ-C-05). 구역이 늘면 이 값이 선택 상태가 된다. */
const ZONE_ID = 'zone-503';

const STATUS_ORDER: DisplayStatus[] = ['normal', 'fault', 'unknown', 'not_deployed'];

/** 시나리오 버튼 — 상태 전이를 손으로 재생해야 화면이 전이 순간에 맞는지 볼 수 있다. */
const SCENARIO_BUTTONS: Array<{ name: string; label: string }> = [
  { name: 'camera-silence', label: 'camera-02 침묵 → 판단 불가' },
  { name: 'camera-resume', label: 'camera-02 재개' },
  { name: 'sensor-offline', label: 'sensor-02 끊김 → 복구' },
  { name: 'sensor-surge', label: 'sensor-01 급변 → 이벤트 모드' },
  { name: 'actuator-command', label: 'actuator-01 명령 왕복' },
  { name: 'robot-idle', label: 'robot-01 대기' },
  { name: 'robot-mission', label: 'robot-01 임무(20Hz)' },
];

export function DeviceGrid() {
  useEffect(() => startDataLayer(ZONE_ID), []);

  const entities = useEntities();
  const summary = useZoneSummary(ZONE_ID);
  const connection = useConnectionStatus();
  const role = useRole();
  const renders = useRenderRate();

  const registry = store.getRegistry();
  const registryError = store.getRegistryError();
  const zone = registry?.zones.find((z) => z.id === ZONE_ID) ?? null;

  // 레지스트리 순서를 따른다 — 값이 오는 순서에 카드가 흔들리면 눈으로 못 쫓는다.
  // 미배포처럼 값이 한 번도 안 온 대상도 목록에 있으므로 카드가 나온다.
  const records = [...entities.values()]
    .filter((r) => r.registry?.zone === ZONE_ID)
    .sort((a, b) => a.id.localeCompare(b.id));

  return (
    <main className="board">
      <header className="board__head">
        <div>
          <h1 className="board__title">{zone?.display_name ?? ZONE_ID} · 구역 장치 현황판</h1>
          <p className="board__sub">
            device_status · availability · deployment 3층을 조합해 정상 / 장애 / 의도적 미배포 / 판단 불가를 구분한다
          </p>
        </div>
        <div className="board__meta">
          <span>갱신 {ZONE_BOARD_REFRESH_MS / 1000}초 · 병합 {RENDER_MERGE_WINDOW_MS}ms</span>
          <ConnectionBadge state={connection.state} attempt={connection.attempt} />
        </div>
      </header>

      {registryError !== null && (
        <p className="notice notice--warn">
          레지스트리 조회 실패 — {registryError}. 존재해야 할 목록이 없으면 미배포 대상은 화면에 나타나지
          않는다(VZ-I-03).
        </p>
      )}

      <section className="summary">
        {STATUS_ORDER.map((s) => (
          <div key={s} className={'summary__item summary__item--' + s}>
            <span className="summary__count">{summary.counts[s]}</span>
            <span className="summary__label">{DISPLAY_STATUS_LABEL[s]}</span>
          </div>
        ))}
        <div className="summary__item summary__item--total">
          <span className="summary__count">{summary.total}</span>
          <span className="summary__label">전체</span>
        </div>
      </section>

      <section className="grid">
        {records.map((r) => (
          <DeviceCard key={r.id} record={r} />
        ))}
        {records.length === 0 && <p className="notice">표시할 대상이 없다. 레지스트리를 받지 못했거나 구역이 비어 있다.</p>}
      </section>

      <MappingTable records={records} />

      <section className="devpanel">
        <h2 className="devpanel__title">시나리오 재생</h2>
        <div className="devpanel__row">
          {SCENARIO_BUTTONS.map((b) => (
            <button key={b.name} type="button" className="btn" onClick={() => playScenario(b.name)}>
              {b.label}
            </button>
          ))}
        </div>

        <h2 className="devpanel__title">계약 자리 확인</h2>
        <div className="devpanel__row devpanel__row--info">
          <span className="chip">
            역할 {role?.role ?? '조회 중'} · scope {role ? JSON.stringify(role.scope) : '—'}{' '}
            <em>(VZ-C-04 자리 확보)</em>
          </span>
          <span className="chip">
            구독 scope <code>"all"</code> <em>(VZ-I-11 자리 확보)</em>
          </span>
          <ReaggregationProbe />
        </div>

        {SHOW_RENDER_COUNTER && (
          <p className="devpanel__metrics">
            현황판 리렌더 {renders.perSecond}회/초 (누적 {renders.total}) · 수신 {store.merge.stats().received}건 ·
            병합 플러시 {store.merge.stats().flushed}회 · 즉시 반영 {store.merge.stats().immediate}회
          </p>
        )}
      </section>
    </main>
  );
}

function ConnectionBadge({ state, attempt }: { state: string; attempt: number }) {
  const label =
    state === 'open'
      ? '게이트웨이 연결됨'
      : state === 'reconnecting'
        ? '재연결 중 (' + attempt + '회)'
        : state === 'connecting'
          ? '연결 중'
          : '연결 종료';
  return <span className={'conn conn--' + state}>{label}</span>;
}

/**
 * 목업 오른쪽 매핑표. 지금 화면에 있는 대상이 어느 행에 해당하는지 함께 보여 준다 —
 * "왜 이 카드가 장애인가"를 표로 되짚을 수 있어야 조합 규칙이 검증된다.
 */
function MappingTable({ records }: { records: Array<{ id: string; state: { payload: unknown } | null }> }) {
  const rows: Array<{ dev: string; avail: string; dep: string; display: DisplayStatus }> = [
    { dev: 'ok', avail: 'online', dep: 'deployed', display: 'normal' },
    { dev: 'fault', avail: 'online', dep: 'deployed', display: 'fault' },
    { dev: '—', avail: 'offline', dep: 'deployed', display: 'fault' },
    { dev: 'ok', avail: 'stale', dep: 'deployed', display: 'unknown' },
    { dev: '—', avail: '—', dep: 'not_deployed', display: 'not_deployed' },
  ];

  /**
   * 대상 하나를 어느 행에 놓을지. **deriveDisplayStatus와 같은 우선순위**로 고른다 —
   * 표와 판정이 따로 놀면 표가 검증 수단이 되지 못한다.
   */
  const rowIndexOf = (layers: {
    device_status: string | null;
    availability: string | null;
    deployment: string;
  }): number => {
    if (layers.deployment !== 'deployed') return 4;
    if (layers.availability === 'offline') return 2;
    if (layers.availability === 'stale') return 3;
    if (layers.availability !== 'online') return -1;
    if (layers.device_status === 'fault') return 1;
    return 0;
  };

  const idsByRow: string[][] = [[], [], [], [], []];
  for (const r of records) {
    const layers = r.state?.payload as
      | { device_status: string | null; availability: string | null; deployment: string }
      | undefined;
    if (!layers) continue;
    const idx = rowIndexOf(layers);
    if (idx >= 0) idsByRow[idx].push(r.id);
  }

  return (
    <section className="mapping">
      <h2 className="mapping__title">3층 → 화면 표시 매핑</h2>
      <table className="mapping__table">
        <thead>
          <tr>
            <th>device_status</th>
            <th>availability</th>
            <th>deployment</th>
            <th>화면 표시</th>
            <th>현재 해당</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              <td>{row.dev}</td>
              <td>{row.avail}</td>
              <td>{row.dep}</td>
              <td>
                <span className={'badge badge--' + row.display}>{DISPLAY_STATUS_LABEL[row.display]}</span>
              </td>
              <td className="mapping__ids">{idsByRow[i].join(', ') || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mapping__note">
        단일 상태 값으로 뭉치면 표현 불가 — <strong>fault + online</strong>은 합치면 '정상'으로 보이고,{' '}
        <strong>stale</strong>은 끊기지 않았으므로 '정상'으로 보인다. 3층 원본을 그대로 받아 화면이 조합해야 네 칸이
        나온다.
      </p>
    </section>
  );
}

/**
 * VZ-C-03 검사 확인용. 집약값(15초 창에서 이미 평균된 CPU 지표)에 평균을 다시 적용해 본다.
 * 개발 모드에서 콘솔 경고가 뜨고 계산 결과는 null이 되어야 정상이다.
 */
function ReaggregationProbe() {
  const entities = useEntities();
  const metrics = entities.get('edge-node-a')?.metrics ?? null;

  const probe = () => {
    if (metrics === null) {
      console.info('[VZ-C-03] 아직 metrics 봉투를 받지 못했다. 15초 주기이므로 잠시 기다릴 것.');
      return;
    }
    const payload = metrics.payload as { cpu_pct?: { value: number } };
    const value = payload.cpu_pct?.value ?? 0;
    const result = guardedMean([{ value, aggregation: metrics.aggregation }], 'edge-node-a/metrics.cpu_pct');
    console.info('[VZ-C-03] guardedMean 결과 =', result, '(null 이면 재집약이 차단된 것)');
  };

  return (
    <button type="button" className="btn btn--probe" onClick={probe}>
      집약값에 평균 적용 시도 <em>(VZ-C-03 경고 확인)</em>
    </button>
  );
}
