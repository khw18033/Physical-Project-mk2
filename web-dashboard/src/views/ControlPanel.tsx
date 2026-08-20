/**
 * src/views/ControlPanel.tsx
 *
 * VZ-O-01 · VZ-O-02 · VZ-O-05 · VZ-I-05 — 제어 패널.
 *
 * 목업의 세 칸을 그대로 옮긴다 — 제어 / 명령 진행 / 마지막 조작자.
 *
 * 화면이 하지 않는 것.
 *  - 만료 판정 — 서버가 서버 시각으로 한다. 화면은 만료 시각을 붙여 보내기만 한다.
 *  - 확정 판정 — 백엔드가 승격한 `completed`를 따른다. 액션별 규칙을 프런트가 떠안지 않는다.
 *  - 잠금 강제 — 화면 차단은 사용자 편의이고 실제 차단은 서버가 한다. 둘 다 있어야 한다.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  COMMAND_DISPLAY_LABEL,
  COMMAND_TTL_MS,
  commandTracker,
  fetchActions,
  fetchAuditTrail,
  type AuditEntry,
  type TrackedCommand,
} from '../data/index.ts';
import { useCommands, useEntities } from '../data/hooks.ts';
import type { ActionSpec, ControlLock } from '../transport/index.ts';

/** 이번 범위에서 제어 대상은 수문 하나다. 대상이 늘면 레지스트리에서 고르게 된다. */
const TARGET = 'actuator-01';

