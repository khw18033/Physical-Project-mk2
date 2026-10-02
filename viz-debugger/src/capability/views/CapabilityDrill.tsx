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
 * ## 계층으로 묶는다 (260921)
 *
 * 이식 때는 노드를 **평면으로** 늘어놓고 role 을 첫 칸의 글자로만 적었다. 그래서 전달본의
 * 「계층별 노드」가 사라졌다 — 계층이 분류가 아니라 열 하나가 되면, 「이 계층이 무엇을
 * 제공하는가」를 물을 자리가 없다. 이제 role 이 섹션이고, 섹션마다 그 계층이 제공하는
 * kind 를 단다(`served` — 서버가 주던 칸인데 파서가 버리고 있었다).
 *
 * ## 조건은 줄 안에서 편다
 *
 * 줄 전체를 누르면 조건이 펴지고, 오른쪽 `›` 가 개발자 단계로 간다. 둘을 한 버튼에 걸면
 * 「태그 하나 켜려다 화면이 넘어가는」 일이 생긴다.
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
import { useLang } from '../../shared/language.ts';
import { capLabel, capReason } from '../labels.ts';
import { nodesOfRole, rolesOf, servedByRole } from '../options.ts';
import { baselineSnapshot, shownSnapshot, useCapability } from '../store.ts';
import {
  OVERRIDE_ALL,
  type CapCost, type CapFunction, type CapLabels, type CapNode, type CapNodeRow, type CapSnapshot,
} from '../types.ts';
import { GlobalConditions, NodeConditions, nodeChanged } from './NodeConditions.tsx';
import { WhatifBar } from './WhatifBar.tsx';

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

/**
 * 그 기능이 요구하는 kind — 필수 먼저, 그다음 선택. 순서가 화면의 순서다.
 *
 * **기능을 안 고른 판(전체 보기)에서는 `fn` 이 `null`** 이고, 그때는 이 배치가 실제로
 * 제공하는 kind 전부가 범위다(`served` 의 키). 「필수/선택」은 기능이 정하는 말이라
 * 그 판에서는 전부 선택으로 둔다 — 없는 구분을 지어내지 않는다.
 */
function kindsOf(fn: CapFunction | null, shown: CapSnapshot): readonly { kind: string; required: boolean }[] {
  if (fn === null) return Object.keys(shown.served).map((kind) => ({ kind, required: false }));
  return [
    ...fn.required.map((row) => ({ kind: row.kind, required: true })),
    ...fn.optional.map((row) => ({ kind: row.kind, required: false })),
  ];
}

/** 노드 한 줄 — 접힌 상태와 펴진 조건면. */
function NodeRow({ node, baseline, wanted, labels, onNode, open, onToggle }: {
  /** 그릴 값 — 조건이 걸려 있으면 가상값이다. */
  node: CapNode;
  /**
   * 조건을 비교·편집할 기준 한 벌. `null` 이면 조건을 못 편다.
   *
   * **`shown` 을 넘기면 안 된다.** `after` 의 노드는 조건이 이미 반영된 값이라
   * 「설정과 같은가」가 늘 참이 되고, 제외한 provider 는 목록에서 아예 사라진다.
   */
  baseline: CapSnapshot | null;
  wanted: ReadonlySet<string>;
  labels: CapLabels;
  onNode(nodeId: string): void;
  open: boolean;
  onToggle(): void;
}) {
  const lang = useLang();
  const cap = useCapability();
  const mine = node.rows.filter((row) => wanted.has(row.kind));
  const serves = mine.filter((row) => row.state === 'ACTIVE');
  const used = usedCost(node.rows);
  const limit = node.budget;
  const over = limit?.computeUnits !== null && limit?.computeUnits !== undefined
    && (used.computeUnits ?? 0) > limit.computeUnits;
  const baselineNode = baseline?.nodes.find((entry) => entry.nodeId === node.nodeId) ?? null;
  const changed = baselineNode !== null && nodeChanged(cap.overrides, baselineNode);

  return <div className={`cap-noderow${open ? ' is-open' : ''}${changed ? ' is-changed' : ''}`}>
    <button type="button" className="cap-noderow__main" onClick={onToggle} aria-expanded={open}>
      <span className="cap-noderow__id">
        <code>{node.nodeId}</code>
        {node.label !== null && <small>{node.label}</small>}
      </span>
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
      <span className="cap-noderow__cond">
        {changed && <em className="cap-chip cap-chip--whatif">{t('cap.cond.changed')}</em>}
        <b aria-hidden="true">{open ? '⌄' : t('cap.cond.open')}</b>
      </span>
    </button>
    <button
      type="button"
      className="cap-noderow__go"
      aria-label={t('cap.tier.toDev', { node: node.nodeId })}
      onClick={() => onNode(node.nodeId)}
    >›</button>
    {open && baselineNode !== null && baseline !== null
      && <NodeConditions node={baselineNode} baseline={baseline} />}
  </div>;
}

