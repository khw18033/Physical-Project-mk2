// 이식: web-dashboard/src/views/DeviceGrid.tsx @ 700ed91 — 대본 재생(260831): scenario 카드 분기
// 260901 — 구역 맵 미니뷰를 tabs/index.tsx 로 꺼냈다(패널마다 축이 달라 따로 접혀야 한다).
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

import { useLang } from '../../shared/language.ts';
import { Rich } from '../../i18n/RichText.tsx';
import { t } from '../../i18n/dict.ts';
import {
  DISPLAY_STATUS_LABEL_KEY,
  RENDER_MERGE_WINDOW_MS,
  SHOW_RENDER_COUNTER,
  ZONE_BOARD_REFRESH_MS,
  describeScope,
  isFullScope,
  playScenario,
  store,
  type DisplayStatus,
} from '../data/index.ts';
import { useEntities, useRenderRate, useRole, useRoleRefresh, useZoneSummary } from '../data/hooks.ts';
import { PendingSource } from '../../shared/PendingSource.tsx';
import { useZoneId } from '../../shared/registry.ts';
import { useScenarioCast } from '../../shared/renderMode.ts';
import { DeviceCard } from './DeviceCard.tsx';
import { UnregisteredCard } from './UnregisteredCard.tsx';
import { Explain } from '../../shared/Explain.tsx';

const STATUS_ORDER: DisplayStatus[] = ['normal', 'fault', 'unknown', 'not_deployed'];

/** 시나리오 버튼 — 상태 전이를 손으로 재생해야 화면이 전이 순간에 맞는지 볼 수 있다. */
const SCENARIO_BUTTONS: Array<{ name: string; labelKey: string }> = [
  { name: 'camera-silence', labelKey: 'dg.1' },
  { name: 'camera-resume', labelKey: 'dg.2' },
  { name: 'sensor-offline', labelKey: 'dg.3' },
  { name: 'sensor-surge', labelKey: 'dg.4' },
  { name: 'robot-idle', labelKey: 'dg.5' },
  { name: 'robot-mission', labelKey: 'dg.6' },
];