const STAGE_LABEL: Record<string, string> = {
  ack: '수신 확인 — 디바이스 ACK',
  executing: '수행 중',
  physical_state_changed: '물리 상태 변화',
  settled: '완료 / 실패 확정',
};

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
  const entities = useEntities();
  const commands = useCommands();

  const record = entities.get(TARGET) ?? null;
  const lock = (record?.controlLock?.payload as ControlLock | undefined) ?? null;
  const actuator = record?.actuator?.payload ?? null;

  const [actions, setActions] = useState<ActionSpec[]>([]);
  const [sending, setSending] = useState(false);
  /** 만료 검증용 — 이미 만료된 명령을 일부러 보내 본다. */
  const [forceExpired, setForceExpired] = useState(false);

  useEffect(() => {
    void fetchActions(TARGET).then(setActions);
  }, []);

  const latest = commands.find((c) => c.entity === TARGET) ?? null;
  const locked = lock?.locked ?? false;

  const issue = useCallback(
    async (spec: ActionSpec) => {
      setSending(true);
      try {
        // 만료 검증 모드에서는 **이미 지난** 만료 시각을 붙여 보낸다.
        // 서버가 실제로 거부하는지 확인하기 위한 것으로, 판정은 여전히 서버가 한다.
        await commandTracker.issue(TARGET, spec, { ttlMs: forceExpired ? -5_000 : COMMAND_TTL_MS });
      } finally {
        setSending(false);
      }
    },
    [forceExpired],
  );

  return (
    <main className="board">
      <header className="board__head">
        <div>
          <h1 className="board__title">제어 패널 — 명령 3상태와 책임소재</h1>
          <p className="board__sub">
            되돌리기 어려운 명령은 ACK가 아니라 수행 결과(완료)로 확정 표시하고, 마지막 조작자를 함께 보여준다
          </p>
        </div>
        <div className="board__meta">
          <span>VZ-O-01 · VZ-O-02 · VZ-O-05 · VZ-I-05</span>
        </div>
      </header>

      <div className="cols cols--3">
        {/* ── 1. 제어 (VZ-O-01 / VZ-O-05) ───────────────────────────────── */}
        <section className="panel">
          <header className="panel__head">
            <h2 className="panel__title">{record?.registry?.display_name ?? TARGET} · 수문 제어</h2>
            <span className="panel__tag">VZ-O-01</span>
          </header>

          {locked && (
            <div className="lockbar">
              <strong>제어 잠금</strong>
              <span>{lock?.reason}</span>
              <span className="lockbar__meta">
                {lock?.phase === 'rechecking' ? '복구 후 재확인 중' : '통신 두절'}
                {lock?.safe_state_held === true && ' · 안전 상태 유지'}
              </span>
            </div>
          )}

          <div className="btnrow">
            {actions.map((spec) => (
              <button
                key={spec.action}
                type="button"
                className={'btn btn--action' + (spec.action.startsWith('open') ? ' btn--danger' : '')}
                disabled={locked || sending}
                onClick={() => void issue(spec)}
              >
                {spec.label}
              </button>
            ))}
            {actions.length === 0 && <p className="muted">액션 카탈로그를 받지 못했다.</p>}
          </div>

          <dl className="kv">
            <dt>현재 상태</dt>
            <dd>
              <strong>{actuator === null ? '—' : actuator.position_pct === 100 ? 'open' : actuator.position_pct === 0 ? 'closed' : '개도 ' + actuator.position_pct + '%'}</strong>
            </dd>
            <dt>발행 형태</dt>
            <dd>
              <code>action={actions[0]?.action ?? '—'}</code>
            </dd>
            <dt>동봉 필드</dt>
            <dd className="muted">
              <code>command_id</code> / <code>expires_at</code> / 감사 필드
            </dd>
          </dl>

          <p className="note">
            가시화는 <strong>추상 action까지만</strong> 발행한다. 디바이스 명령(<code>levee:open</code>)으로의 번역은
            백엔드가 어휘집으로 수행한다.
            {actions.some((a) => a.irreversible) && (
              <>
                {' '}
                이 액션들은 <strong>되돌리기 어려움</strong>으로 선언되어 ACK가 아니라 수행 결과로 확정한다.
              </>
            )}
          </p>

          <label className="check">
            <input type="checkbox" checked={forceExpired} onChange={(e) => setForceExpired(e.target.checked)} />
            만료된 명령 보내보기 <em>(expires_at을 과거로 — 서버가 거부하는지 확인)</em>
          </label>
        </section>

        {/* ── 2. 명령 진행 (VZ-O-02) ────────────────────────────────────── */}
        <section className="panel">
          <header className="panel__head">
            <h2 className="panel__title">명령 진행 — 발행에서 확정까지</h2>
            <span className="panel__tag">VZ-O-02</span>
          </header>

          {latest === null ? (
            <p className="muted">아직 발행한 명령이 없다. 왼쪽에서 명령을 눌러 보라.</p>
          ) : (
            <CommandTimeline command={latest} />
          )}

          <p className="note">
            프론트는 <strong>진행중 · 확정 · 실패</strong> 3상태만 그린다. ACK를 확정으로 취급하면 화면과 현실이
            어긋난다.
          </p>
        </section>

        {/* ── 3. 마지막 조작자 (VZ-I-05) ───────────────────────────────── */}
        <LastOperatorPanel entity={TARGET} refreshKey={latest?.stages.length ?? 0} />
      </div>

      <p className="footnote">
        감사 조회는 <strong>패널 열람 시점에만</strong> 질의한다. 진행 중 명령의 상태 변화는 결과 푸시로 이미
        도달하므로 주기 폴링은 중복이다.
      </p>
    </main>
  );
}