function TierStep({ fn, shown, baseline, labels, onNode }: {
  /** `null` 이면 기능을 안 고른 **전체 보기**다. */
  fn: CapFunction | null; shown: CapSnapshot; baseline: CapSnapshot | null; labels: CapLabels;
  onNode(nodeId: string): void;
}) {
  // 언어는 **내려받지 않고 여기서 구독한다.** `t()` 는 부르는 순간의 값일 뿐 구독이 아니라,
  // 훅이 없으면 이 부품만 옛 언어로 남는다 (`verify:i18n-no-frozen` §2).
  const lang = useLang();
  const cap = useCapability();
  /**
   * 펴진 조건면 하나. **문자열 하나다** — 배열이면 둘이 열리고, 둘이 열리면 분할 화면이고,
   * 분할 화면은 곧 탭이 된다 (`VZ-N-05` 와 같은 규칙). `'*'` 면 전체 조건이다.
   */
  const [openCond, setOpenCond] = useState<string | null>(null);
  const kinds = kindsOf(fn, shown);
  const wanted = new Set(kinds.map((entry) => entry.kind));
  const roles = rolesOf(shown);

  return <>
    <WhatifBar
      variant="drill"
      globalOpen={openCond === OVERRIDE_ALL}
      onGlobal={() => setOpenCond(openCond === OVERRIDE_ALL ? null : OVERRIDE_ALL)}
    />
    {openCond === OVERRIDE_ALL && baseline !== null && <GlobalConditions baseline={baseline} />}

    {fn === null
      // 전체 보기에는 판정이 없다 — 기능을 안 골랐으니 「가능/불가」를 말할 대상이 없다.
      // 대신 이 배치의 크기를 적는다. 없는 판정을 지어내는 것보다 낫다.
      ? <div className="cap-strip">
        <b>{t('cap.fleet.strip.title')}</b>
        <span><small>{t('cap.fleet.strip.roles')}</small><b>{roles.length}</b></span>
        <span><small>{t('cap.fleet.strip.nodes')}</small><b>{shown.nodes.length}</b></span>
        <span><small>{t('cap.fleet.strip.kinds')}</small><b>{Object.keys(shown.served).length}</b></span>
      </div>
      : <div className="cap-strip">
        <b>{t('cap.tier.verdict')}<em className={`cap-chip cap-chip--${stateClass(fn.state)}`}>{capLabel(labels.states, fn.state, lang)}</em></b>
        <span><small>{t('cap.tier.required')}</small><b>{fn.required.length}</b></span>
        <span><small>{t('cap.tier.optional')}</small><b>{fn.optional.length}</b></span>
        <span><small>{t('cap.tier.byRole')}</small><b>{Object.keys(fn.byRole).length === 0 ? '—' : Object.entries(fn.byRole)
          .map(([role, cost]) => `${capLabel(labels.roles, role, lang)} ${costText(cost) ?? '—'}`).join(' · ')}</b></span>
      </div>}

    {/* 부족한 kind 가 있으면 계층별 사유를 먼저 적는다 — 「왜 불가인가」가 표 위에 있어야 한다. */}
    {fn !== null && fn.supplement.length > 0 && <ul className="cap-supplement">
      {fn.supplement.map((row) => <li key={`${row.kind}/${row.role}`}>
        <code>{capLabel(labels.capabilityKinds, row.kind, lang)}</code>
        <em>{capLabel(labels.roles, row.role, lang)}</em>
        <span>{capReason(labels.reasons, row.reasonToken, row.reason, lang, row.reasonData) ?? t('cap.noReason')}</span>
      </li>)}
    </ul>}

    <p className="cap-note">{t(fn === null ? 'cap.fleet.note' : 'cap.tier.note')}</p>

    {roles.map((role) => {
      const nodes = nodesOfRole(shown, role);
      const here = servedByRole(shown, role);
      // 조건 때문에 **사라진 것**은 자리를 남긴다 — 그냥 없애면 「원래 없었다」로 읽힌다.
      const gone = baseline === null || cap.whatif === null
        ? []
        : servedByRole(baseline, role).filter((kind) => !here.includes(kind));
      return <section key={role} className="cap-role">
        <div className="cap-role__head">
          <div className="cap-role__title">
            <strong>{capLabel(labels.roles, role, lang) || t('cap.noRole')}</strong>
            <code>{role === '' ? '—' : role}</code>
            <span>{t('cap.tier.role.nodes', { n: nodes.length })}</span>
          </div>
          <div className="cap-role__serves">
            <span>{t('cap.tier.role.serves')}</span>
            {here.length === 0 && gone.length === 0
              ? <em className="cap-chip cap-chip--unknown">{t('cap.tier.role.noServes')}</em>
              : here.map((kind) => <em key={kind} className="cap-chip cap-chip--ok">
                {capLabel(labels.capabilityKinds, kind, lang)}
              </em>)}
            {gone.map((kind) => <em key={kind} className="cap-chip cap-chip--gone">
              {capLabel(labels.capabilityKinds, kind, lang)}
            </em>)}
            {gone.length > 0 && <small>{t('cap.tier.gone')}</small>}
          </div>
        </div>
        {nodes.map((node) => <NodeRow
          key={node.nodeId}
          node={node}
          baseline={baseline}
          wanted={wanted}
          labels={labels}
          onNode={onNode}
          open={openCond === node.nodeId}
          onToggle={() => setOpenCond(openCond === node.nodeId ? null : node.nodeId)}
        />)}
      </section>;
    })}
  </>;
}

