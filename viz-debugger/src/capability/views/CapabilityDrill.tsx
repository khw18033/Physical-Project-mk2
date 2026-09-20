/**
 * src/capability/views/CapabilityDrill.tsx (260920 신설 — 기능 상태 패널 이식)
 *
 * **기능 › 계층·자원 › 개발자.** 전달본의 탭 셋을 **단계별 세분화**로 옮긴 것이다 —
 * 마일스톤 › 노드 › 액션 아이템과 같은 문법이고, 이동 경로(`crumbs`)도 같은 모양이다.
 *
 * ## 탭이 아니다
 *
 * 탭 바를 그대로 옮기면 `verify:no-tabs` 에 걸린다. 그것은 형식의 문제가 아니라, 상위에서
 * 고른 것이 하위의 조회 범위가 되는 이 화면의 문법(`VZ-N-02` 「연결이 곧 범위」)과 탭이
 * 어긋나기 때문이다. 기능을 고르면 그 기능이 요구하는 kind 만 아래 두 칸에 남는다.
 *
 * ## 규칙은 `VZ-N-05`(확대) 그대로다
 *
 * 오버레이다 · 뒤를 교체하지 않는다 · 동시 하나 · 닫는 길이 둘 이상(닫기 · Esc · 배경).
 *
 * ## 판정을 여기서 다시 하지 않는다
 *
 * `state` 도 `reason_token` 도 서버가 낸 것을 옮기기만 한다. 한 칸만 우리가 센다 —
 * 노드가 **지금 무는 비용의 합**(`usedCost`)이다. 서버가 그 합을 안 주기 때문이고,
 * 고른 provider 의 `cost` 를 더한 것이라 새 값이 아니다.
 */

import { useEffect, useState } from 'react';
import { t } from '../../i18n/dict.ts';
import { useLang, type Lang } from '../../shared/language.ts';
import { capLabel, capReason } from '../labels.ts';
import { useCapability } from '../store.ts';
import type { CapCost, CapFunction, CapLabels, CapNode, CapNodeRow } from '../types.ts';

/** 비용 한 줄. 모르는 칸은 적지 않는다 — 0 으로 적으면 「공짜」라는 없는 사실이 된다. */
function costText(cost: CapCost | null): string | null {
  if (cost === null) return null;
  if (cost.computeUnits === null) return cost.memoryMb === null ? null : t('cap.mem', { mb: cost.memoryMb });
  if (cost.memoryMb === null) return t('cap.cu', { cu: cost.computeUnits });
  return t('cap.cost', { cu: cost.computeUnits, mb: cost.memoryMb });
}

/** 이 노드가 지금 무는 비용 — 고른(`ACTIVE`) provider 들의 합. */
function usedCost(rows: readonly CapNodeRow[]): CapCost {
  let cu = 0;
  let mb = 0;
  for (const row of rows) {
    if (row.state !== 'ACTIVE' || row.cost === null) continue;
    cu += row.cost.computeUnits ?? 0;
    mb += row.cost.memoryMb ?? 0;
  }
  return { computeUnits: cu, memoryMb: mb };
}

function stateClass(state: string): string {
  if (state === 'ACTIVE') return 'ok';
  if (state === 'DEGRADED') return 'warn';
  if (state === 'DISABLED') return 'bad';
  return 'unknown';
}

/** 그 기능이 요구하는 kind — 필수 먼저, 그다음 선택. 순서가 화면의 순서다. */
function kindsOf(fn: CapFunction): readonly { kind: string; required: boolean }[] {
  return [
    ...fn.required.map((row) => ({ kind: row.kind, required: true })),
    ...fn.optional.map((row) => ({ kind: row.kind, required: false })),
  ];
}