/** 네 단계 이력. store는 마지막 값만 갖지만 추적기가 단계를 모두 들고 있다. */
function CommandTimeline({ command }: { command: TrackedCommand }) {
  return (
    <>
      <div className="cmdhead">
        <span className={'badge badge--cmd-' + command.display}>{COMMAND_DISPLAY_LABEL[command.display]}</span>
        <code className="cmdhead__id">{command.commandId}</code>
        {command.progressPct !== null && command.display === 'in_progress' && (
          <span className="progress">
            <span className="progress__bar" style={{ width: command.progressPct + '%' }} />
            <span className="progress__pct">{command.progressPct}%</span>
          </span>
        )}
      </div>

      <ol className="timeline">
        <li className="timeline__row timeline__row--issued">
          <span className="timeline__dot" />
          <div>
            <strong>발행</strong> — 가시화 → 백엔드 (감사 필드 동봉)
            <div className="timeline__sub">
              만료 <code>{timeOf(command.expiresAt)}</code> · 화면: 버튼 비활성
            </div>
          </div>
        </li>

        {command.stages.map((s, i) => (
          <li key={i} className={'timeline__row timeline__row--' + s.status}>
            <span className="timeline__dot" />
            <div>
              <strong>{STAGE_LABEL[s.stage] ?? s.stage}</strong>
              <div className="timeline__sub">
                {s.detail}
                {s.progressPct !== null && ' · ' + s.progressPct + '%'}
                {s.reasonCode !== null && ' · 사유코드 ' + s.reasonCode}
              </div>
            </div>
            <time className="timeline__time">{timeOf(s.ts)}</time>
          </li>
        ))}
      </ol>

      {command.display === 'failed' && (
        <div className="failbox">
          <strong>실패</strong> — {command.lastDetail}
          {command.restored && <div className="failbox__sub">이전 상태로 복원됨. 화면과 현실이 어긋나지 않는다.</div>}
        </div>
      )}
    </>
  );
}

/**
 * VZ-I-05 — 마지막 조작자.
 * **열 때만 조회한다.** 아래 useEffect에 인터벌이 없는 것이 요구사항 그 자체다.
 * 감사 필드 이름은 여기 없다 — auditFieldMap이 만든 표시행만 늘어놓는다.
 */
function LastOperatorPanel({ entity, refreshKey }: { entity: string; refreshKey: number }) {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [queryCount, setQueryCount] = useState<number | null>(null);
  const [open, setOpen] = useState(true);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    void fetchAuditTrail(entity, 5).then((r) => {
      if (!alive) return;
      setEntries(r.entries);
      setError(r.error);
      setQueryCount(r.serverQueryCount);
    });
    return () => {
      alive = false;
    };
    // refreshKey — 명령 단계가 늘면 한 번 더 읽는다. 주기가 아니라 **이벤트**다.
  }, [entity, open, refreshKey]);

  const last = entries[0] ?? null;

  return (
    <section className="panel">
      <header className="panel__head">
        <h2 className="panel__title">마지막 조작자</h2>
        <span className="panel__tag">VZ-I-05</span>
      </header>

      <button type="button" className="btn btn--small" onClick={() => setOpen((v) => !v)}>
        {open ? '패널 닫기' : '패널 열기 (열 때 1회 조회)'}
      </button>

      {!open && <p className="muted">닫힌 동안에는 조회하지 않는다.</p>}

      {open && error !== null && <p className="notice notice--warn">{error}</p>}

      {open && last === null && error === null && (
        <p className="muted">조작 이력이 없다. 명령을 한 번 발행하면 기록이 생긴다.</p>
      )}

      {open && last !== null && (
        <>
          <div className="actor">
            <strong className="actor__name">{last.actorName ?? '미기록'}</strong>
            {last.actorRole !== null && <span className="chip">{last.actorRole}</span>}
          </div>

          <dl className="kv">
            <dt>시각</dt>
            <dd>
              <strong>{last.occurredAt === null ? '—' : timeOf(last.occurredAt)}</strong>
            </dd>
            {last.rows.map((row, i) => (
              <FragmentRow key={i} label={row.label} value={row.value} muted={row.muted} />
            ))}
          </dl>

          <p className="note note--dim">
            <code>command_id</code> · {last.commandId ?? '—'}
            <br />
            기록 작성 — {last.writtenBy ?? '—'}
            <br />
            조작자·시각은 토큰·서버 시각에서 주입
          </p>

          {queryCount !== null && (
            <p className="note note--dim">서버 누적 감사 조회 {queryCount}회 (주기 폴링이 없으면 늘지 않는다)</p>
          )}
        </>
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
