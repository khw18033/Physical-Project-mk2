// 이식: web-dashboard/src/views/ControlPanel.tsx @ 700ed91 — 무수정 (transport 경로만 조정)
/**
 * src/views/ControlPanel.tsx
 *
 * VZ-O-01 · VZ-O-02 · VZ-O-05 · VZ-C-04 · VZ-I-05 — 제어 패널.
 *
 * 목업의 세 칸을 그대로 옮긴다 — 제어 / 명령 진행 / 마지막 조작자.
 *
 * 화면이 하지 않는 것.
 *  - 만료 판정 — 서버가 서버 시각으로 한다. 화면은 만료 시각을 붙여 보내기만 한다.
 *  - 확정 판정 — 백엔드가 승격한 `completed`를 따른다. 액션별 규칙을 프런트가 떠안지 않는다.
 *  - 잠금 강제 — 화면 차단은 사용자 편의이고 실제 차단은 서버가 한다. 둘 다 있어야 한다.
 *  - **키 관리** — 요청 식별자와 상관 키를 화면이 다루지 않는다. 데이터 레이어가 주는
 *    "이 요청의 현재 상태" 하나만 그린다. 아래 코드에 상관 키 **값**을 읽거나 조립하는
 *    곳이 없는 것이 그 증거다 — 표시할 키는 `tracking.value`로 이미 만들어져 오고,
 *    감사 조회 키도 데이터 레이어가 꺼낸다.
 *    (`'command_id'` 문자열이 아래에 두 번 나오지만 그건 키 값이 아니라 **서버가 무엇으로
 *    조회했는지 알려 주는 종류 태그**다. 키를 다루는 것과는 다른 일이다.)
 */

import { useLang } from '../../shared/language.ts';
import { Rich } from '../../i18n/RichText.tsx';
import { t } from '../../i18n/dict.ts';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { PendingSource } from '../../shared/PendingSource.tsx';
import {
  COMMAND_DISPLAY_LABEL_KEY,
  COMMAND_STAGE_LABEL_KEY,
  COMMAND_TTL_MS,
  commandTracker,
  describeScope,
  fetchActions,
  fetchAuditTrail,
  playScenario,
  store,
  type AuditQueryResult,
  type ControlGate,
  type TrackedCommand,
} from '../data/index.ts';
import { useCommands, useControlGate, useEntities, useRole, useRoleRefresh } from '../data/hooks.ts';
import { useScenarioCast } from '../../shared/renderMode.ts';
import type { ActionSpec } from '../../transport/index.ts';
import { Explain } from '../../shared/Explain.tsx';

/** 제어 대상 후보. 둘째는 **다른 구역**에 있어 권한 범위 검증에 쓰인다(VZ-C-04). */
const TARGETS = ['actuator-01', 'actuator-02'] as const;

/** ACK 없이 만료되는 것을 보려면 30초를 기다릴 수 없으므로 짧은 TTL을 쓴다. */
const SHORT_TTL_MS = 6_000;

/** 단계 표기는 `shared/commandCenter.ts` 하나에 있다 — 캔버스의 제어 뷰 노드가 같은 것을 그린다. */
const STAGE_LABEL = COMMAND_STAGE_LABEL_KEY;

function timeOf(iso: string): string {
  // 서버가 보낸 시각을 표시만 한다. 이 값으로 판정하지 않는다.
  const d = new Date(iso);
  return (
    String(d.getHours()).padStart(2, '0') + ':' +
    String(d.getMinutes()).padStart(2, '0') + ':' +
    String(d.getSeconds()).padStart(2, '0') + '.' +
    String(Math.floor(d.getMilliseconds() / 100))
  );
}

