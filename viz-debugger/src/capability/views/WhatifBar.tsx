/**
 * src/capability/views/WhatifBar.tsx (260921 신설 — What-if · 계층별 노드)
 *
 * **무엇을 걸었고 그래서 몇 건이 바뀌는가.** 기능 판과 드릴다운이 **같은 막대**를 쓴다 —
 * 두 벌로 두면 한쪽만 고쳐지고, 그때 한 판은 조건이 걸린 줄도 모르고 값을 그린다.
 *
 * ## 걸린 조건은 답신에서 읽는다
 *
 * 칩에 적는 것은 우리가 보낸 것이 아니라 **서버가 정규화해서 돌려준 `overrides`**다
 * (`whatif.overrides`). 우리 기억을 적으면 서버가 무시한 칸까지 「걸려 있다」고 말하게 된다.
 * 실행 기록 칼럼을 답신 기준으로 맞춘 것과 같은 규칙이다.
 *
 * 다만 서버는 `'*'` 를 **노드 수만큼 펼쳐서** 돌려준다(260921 실측 — 전체에 하나를 걸면
 * 답신에는 여섯 건이 온다). 그대로 적으면 사용자가 한 일(한 번)과 화면이 말하는 것(여섯 번)이
 * 어긋나므로, 전부 같을 때만 한 줄로 되접는다(`collapseOverrides`).
 *
 * ## 「기준선으로」는 늘 있다
 *
 * 조건을 건 사람과 화면을 보는 사람이 다를 수 있다. 되돌리는 길이 한 번에 안 보이면
 * 가상값이 현재값으로 굳는다.
 */

import { t } from '../../i18n/dict.ts';
import { useLang } from '../../shared/language.ts';
import { collapseOverrides } from '../options.ts';
import { clearCapabilityOverrides, useCapability } from '../store.ts';
import { OVERRIDE_ALL, type CapOverride, type CapOverrides } from '../types.ts';

/** 조건 한 칸을 사람 말로. 안 건 칸은 안 적는다 — 빈 칸을 적으면 건 것처럼 보인다. */
function describe(entry: CapOverride): readonly string[] {
  const out: string[] = [];
  if (entry.excludeProviders !== null && entry.excludeProviders.length > 0) {
    out.push(t('cap.whatif.excl', { list: entry.excludeProviders.join(' · ') }));
  }
  if (entry.tags !== null) out.push(t('cap.whatif.tagCount', { n: entry.tags.length }));
  if (entry.budget !== null && entry.budget.computeUnits !== null) {
    out.push(t('cap.whatif.budgetAt', { cu: entry.budget.computeUnits }));
  }
  return out;
}

/** 걸린 조건 전부를 칩 문구로. 전체(`'*'`)를 먼저 적는다 — 그것이 나머지의 바탕이다. */
export function overrideChips(overrides: CapOverrides): readonly string[] {
  const out: string[] = [];
  const all = overrides[OVERRIDE_ALL];
  if (all !== undefined) {
    for (const what of describe(all)) out.push(t('cap.whatif.chipAll', { what }));
  }
  for (const [nodeId, entry] of Object.entries(overrides)) {
    if (nodeId === OVERRIDE_ALL) continue;
    for (const what of describe(entry)) out.push(t('cap.whatif.chipNode', { node: nodeId, what }));
  }
  return out;
}

/**
 * `panel` 은 좁은 기둥이라 세로로, `drill` 은 오버레이라 한 줄로 선다. 담는 것은 같다.
 *
 * `onGlobal` 이 있으면 「전체 노드에 적용」 버튼이 붙는다 — 전달본의 확인 순서 3번
 * (「전체 노드에서 unidepth 를 제외한다」)이 그 버튼 하나로 되는 일이다.
 */
export function WhatifBar({ variant, onGlobal, globalOpen }: {
  variant: 'panel' | 'drill';
  onGlobal?: () => void;
  globalOpen?: boolean;
}) {
  // 언어는 **여기서 구독한다.** `t()` 는 부르는 순간의 값일 뿐 구독이 아니라, 훅이 없으면
  // 이 부품만 옛 언어로 남는다 (`verify:i18n-no-frozen` §2).
  useLang();
  const cap = useCapability();
  const active = cap.whatif !== null;

  // 조건도 없고 사유도 없으면 적을 것이 없다 — 빈 막대는 자리만 먹는다.
  if (!active && cap.whatifError === null && !cap.whatifLoading && onGlobal === undefined) return null;

  const changed = cap.whatif?.diff.filter((row) => row.changed).length ?? 0;
  // 답신이 있으면 그것을(펼쳐진 것은 되접어서), 아직 없으면 우리가 건 것을 적는다.
  const answered = cap.whatif;
  const chips = overrideChips(answered === null
    ? cap.overrides
    : collapseOverrides(answered.overrides, answered.after.nodes.map((node) => node.nodeId)));

  return <div className={`cap-whatif cap-whatif--${variant}${active ? ' is-active' : ''}`}>
    <div className="cap-whatif__line">
      {active && <em className="cap-chip cap-chip--whatif" title={t('cap.badge.whatifTitle')}>{t('cap.badge.whatif')}</em>}
      <strong>
        {cap.whatifLoading
          ? t('cap.whatif.loading')
          : active ? t('cap.whatif.changed', { n: changed }) : t('cap.whatif.baseline')}
      </strong>
      <span className="cap-whatif__buttons">
        {onGlobal !== undefined && <button type="button" onClick={onGlobal}>
          {globalOpen === true ? t('cap.whatif.globalClose') : t('cap.whatif.global')}
        </button>}
        {(active || chips.length > 0) && <button type="button" onClick={() => void clearCapabilityOverrides()}>
          {t('cap.whatif.reset')}
        </button>}
      </span>
    </div>

    {chips.length > 0 && <div className="cap-whatif__chips">
      {chips.map((text) => <em key={text} className="cap-chip cap-chip--plain">{text}</em>)}
    </div>}

    {/* 못 걸었으면 **그 사유를 적는다.** 조용히 기준선으로 돌아가면 조건이 먹힌 줄 안다. */}
    {cap.whatifError !== null && <p className="cap-whatif__error">{t('cap.whatif.error', { reason: cap.whatifError })}</p>}
  </div>;
}