export function DeviceGrid() {
  useLang();
  // 구역은 연결 설정에서 온다 — 바뀌면 다시 그린다 (260921). **아래 훅들보다 먼저 읽는다**:
  // `useZoneSummary(ZONE_ID)` 가 이 값을 인자로 받는다.
  const ZONE_ID = useZoneId();
  // 데이터 레이어 기동은 App이 앱 수명 단위로 한다 — 탭을 옮길 때마다 구독을
  // 끊었다 붙이면 돌아왔을 때 화면이 비고, 서버 스냅샷을 매번 다시 받게 된다.
  const entities = useEntities();
  // 대본 재생 중인가 — 카드 단위 분기(대본 등장 장비만 그린다)의 근거 (260831).
  const scenarioCast = useScenarioCast();
  const summary = useZoneSummary(ZONE_ID);
  const role = useRole();
  const refreshRole = useRoleRefresh();
  const renders = useRenderRate();

  const registry = store.getRegistry();
  const registryError = store.getRegistryError();
  const zone = registry?.zones.find((z) => z.id === ZONE_ID) ?? null;

  // 레지스트리 순서를 따른다 — 값이 오는 순서에 카드가 흔들리면 눈으로 못 쫓는다.
  // 미배포처럼 값이 한 번도 안 온 대상도 목록에 있으므로 카드가 나온다.
  const records = [...entities.values()]
    .filter((r) => r.registry?.zone === ZONE_ID)
    .sort((a, b) => a.id.localeCompare(b.id));

  /**
   * **값은 왔는데 레지스트리에 없는 개체** (260921 · 관문 C-a).
   *
   * 위 `records` 는 레지스트리 구역으로 거르므로 이들이 통째로 빠진다 — 저장소는 받아
   * 두는데(`DataStore.apply`) 화면에만 없는 상태다. 디버깅 도구라 **보여줄 수 있는 값은
   * 다 보여준다**: 봉투가 한 건이라도 온 것만 모아 따로 구획으로 그린다.
   *
   * `envelopeCount > 0` 으로 거르는 이유는, 레지스트리가 아직 안 왔을 때 만들어진 빈
   * 기록이 섞이면 「값이 왔다」는 이 구획의 뜻이 흐려지기 때문이다.
   */
  const strays = [...entities.values()]
    .filter((r) => r.registry === null && r.envelopeCount > 0)
    .sort((a, b) => a.id.localeCompare(b.id));

  return (
    <main className="board">
      <header className="board__head">
        <div>
          <h1 className="board__title">{t('dg.boardTitle', { zone: zone?.display_name ?? ZONE_ID })}</h1>
          <Explain id="grid-1" className="board__sub">
            {t('dg.boardSub')}
          </Explain>
        </div>
        <div className="board__meta">
          <span>{t('dg.boardMeta', { sec: ZONE_BOARD_REFRESH_MS / 1000, ms: RENDER_MERGE_WINDOW_MS })}</span>
        </div>
      </header>

      {registryError !== null && (
        <p className="notice notice--warn">
          {t('dg.registryFailed', { reason: registryError })}
        </p>
      )}

      {/* 구역 요약 — 시나리오 모드에서는 **cast 기준 집계**다 (260831 요구 2).
          상태 4종 집계는 남이 줄 데이터(A)라 대본 중에도 지어내지 않고, 지금 화면이
          「대본 장비 몇 · 자리표시 몇」인지를 센다 — 이건 화면 자신의 사실이다. */}
      {scenarioCast !== null ? (
        <section className="summary">
          <div className="summary__item summary__item--normal">
            <span className="summary__count">{records.filter((r) => scenarioCast.has(r.id)).length}</span>
            <span className="summary__label">{t('dg.7')}</span>
          </div>
          <div className="summary__item summary__item--unknown">
            <span className="summary__count">{records.filter((r) => !scenarioCast.has(r.id)).length}</span>
            <span className="summary__label">{t('dg.8')}</span>
          </div>
          <div className="summary__item summary__item--total">
            <span className="summary__count">{records.length}</span>
            <span className="summary__label">{t('dg.9')}</span>
          </div>
        </section>
      ) : (
        <PendingSource id="zone-summary" minHeight={92}>
          <section className="summary">
            {STATUS_ORDER.map((s) => (
              <div key={s} className={'summary__item summary__item--' + s}>
                <span className="summary__count">{summary.counts[s]}</span>
                <span className="summary__label">{t(DISPLAY_STATUS_LABEL_KEY[s])}</span>
              </div>
            ))}
            <div className="summary__item summary__item--total">
              <span className="summary__count">{summary.total}</span>
              <span className="summary__label">{t('dg.9')}</span>
            </div>
          </section>
        </PendingSource>
      )}

      {/* 카드 그리드 자리 전체. 대상 목록(VZ-I-03)과 그 상태(VZ-I-01)가 둘 다 남에게서 온다.
          scenario 모드에서는 **카드 단위로 갈린다** — 대본 등장 장비만 그리고, 나머지는
          여전히 자리표시다. 그래야 「대본이 준 값」과 「아직 아무도 안 준 자리」가 갈린다. */}
      {scenarioCast !== null ? (
        <section className="grid">
          {records.map((r) => scenarioCast.has(r.id)
            ? <div key={r.id} className="scenario-card"><DeviceCard record={r} /></div>
            : <div key={r.id} className="scenario-card scenario-card--offcast"><b>{r.id}</b><span className="scenario-card__note">{t('dg.10')}</span><PendingSource id="device-cards" entity={r.id} inline /></div>)}
        </section>
      ) : (
        <PendingSource id="device-cards" minHeight={320}>
          <section className="grid">
            {records.map((r) => (
              <DeviceCard key={r.id} record={r} />
            ))}
            {records.length === 0 && <p className="notice">{t('dg.11')}</p>}
          </section>
        </PendingSource>
      )}

      {/* 레지스트리 밖 개체. **비어 있으면 아예 안 그린다** — 평소에는 없는 것이 정상이고,
          빈 구획이 늘 떠 있으면 진짜로 하나 생겼을 때 눈에 안 들어온다. */}
      {strays.length > 0 && (
        <section className="stray">
          <h2 className="stray__title">
            {t('dg.stray.title')}
            <span className="stray__count">{t('dg.stray.count', { n: strays.length })}</span>
          </h2>
          <Explain id="grid-stray" className="stray__sub">{t('dg.stray.sub')}</Explain>
          <div className="grid">
            {strays.map((r) => <UnregisteredCard key={r.id} record={r} />)}
          </div>
        </section>
      )}

      <MappingTable records={records} />

      <section className="devpanel">
        <h2 className="devpanel__title">{t('dg.12')}</h2>
        <div className="devpanel__row">
          {SCENARIO_BUTTONS.map((b) => (
            <button key={b.name} type="button" className="btn" onClick={() => playScenario(b.name)}>
              {t(b.labelKey)}
            </button>
          ))}
        </div>

        <h2 className="devpanel__title">{t('dg.13')}</h2>
        <div className="devpanel__row devpanel__row--info">
          {/* VZ-C-04 — **자리 확보가 아니라 실사용이다.** 범위가 실제 값으로 내려온다. */}
          <PendingSource id="role-scope" inline>
            <span className={'chip' + (isFullScope(role) ? '' : ' chip--scoped')}>
              {t('dg.role', { name: role?.display_name ?? t('dg.14'), scope: describeScope(role) })}
              {role !== null && <em> (VZ-C-04 · {role.source})</em>}
            </span>
          </PendingSource>
          <button type="button" className="btn btn--tiny" onClick={refreshRole}>
            {t('dg.refreshRole')} <em>{t('dg.15')}</em>
          </button>
          <span className="chip">
            <Rich id="dg.scopeAll" /> <em>{t('dg.16')}</em>
          </span>
        </div>
        <Explain id="grid-2" className="note note--dim">
          <Rich id="dg.scopeNote" />
        </Explain>

        {SHOW_RENDER_COUNTER && (
          <p className="devpanel__metrics">
            {t('dg.renderMetrics', {
              perSec: renders.perSecond,
              total: renders.total,
              received: store.merge.stats().received,
              flushed: store.merge.stats().flushed,
              immediate: store.merge.stats().immediate,
            })}
          </p>
        )}
      </section>
    </main>
  );
}

/**
 * 목업 오른쪽 매핑표. 지금 화면에 있는 대상이 어느 행에 해당하는지 함께 보여 준다 —
 * "왜 이 카드가 장애인가"를 표로 되짚을 수 있어야 조합 규칙이 검증된다.
 */
function MappingTable({ records }: { records: Array<{ id: string; state: { payload: unknown } | null }> }) {
  useLang();
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
      <h2 className="mapping__title">{t('dg.19')}</h2>
      <table className="mapping__table">
        <thead>
          <tr>
            <th>device_status</th>
            <th>availability</th>
            <th>deployment</th>
            <th>{t('dg.20')}</th>
            <th>{t('dg.21')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              <td>{row.dev}</td>
              <td>{row.avail}</td>
              <td>{row.dep}</td>
              <td>
                <span className={'badge badge--' + row.display}>{t(DISPLAY_STATUS_LABEL_KEY[row.display])}</span>
              </td>
              <td className="mapping__ids">{idsByRow[i].join(', ') || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mapping__note">
        <Rich id="dg.mappingNote" />
      </p>
    </section>
  );
}