export function ControlPanel() {
  useLang();
  const entities = useEntities();
  const commands = useCommands();
  const role = useRole();
  const refreshRole = useRoleRefresh();

  // 시나리오 모드 — 제어 대상을 **대본 cast 로 좁힌다** (260831 요구 2).
  // cast 에 액추에이터가 없으면(1·2편) 대상이 비고, 제어 자리들은 axis="actuator" 로
  // 「이 대본에는 해당 없음」이 된다. 3편은 현행대로 대본 명령이 실제 엔진을 통과한다.
  const scenarioCast = useScenarioCast();
  const targets: string[] = scenarioCast === null ? [...TARGETS] : TARGETS.filter((id) => scenarioCast.has(id));

  const [target, setTarget] = useState<string>(TARGETS[0]);
  useEffect(() => {
    if (targets.length > 0 && !targets.includes(target)) setTarget(targets[0]);
  }, [scenarioCast]);
  const [actions, setActions] = useState<ActionSpec[]>([]);
  /** 만료 검증용 — 이미 만료된 명령을 일부러 보내 본다. */
  const [forceExpired, setForceExpired] = useState(false);
  /** ACK 미도착 검증용 — 목 서버가 ACK를 보내지 않게 하고 짧은 TTL로 발행한다. */
  const [dropAck, setDropAck] = useState(false);

  const record = entities.get(target) ?? null;
  const gate = useControlGate(target);
  const latest = commands.find((c) => c.entity === target) ?? null;

  useEffect(() => {
    void fetchActions(target).then(setActions);
  }, [target]);

  /**
   * 발행 직후 버튼을 잠그는 근거는 **추적기의 상태**다.
   * `await`가 끝나기를 기다리는 로컬 플래그로 잠그면 ACK가 늦을 때 버튼이 먼저 풀린다 —
   * 이번 계약에서는 ACK가 늦게 올 수 있으므로 그 방식이 실제로 깨진다.
   */
  const inFlight = latest !== null && latest.display === 'in_progress' && !latest.settled;

  const issue = useCallback(
    async (spec: ActionSpec, options: { bypassUiLock?: boolean } = {}) => {
      if (dropAck) {
        // 목 서버가 다음 1건의 ACK를 보내지 않게 한다. 실제 게이트웨이에는 없는 경로다.
        playScenario('ack-drop');
      }
      await commandTracker.issue(target, spec, {
        // 만료 검증 모드에서는 **이미 지난** 만료 시각을 붙여 보낸다.
        // 서버가 실제로 거부하는지 확인하기 위한 것으로, 판정은 여전히 서버가 한다.
        ttlMs: forceExpired ? -5_000 : dropAck ? SHORT_TTL_MS : COMMAND_TTL_MS,
        inputMode: options.bypassUiLock === true ? 'api' : 'click',
      });
    },
    [target, forceExpired, dropAck],
  );

  return (
    <main className="board">
      <header className="board__head">
        <div>
          <h1 className="board__title">{t('cp.1')}</h1>
          <Explain id="ctl-1" className="board__sub">
            <Rich id="cp.sub" />
          </Explain>
        </div>
        <div className="board__meta">
          <span>VZ-O-01 · VZ-O-02 · VZ-O-05 · VZ-C-04 · VZ-I-05</span>
        </div>
      </header>

      <section className="targetbar">
        <span className="targetbar__label">{t('cp.3')}</span>
        {/* 대상 목록과 표시 이름은 레지스트리에서 온다 (VZ-I-03). 버튼 자체는 우리 것이다. */}
        <PendingSource id="registry" inline />
        {targets.map((id) => (
          <button
            key={id}
            type="button"
            className={'btn btn--small' + (target === id ? ' btn--on' : '')}
            onClick={() => setTarget(id)}
          >
            {store.getRegistry()?.entities.find((e) => e.id === id)?.display_name ?? id}
          </button>
        ))}
        {targets.length === 0 && <span className="muted">{t('cp.4')}</span>}
        <span className="targetbar__role">
          {t('cp.rolePrefix')} <strong>{role?.display_name ?? t('cp.5')}</strong> · {describeScope(role)}
          <button type="button" className="btn btn--tiny" onClick={refreshRole}>
            {t('cp.refreshRole')} <em>{t('cp.6')}</em>
          </button>
        </span>
      </section>

      <div className="cols cols--3">
        {/* ── 1. 제어 (VZ-O-01 / VZ-O-05 / VZ-C-04) ─────────────────────── */}
        <section className="panel">
          <header className="panel__head">
            <h2 className="panel__title">{t('cp.gateControl', { name: record?.registry?.display_name ?? target })}</h2>
            <span className="panel__tag">VZ-O-01</span>
          </header>

          <ControlGateBar gate={gate} />

          <PendingSource id="action-catalog" minHeight={52} entity={target} axis="actuator">
          <div className="btnrow">
            {actions.map((spec) => (
              <button
                key={spec.action}
                type="button"
                className={'btn btn--action' + (spec.action.startsWith('open') ? ' btn--danger' : '')}
                // 잠금 사유가 하나라도 있으면 잠근다. 진행 중에도 잠근다 —
                // **ACK를 기다리지 않고** 발행 직후부터 잠기는 것이 요구사항이다.
                disabled={gate.locked || inFlight}
                onClick={() => void issue(spec)}
              >
                {spec.label}
              </button>
            ))}
            {actions.length === 0 && <p className="muted">{t('cp.7')}</p>}
          </div>
          </PendingSource>

          {inFlight && (
            <p className="notice notice--busy">
              <span className="spinner" aria-hidden="true" />
              {t('cp.issued', { how: latest?.tracking.linked === true ? t('cp.8') : t('cp.9') })}
            </p>
          )}

          <dl className="kv">
            <dt>{t('cp.10')}</dt>
            <dd>
              <PendingSource id="actuator-state" inline entity={target} axis="actuator">
                <strong>{describePosition(record?.actuator?.payload?.position_pct ?? null)}</strong>
              </PendingSource>
            </dd>
            <dt>{t('cp.11')}</dt>
            <dd>
              <code>action={actions[0]?.action ?? '—'}</code>
            </dd>
            <dt>{t('cp.12')}</dt>
            <dd className="muted">
              <Rich id="cp.auditFields" />
              <br />
              <em>{t('cp.13')}</em>
            </dd>
          </dl>

          <Explain id="ctl-2" className="note">
            <Rich id="cp.abstractAction" />
            {actions.some((a) => a.irreversible) && (
              <>
                {' '}
                <Rich id="cp.irreversible" />
              </>
            )}
          </Explain>

          <div className="devpanel devpanel--inline">
            <h3 className="devpanel__title">{t('cp.15')}</h3>

            <label className="check">
              <input type="checkbox" checked={forceExpired} onChange={(e) => setForceExpired(e.target.checked)} />
              {t('cp.sendExpired')} <em>{t('cp.16')}</em>
            </label>

            <label className="check">
              <input type="checkbox" checked={dropAck} onChange={(e) => setDropAck(e.target.checked)} />
              {t('cp.expireNoAck')} <em>{t('cp.expireNoAckNote', { sec: SHORT_TTL_MS / 1000 })}</em>
            </label>

            <div className="devpanel__row">
              <button type="button" className="btn btn--small" onClick={() => playScenario('ack-late')}>
                {t('cp.btn.ackLate')}
              </button>
              <button type="button" className="btn btn--small" onClick={() => playScenario('command-fail')}>
                {t('cp.btn.commandFail')}
              </button>
              <button type="button" className="btn btn--small" onClick={() => playScenario('control-lock')}>
                {t('cp.btn.controlLock')}
              </button>
              <button type="button" className="btn btn--small" onClick={() => playScenario('control-unlock')}>
                {t('cp.btn.controlUnlock')}
              </button>
            </div>

            {/*
              전송 아키텍처 문서 대조 결과 — Kafka 지연 10~50ms에 브릿지 전환이 한 겹 더 붙고
              왕복이니 두 번 겪는다. 즉시 ACK를 전제로 정한 expires_at 기본값과 만료 임계가
              실제 경로에서 견디는지, 실물 백엔드에 붙기 전에 여기서 확인한다.
            */}
            <div className="devpanel__row">
              <button
                type="button"
                className="btn btn--small btn--probe"
                onClick={() => playScenario('command-roundtrip-slow')}
              >
                {t('cp.btn.slowRoundtrip')}
              </button>
              <button
                type="button"
                className="btn btn--small"
                onClick={() => playScenario('command-roundtrip-zero')}
              >
                {t('cp.btn.zeroRoundtrip')}
              </button>
              <button
                type="button"
                className="btn btn--small"
                onClick={() => playScenario('cache-policy-audit')}
              >
                {t('cp.btn.cacheAudit')}
              </button>
            </div>

            <div className="devpanel__row">
              <button type="button" className="btn btn--small" onClick={() => { playScenario('role-narrow'); }}>
                {t('cp.btn.roleNarrow')}
              </button>
              <button type="button" className="btn btn--small" onClick={() => { playScenario('role-full'); }}>
                {t('cp.btn.roleFull')}
              </button>
              <button
                type="button"
                className="btn btn--small btn--probe"
                // **화면 잠금을 우회한다.** 화면 차단이 방어선이 아니라는 것을 보이기 위한 경로로,
                // 서버가 out_of_scope로 거부해야 정상이다.
                disabled={actions.length === 0}
                onClick={() => actions[0] && void issue(actions[0], { bypassUiLock: true })}
              >
                {t('cp.bypassLock')} <em>{t('cp.17')}</em>
              </button>
            </div>
            <Explain id="ctl-3" className="note note--dim">
              <Rich id="cp.roleNote" />
            </Explain>
          </div>
        </section>

        {/* ── 2. 명령 진행 (VZ-O-02) ────────────────────────────────────── */}
        <section className="panel">
          <header className="panel__head">
            <h2 className="panel__title">{t('cp.19')}</h2>
            <span className="panel__tag">VZ-O-02</span>
          </header>

          {/* scenario 모드: 대본의 명령(3편 close/open_gate)이 이 엔진 이력에 4단계로 뜬다.
              발행 주체는 감사에 「임무 MSN-…」로 남는다 — 사람이 누른 것이 아니다. */}
          <PendingSource id="command-result" minHeight={180} entity={target} axis="command">
            {latest === null ? (
              <p className="muted">{t('cp.20')}</p>
            ) : (
              <CommandTimeline command={latest} />
            )}
          </PendingSource>

          <Explain id="ctl-4" className="note">
            <Rich id="cp.threeStates" />
          </Explain>
        </section>

        {/* ── 3. 마지막 조작자 (VZ-I-05) ───────────────────────────────── */}
        <LastOperatorPanel entity={target} command={latest} refreshKey={latest?.stages.length ?? 0} />
      </div>

      <p className="footnote">
        <Rich id="cp.auditNote" />
      </p>
    </main>
  );
}