function TierStep({ fn, nodes, labels, lang, onNode }: {
  fn: CapFunction; nodes: readonly CapNode[]; labels: CapLabels; lang: Lang; onNode(nodeId: string): void;
}) {
  const kinds = kindsOf(fn);
  const wanted = new Set(kinds.map((entry) => entry.kind));
  return <>
    <div className="cap-strip">
      <b>{t('cap.tier.verdict')}<em className={`cap-chip cap-chip--${stateClass(fn.state)}`}>{capLabel(labels.states, fn.state, lang)}</em></b>
      <span><small>{t('cap.tier.required')}</small><b>{fn.required.length}</b></span>
      <span><small>{t('cap.tier.optional')}</small><b>{fn.optional.length}</b></span>
      <span><small>{t('cap.tier.byRole')}</small><b>{Object.keys(fn.byRole).length === 0 ? '—' : Object.entries(fn.byRole)
        .map(([role, cost]) => `${capLabel(labels.roles, role, lang)} ${costText(cost) ?? '—'}`).join(' · ')}</b></span>
    </div>

    {/* 부족한 kind 가 있으면 계층별 사유를 먼저 적는다 — 「왜 불가인가」가 표 위에 있어야 한다. */}
    {fn.supplement.length > 0 && <ul className="cap-supplement">
      {fn.supplement.map((row) => <li key={`${row.kind}/${row.role}`}>
        <code>{capLabel(labels.capabilityKinds, row.kind, lang)}</code>
        <em>{capLabel(labels.roles, row.role, lang)}</em>
        <span>{capReason(labels.reasons, row.reasonToken, row.reason, lang, row.reasonData) ?? t('cap.noReason')}</span>
      </li>)}
    </ul>}

    <p className="cap-note">{t('cap.tier.note')}</p>
    <div className="cap-table cap-table--tier">
      <div className="cap-table__head">
        <span>{t('cap.tier.head.role')}</span><span>{t('cap.tier.head.node')}</span>
        <span>{t('cap.tier.head.serves')}</span><span>{t('cap.tier.head.budget')}</span><span />
      </div>
      {nodes.map((node) => {
        const mine = node.rows.filter((row) => wanted.has(row.kind));
        const serves = mine.filter((row) => row.state === 'ACTIVE');
        const used = usedCost(node.rows);
        const limit = node.budget;
        const over = limit?.computeUnits !== null && limit?.computeUnits !== undefined
          && (used.computeUnits ?? 0) > limit.computeUnits;
        return <button key={node.nodeId} type="button" className="cap-noderow" onClick={() => onNode(node.nodeId)}>
          <span className="cap-noderow__role">{capLabel(labels.roles, node.role, lang) || t('cap.noRole')}</span>
          <code>{node.nodeId}</code>
          <span className="cap-noderow__serves">
            {serves.length === 0
              ? <em className="cap-chip cap-chip--unknown">{t('cap.tier.none')}</em>
              : serves.map((row) => <em
                key={row.kind}
                className="cap-chip cap-chip--ok"
                title={`${row.kind} ← ${row.providerId ?? '?'}`}
              >{capLabel(labels.capabilityKinds, row.kind, lang)}</em>)}
          </span>
          <span className="cap-noderow__budget">
            <em className={`cap-chip cap-chip--${serves.length === 0 ? 'unknown' : over ? 'bad' : 'ok'}`}>
              {limit === null
                ? costText(used) ?? '—'
                : t('cap.budget', { used: (used.computeUnits ?? 0).toFixed(1), limit: (limit.computeUnits ?? 0).toFixed(1) })}
            </em>
          </span>
          <b aria-hidden="true">›</b>
        </button>;
      })}
    </div>
  </>;
}

function DevStep({ fn, node, labels, lang }: { fn: CapFunction; node: CapNode; labels: CapLabels; lang: Lang }) {
  const kinds = kindsOf(fn);
  const byKind = new Map(node.rows.map((row) => [row.kind, row]));
  const alternatives = kinds
    .flatMap(({ kind }) => (byKind.get(kind)?.alternatives ?? []).map((alt) => ({ kind, alt })));
  /** 고른 provider 가 실제로 어디에 꽂히는지 — 서버가 객체로 주고 파서가 `k=v` 로 이어 붙인다. */
  const selectors = [...new Set(kinds
    .map(({ kind }) => byKind.get(kind)?.nodeSelector)
    .filter((value): value is string => value !== null && value !== undefined))];
  return <div className="cap-dev">
    <div className="cap-dev__main">
      <h3>{t('cap.dev.rows', { fn: capLabel(labels.functions, fn.functionId, lang) })}</h3>
      <div className="cap-table cap-table--dev">
        <div className="cap-table__head">
          <span>capability_kind</span><span>state</span><span>provider</span><span>reason_token</span>
        </div>
        {kinds.map(({ kind, required }) => {
          const row = byKind.get(kind) ?? null;
          return <div key={kind} className="cap-devrow">
            <span>
              <code>{kind}</code>
              <small>{capLabel(labels.capabilityKinds, kind, lang)}</small>
            </span>
            <span>
              <em className={`cap-chip cap-chip--${row === null ? 'unknown' : stateClass(row.state)}`}>
                {row === null ? t('cap.dev.noRow') : capLabel(labels.states, row.state, lang)}
              </em>
              <small>{required ? t('cap.required') : t('cap.optional')}</small>
            </span>
            <span>
              <code>{row?.providerId ?? '—'}</code>
              <small>{(row === null ? null : costText(row.cost))
                ?? (row?.priority === null || row?.priority === undefined ? '' : t('cap.priority', { priority: row.priority }))}</small>
            </span>
            <span>
              <code className="cap-token">{row?.reasonToken ?? row?.reason ?? '—'}</code>
              <small>{row === null ? '' : capReason(labels.reasons, row.reasonToken, row.reason, lang, row.reasonData) ?? ''}</small>
            </span>
          </div>;
        })}
      </div>

      <h3>{t('cap.dev.alt')}</h3>
      {alternatives.length === 0
        ? <p className="cap-note">{t('cap.dev.noAlt')}</p>
        : <div className="cap-alts">
          {alternatives.map(({ kind, alt }) => <div key={`${kind}/${alt.providerId}`} className="cap-alt">
            <div>
              <b><code>{alt.providerId}</code></b>
              <em className="cap-chip cap-chip--plain">{capLabel(labels.capabilityKinds, kind, lang)}</em>
              <code className="cap-token">{alt.reasonToken ?? alt.reason ?? '—'}</code>
            </div>
            <p>{capReason(labels.reasons, alt.reasonToken, alt.reason, lang, alt.reasonData) ?? t('cap.noReason')}</p>
          </div>)}
        </div>}
    </div>

    <aside className="cap-dev__side">
      <h3>{t('cap.dev.whatIsThis')}</h3>
      <p>{t('cap.dev.whatIsThisBody')}</p>
      <p>{t('cap.dev.costIsDemand')}</p>
      <h3>{t('cap.dev.node')}</h3>
      <dl className="cap-dev__facts">
        <dt>role</dt><dd>{node.role === '' ? t('cap.noRole') : `${capLabel(labels.roles, node.role, lang)} (${node.role})`}</dd>
        <dt>tags</dt><dd>{node.tags.length === 0 ? '—' : node.tags.join(' · ')}</dd>
        <dt>budget</dt><dd>{costText(node.budget) ?? '—'}</dd>
        {node.excludeProviders.length > 0 && <><dt>exclude</dt><dd>{node.excludeProviders.join(' · ')}</dd></>}
        {selectors.length > 0 && <><dt>selector</dt><dd>{selectors.join(' / ')}</dd></>}
      </dl>
      {/* 아직 없는 길. **비어 있다는 사실을 적는다** — 빈칸은 「안 만들었다」로 읽힌다. */}
      <h3>{t('cap.dev.device')}</h3>
      <p className="cap-note">{t('cap.dev.deviceNone')}</p>
    </aside>
  </div>;
}