function DevStep({ fn, node, shown, labels }: {
  fn: CapFunction | null; node: CapNode; shown: CapSnapshot; labels: CapLabels;
}) {
  const lang = useLang();
  const kinds = kindsOf(fn, shown);
  const byKind = new Map(node.rows.map((row) => [row.kind, row]));
  const alternatives = kinds
    .flatMap(({ kind }) => (byKind.get(kind)?.alternatives ?? []).map((alt) => ({ kind, alt })));
  /** 고른 provider 가 실제로 어디에 꽂히는지 — 서버가 객체로 주고 파서가 `k=v` 로 이어 붙인다. */
  const selectors = [...new Set(kinds
    .map(({ kind }) => byKind.get(kind)?.nodeSelector)
    .filter((value): value is string => value !== null && value !== undefined))];
  return <div className="cap-dev">
    <div className="cap-dev__main">
      <h3>{fn === null
        ? t('cap.fleet.dev.rows')
        : t('cap.dev.rows', { fn: capLabel(labels.functions, fn.functionId, lang) })}</h3>
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

/**
 * `functionId` 가 `null` 이면 **기능을 안 고른 전체 보기**다(260921 · (나)안).
 *
 * 전달본의 「계층·자원」 탭은 원래 기능과 무관한 fleet 축이었다. 이식 때 기능 드릴다운
 * 안으로 들어가면서 그 축이 사라졌고, 그래서 「이 배치의 계층 구성이 통째로 어떻게
 * 생겼나」를 볼 자리가 없었다. 여기가 그 자리다 — **탭이 아니라 같은 오버레이**이고,
 * 규칙(동시 하나 · 뒤를 안 갈아 치움 · 닫는 길 둘)도 그대로다.
 */
export function CapabilityDrill({ functionId, onClose }: { functionId: string | null; onClose(): void }) {
  const lang = useLang();
  const cap = useCapability();
  const [nodeId, setNodeId] = useState<string | null>(null);

  // 여는 길이 하나여도 닫는 길은 둘 이상이어야 한다 (`DeviceStatusOverlay` 와 같은 규칙).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // 조건이 걸려 있으면 가상값을, 아니면 기준선을 그린다. 갈림은 저장소의 한 함수다.
  const shown = shownSnapshot(cap);
  const baseline = baselineSnapshot(cap);
  const fleet = functionId === null;
  const fn = fleet ? null : shown?.functions.find((entry) => entry.functionId === functionId) ?? null;
  const node = nodeId === null ? null : shown?.nodes.find((entry) => entry.nodeId === nodeId) ?? null;
  const fnName = fn === null ? (functionId ?? t('cap.fleet.crumb')) : capLabel(cap.labels.functions, fn.functionId, lang);
  /** 기능을 골랐는데 그 기능이 응답에 없다 — 전체 보기에서는 일어날 수 없는 일이다. */
  const missing = !fleet && (fn === null || shown === null);

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="modal cap-modal" role="dialog" aria-label={fleet ? t('cap.fleet.aria') : t('cap.drill.aria', { fn: fnName })}>
      <header>
        <div>
          <nav className="crumbs" aria-label={t('cap.crumb.aria')}>
            <button type="button" className="crumbs__link" onClick={onClose}>{t('cap.crumb.functions')}</button>
            <span className="crumbs__sep" aria-hidden="true">›</span>
            {node === null
              ? <span className="crumbs__here">{t(fleet ? 'cap.fleet.crumb' : 'cap.crumb.tier')}</span>
              : <button type="button" className="crumbs__link" onClick={() => setNodeId(null)}>{t(fleet ? 'cap.fleet.crumb' : 'cap.crumb.tier')}</button>}
            {node !== null && <>
              <span className="crumbs__sep" aria-hidden="true">›</span>
              <span className="crumbs__here">{t('cap.crumb.dev')}</span>
            </>}
          </nav>
          <h2>{node !== null
            ? t('cap.dev.title', { node: node.nodeId })
            : fleet ? t('cap.fleet.title') : t('cap.tier.title', { fn: fnName })}</h2>
          <small>
            {t('cap.badge.config')}
            {cap.via === 'sample' ? ` · ${t('cap.badge.sample')}` : ''}
            {cap.whatif !== null ? ` · ${t('cap.badge.whatif')}` : ''}
          </small>
        </div>
        <button type="button" onClick={onClose}>{t('cap.close')}</button>
      </header>

      {missing || shown === null
        ? <p className="cap-note cap-note--pad">{t('cap.drill.gone')}</p>
        : node === null
          ? <TierStep fn={fn} shown={shown} baseline={baseline} labels={cap.labels} onNode={setNodeId} />
          : <DevStep fn={fn} node={node} shown={shown} labels={cap.labels} />}

      <footer>
        <span>{node === null ? t(fleet ? 'cap.fleet.api' : 'cap.tier.api') : t('cap.dev.api', { node: node.nodeId })}</span>
        {node !== null && <button type="button" onClick={() => setNodeId(null)}>{t('cap.backToTier')}</button>}
        <button type="button" onClick={onClose}>{t('cap.closeShort')}</button>
      </footer>
    </section>
  </div>;
}