function describePosition(pct: number | null): string {
  if (pct === null) return '—';
  if (pct === 100) return 'open';
  if (pct === 0) return 'closed';
  return t('cp.openPct', { pct });
}

/**
 * VZ-O-05 + VZ-C-04 — 잠금 사유들.
 * **사유가 둘 이상일 수 있다** — 통신 두절과 권한 범위 밖은 동시에 성립한다.
 * 판정은 데이터 레이어가 끝냈고 여기서는 늘어놓기만 한다.
 */
function ControlGateBar({ gate }: { gate: ControlGate }) {
  useLang();
  if (!gate.locked) return null;
  return (
    <div className="lockbar">
      <strong>{t('cp.22')}</strong>
      {gate.reasons.map((r) => (
        <span key={r.kind} className={'lockbar__reason lockbar__reason--' + r.kind}>
          <span className="lockbar__badge">{r.label}</span>
          {r.text}
          {r.meta !== null && <span className="lockbar__meta">{r.meta}</span>}
        </span>
      ))}
    </div>
  );
}

/**
 * 네 단계 이력. store는 마지막 값만 갖지만 추적기가 단계를 모두 들고 있다.
 *
 * 화면은 추적 키를 **한 개**만 본다 — 지금 무엇으로 추적 중인지는 데이터 레이어가
 * 라벨과 값으로 만들어 넘겨 준다.
 */