export function CapabilityDrill({ functionId, onClose }: { functionId: string; onClose(): void }) {
  const lang = useLang();
  const cap = useCapability();
  const [nodeId, setNodeId] = useState<string | null>(null);

  // 여는 길이 하나여도 닫는 길은 둘 이상이어야 한다 (`DeviceStatusOverlay` 와 같은 규칙).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const fn = cap.snapshot?.functions.find((entry) => entry.functionId === functionId) ?? null;
  const nodes = cap.snapshot?.nodes ?? [];
  const node = nodeId === null ? null : nodes.find((entry) => entry.nodeId === nodeId) ?? null;
  const fnName = fn === null ? functionId : capLabel(cap.labels.functions, fn.functionId, lang);

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="modal cap-modal" role="dialog" aria-label={t('cap.drill.aria', { fn: fnName })}>
      <header>
        <div>
          <nav className="crumbs" aria-label={t('cap.crumb.aria')}>
            <button type="button" className="crumbs__link" onClick={onClose}>{t('cap.crumb.functions')}</button>
            <span className="crumbs__sep" aria-hidden="true">›</span>
            {node === null
              ? <span className="crumbs__here">{t('cap.crumb.tier')}</span>
              : <button type="button" className="crumbs__link" onClick={() => setNodeId(null)}>{t('cap.crumb.tier')}</button>}
            {node !== null && <>
              <span className="crumbs__sep" aria-hidden="true">›</span>
              <span className="crumbs__here">{t('cap.crumb.dev')}</span>
            </>}
          </nav>
          <h2>{node === null ? t('cap.tier.title', { fn: fnName }) : t('cap.dev.title', { node: node.nodeId })}</h2>
          <small>
            {t('cap.badge.config')}
            {cap.via === 'sample' ? ` · ${t('cap.badge.sample')}` : ''}
          </small>
        </div>
        <button type="button" onClick={onClose}>{t('cap.close')}</button>
      </header>

      {fn === null
        ? <p className="cap-note cap-note--pad">{t('cap.drill.gone')}</p>
        : node === null
          ? <TierStep fn={fn} nodes={nodes} labels={cap.labels} lang={lang} onNode={setNodeId} />
          : <DevStep fn={fn} node={node} labels={cap.labels} lang={lang} />}

      <footer>
        <span>{node === null ? t('cap.tier.api') : t('cap.dev.api', { node: node.nodeId })}</span>
        {node !== null && <button type="button" onClick={() => setNodeId(null)}>{t('cap.backToTier')}</button>}
        <button type="button" onClick={onClose}>{t('cap.closeShort')}</button>
      </footer>
    </section>
  </div>;
}