function CommandTimeline({ command }: { command: TrackedCommand }) {
  useLang();
  return (
    <>
      <div className="cmdhead">
        <span className={'badge badge--cmd-' + command.display}>{t(COMMAND_DISPLAY_LABEL_KEY[command.display])}</span>
        <span className={'trackkey' + (command.tracking.linked ? ' trackkey--linked' : '')}>
          <em>{command.tracking.label}</em>
          <code className="cmdhead__id">{command.tracking.value}</code>
        </span>
        {command.progressPct !== null && command.display === 'in_progress' && (
          <span className="progress">
            <span className="progress__bar" style={{ width: command.progressPct + '%' }} />
            <span className="progress__pct">{command.progressPct}%</span>
          </span>
        )}
      </div>

      {command.absorbedCount > 0 && (
        <p className="notice notice--absorbed">
          <Rich id="cp.absorbed" vars={{ n: command.absorbedCount }} />
        </p>
      )}

      <ol className="timeline">
        {command.stages.map((s, i) => (
          <li
            key={i}
            className={
              'timeline__row timeline__row--' + s.status +
              (s.absorbed === true ? ' timeline__row--absorbed' : '')
            }
          >
            <span className="timeline__dot" />
            <div>
              <strong>{STAGE_LABEL[s.stage] ?? s.stage}</strong>
              {s.absorbed === true && <span className="chip chip--absorbed">{t('cp.23')}</span>}
              <div className="timeline__sub">
                {s.detail}
                {s.progressPct !== null && ' · ' + s.progressPct + '%'}
                {s.reasonCode !== null && t('cp.reasonCode', { code: s.reasonCode })}
              </div>
            </div>
            <time className="timeline__time">{timeOf(s.ts)}</time>
          </li>
        ))}
      </ol>

      <Explain id="ctl-5" className="note note--dim">
        <Rich id="cp.expiryNote" vars={{ at: timeOf(command.expiresAt) }} />
      </Explain>

      {command.display === 'failed' && (
        <div className="failbox">
          <strong>{t('cp.24')}</strong> — {command.lastDetail}
          {command.restored && <div className="failbox__sub">{t('cp.25')}</div>}
        </div>
      )}
    </>
  );
}

/**
 * VZ-I-05 — 마지막 조작자.
 *
 * **열 때만 조회한다.** 아래 useEffect에 인터벌이 없는 것이 요구사항 그 자체다.
 * 조회 키는 **상관 키**이며, 그 키를 꺼내는 일은 데이터 레이어가 한다 —
 * 이 컴포넌트는 "이 요청"을 넘길 뿐 키를 만지지 않는다.
 * 감사 필드 이름도 여기 없다 — auditFieldMap이 만든 표시행만 늘어놓는다.
 */
function LastOperatorPanel({
  entity,
  command,
  refreshKey,
}: {
  entity: string;
  command: TrackedCommand | null;
  refreshKey: number;
}) {
  useLang();
  const [result, setResult] = useState<AuditQueryResult | null>(null);
  const [open, setOpen] = useState(true);

  // 요청 객체 자체가 아니라 식별자에만 반응해야 매 단계마다 조회가 나가지 않는다.
  const requestId = command?.requestId ?? null;

  useEffect(() => {
    if (!open) return;
    let alive = true;
    void fetchAuditTrail({ command, entity }, 5).then((r) => {
      if (alive) setResult(r);
    });
    return () => {
      alive = false;
    };
    // refreshKey — 명령 단계가 늘면 한 번 더 읽는다. 주기가 아니라 **이벤트**다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entity, requestId, open, refreshKey]);

  const entries = result?.entries ?? [];
  const last = entries[0] ?? null;
  const error = result?.error ?? null;

  const queryLabel = useMemo(() => {
    if (result === null) return null;
    if (result.queriedBy === 'command_id') return t('cp.queriedByKey', { key: result.queriedKey ?? '' });
    if (result.queriedBy === 'entity') return t('cp.queriedByEntity', { key: result.queriedKey ?? '' });
    return null;
  }, [result]);

  return (
    <section className="panel">
      <header className="panel__head">
        <h2 className="panel__title">{t('cp.26')}</h2>
        <span className="panel__tag">VZ-I-05</span>
      </header>

      <button type="button" className="btn btn--small" onClick={() => setOpen((v) => !v)}>
        {open ? t('cp.27') : t('cp.28')}
      </button>

      {!open && <p className="muted">{t('cp.29')}</p>}

      {open && queryLabel !== null && (
        <p className={'querykey' + (result?.queriedBy === 'command_id' ? ' querykey--chain' : '')}>{queryLabel}</p>
      )}

      {open && error !== null && <p className="notice notice--warn">{error}</p>}

      {open && last === null && error === null && (
        <p className="muted">{t('cp.30')}</p>
      )}

      {/* 층 3 (260901) — 축을 줬다. 3편에서는 대본 명령이 실제 엔진을 통과하므로 감사에
          값이 차고, 1·2편에서는 이 탭이 패널째 접혀 이 자리가 아예 나오지 않는다.
          축이 없던 8/31까지는 시나리오 중에도 늘 「연결 예정」이라 값이 있어도 안 보였다. */}
      {open && last !== null && (
        <PendingSource id="audit-history" minHeight={150} entity={entity} axis="command">
          <div className="actor">
            <strong className="actor__name">{last.actorName ?? t('cp.31')}</strong>
            {last.actorRole !== null && <span className="chip">{last.actorRole}</span>}
          </div>

          <dl className="kv">
            <dt>{t('cp.32')}</dt>
            <dd>
              <strong>{last.occurredAt === null ? '—' : timeOf(last.occurredAt)}</strong>
            </dd>
            {last.rows.map((row, i) => (
              <FragmentRow key={i} label={row.label} value={row.value} muted={row.muted} />
            ))}
          </dl>

          <Explain id="ctl-6" className="note note--dim">
            {t('cp.correlationKey', { key: last.commandId ?? '—' })}
            <br />
            {t('cp.writtenBy', { who: last.writtenBy ?? '—' })}
            <br />
            {t('cp.injectedFrom')}
          </Explain>

          {result?.serverQueryCount != null && (
            <Explain id="ctl-7" className="note note--dim">
              {t('cp.serverQueryCount', { n: result.serverQueryCount })}
            </Explain>
          )}
        </PendingSource>
      )}
    </section>
  );
}

function FragmentRow({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <>
      <dt>{label}</dt>
      <dd className={muted === true ? 'muted' : undefined}>{value}</dd>
    </>
  );
}
