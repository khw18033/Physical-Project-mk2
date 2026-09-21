/**
 * src/capability/views/CapabilityPanel.tsx (260920 신설 — 기능 상태 패널 이식)
 *
 * **하드웨어 판과 나란히 서는 기능 판.** 마일스톤 화면 오른쪽 기둥이 위아래로 갈라지고
 * 아래 절반이 이것이다 — 둘은 **완전히 다른 판**이고 세로를 1:1 로 나눠 각자 구른다.
 *
 * ## 왜 나란히인가 — 축이 다르다
 *
 *   하드웨어 카드   장비 하나가 **지금 살아 있는가** (실측 MQTT)
 *   기능 판         이 배치에서 **무엇이 가능한가** (설정·manifest 계산)
 *
 * 그래서 「설정 기반 · 실측 아님」 배지가 **끌 수 없게** 붙는다. 바로 위 카드가 실측값이라,
 * 배지가 없으면 계산된 `가능` 이 「카메라가 실제로 돌고 있다」로 읽힌다. 전달본이 두 번
 * 못박은 자리다.
 *
 * ## 배지가 둘이 된다 (260921)
 *
 * 가상 조건이 걸려 있는 동안 **「가상 조건」 배지가 하나 더 붙고, 그것도 끌 수 없다.**
 * 이유가 같다 — 이 판의 값은 이미 한 단계 약한 주장(계산)인데, 거기에 「그것도 실제
 * 설정이 아니라 가정」이 겹친다. 두 겹을 적어 두지 않으면 남이 본 화면이 현재 상태가 된다.
 *
 * 조건은 이 판에서 **걸지 않는다.** 거는 자리는 드릴다운의 계층·자원 단계 하나이고
 * (`NodeConditions`), 여기는 결과와 「기준선으로」만 보인다 — 좁은 기둥에 조작면을 우겨
 * 넣으면 체크박스가 기능 목록을 밀어낸다.
 *
 * ## 세 단계 (사용자 지시 · 260919 논의)
 *
 *   기능        여기 (접힌 목록)
 *   계층·자원   기능을 누르면 — `CapabilityDrill`
 *   개발자      노드를 누르면 — 같은 오버레이의 다음 칸
 *
 * 탭이 아니라 **드릴다운**이다. 탭 셋을 그대로 옮기면 `verify:no-tabs` 에 걸리고, 무엇보다
 * 2026-09-03 에 없앤 것이 다른 이름으로 되살아난다.
 */

import { useEffect, useState } from 'react';
import { t } from '../../i18n/dict.ts';
import { useLang } from '../../shared/language.ts';
import { capabilityBaseUrl } from '../CapabilityClient.ts';
import { capLabel, capReason } from '../labels.ts';
import { clearCapabilityForAddressChange, loadCapability, shownSnapshot, useCapability } from '../store.ts';
import type { CapFunction, CapKindRow } from '../types.ts';
import { CapabilityDrill } from './CapabilityDrill.tsx';
import { WhatifBar } from './WhatifBar.tsx';

/** 원본 `CapabilityState` → 칩 색. 모르는 값은 회색이다 — 초록도 빨강도 거짓이 된다. */
function stateClass(state: string): string {
  if (state === 'ACTIVE') return 'ok';
  if (state === 'DEGRADED') return 'warn';
  if (state === 'DISABLED') return 'bad';
  return 'unknown';
}

/** 못 채운 필수 줄 하나 — 왜 안 되는지 한 줄로. 없으면 null. */
function firstGap(fn: CapFunction): CapKindRow | null {
  return fn.required.find((row) => row.missing || !row.activated) ?? null;
}

export function CapabilityPanel() {
  const lang = useLang();
  const cap = useCapability();
  /**
   * 열려 있는 드릴다운. **상태 하나다** — 기능을 고른 것과 계층 전체 보기가 같은 칸을 쓴다.
   * 둘을 각자 상태로 두면 둘이 동시에 열릴 수 있고, 둘이 열리면 분할 화면이고, 분할 화면은
   * 곧 탭이 된다 (`VZ-N-05` · `DeviceStatusOverlay` 와 같은 규칙).
   */
  const [open, setOpen] = useState<{ fn: string } | { fleet: true } | null>(null);
  const base = capabilityBaseUrl();

  /**
   * 판이 뜨면 한 번 읽는다. 주소가 바뀌거나 테스트를 토글하면 다시 읽는다 —
   * 저장소가 그때 값을 비우므로 여기서 안 읽으면 빈 채로 남는다.
   *
   * **타이머는 없다.** 이 값은 배치 설정이지 계측값이 아니다. 클러스터에서 배치가 바뀌면
   * 새로고침을 누른다 — 초당 갱신하는 척하면 그것대로 거짓이다.
   */
  useEffect(() => {
    // **먼저 버리고 읽는다.** 안 버리면 새 주소를 넣은 뒤 응답이 올 때까지 옛 클러스터의
    // 노드가 화면에 남는다 — 그 몇 초가 「지금 무엇이 가능한가」를 거짓으로 만든다.
    clearCapabilityForAddressChange();
    void loadCapability();
  }, [cap.testMode, base]);

  // 조건이 걸려 있으면 가상값을 그린다. 갈림은 저장소의 한 함수다 — 부품마다 고르면
  // 언젠가 한 칸만 기준선이 남는다.
  const functions = shownSnapshot(cap)?.functions ?? [];
  const sample = cap.via === 'sample';
  /** 기능별 전·후. 서버가 낸 `diff` 를 옮기기만 한다 — 두 상태를 여기서 비교하지 않는다. */
  const diffById = new Map((cap.whatif?.diff ?? []).map((row) => [row.functionId, row]));

  return <aside className="capability-panel">
    <div className="capability-panel__head">
      <h2>{t('cap.heading', { n: functions.length })}</h2>
      <div className="capability-badges">
        {/* **끌 수 없다.** 위 카드는 실측이고 이 판은 계산이다 — 같은 무게로 읽히면 안 된다. */}
        <em className="cap-chip cap-chip--warn" title={t('cap.badge.configTitle')}>{t('cap.badge.config')}</em>
        {/* **이것도 끌 수 없다.** 조건이 걸려 있는 동안에는 늘 뜬다 — 가리는 길이 없어야 한다. */}
        {cap.whatif !== null && <em className="cap-chip cap-chip--whatif" title={t('cap.badge.whatifTitle')}>{t('cap.badge.whatif')}</em>}
        {sample && <em className="cap-chip cap-chip--sample" title={t('cap.badge.sampleTitle')}>{t('cap.badge.sample')}</em>}
        {cap.via === 'direct' && <em className="cap-chip cap-chip--plain" title={t('cap.badge.directTitle')}>{t('cap.badge.direct')}</em>}
      </div>
    </div>
    <p className="capability-panel__hint">
      {t('cap.hint')}
      {/* 계층 전체 보기 — 기능과 무관한 축이라 기능 목록 **안**에 둘 수 없다. 오버레이는
          기능 드릴다운과 같은 것을 쓴다(탭이 아니다 · 동시 하나). */}
      <button type="button" className="capability-panel__fleet" onClick={() => setOpen({ fleet: true })}>
        {t('cap.fleet.open')}
      </button>
    </p>

    {/* 배치 모드가 폴백했으면 그 사실을 적는다 — k3s 를 요청했는데 local 로 떨어진 것은
        「왜 클러스터가 안 바뀌지」의 답이다(전달본 「배치 모드와 한계」). */}
    {cap.control !== null && cap.control.active !== cap.control.requested && <p className="capability-panel__fallback">
      {t('cap.controlFallback', {
        requested: cap.control.requested ?? '?',
        active: cap.control.active ?? '?',
        reason: cap.control.reason ?? t('cap.noReason'),
      })}
    </p>}

    <WhatifBar variant="panel" />

    <div className="capability-panel__body">
      {cap.loading && functions.length === 0 && <p className="capability-panel__note">{t('cap.loading')}</p>}
      {cap.error !== null && <p className="capability-panel__error">{t('cap.error', { reason: cap.error })}</p>}
      {!cap.loading && cap.error === null && functions.length === 0 && <p className="capability-panel__note">{t('cap.empty')}</p>}

      {functions.map((fn) => {
        const gap = firstGap(fn);
        const gapWhy = gap === null ? null : gap.why[0] ?? null;
        const diff = diffById.get(fn.functionId) ?? null;
        // 안 바뀐 기능에는 화살표를 안 붙인다 — 붙이면 전부 바뀐 것처럼 보인다.
        const before = diff !== null && diff.changed ? diff.beforeState : null;
        return <button
          key={fn.functionId}
          type="button"
          className={`cap-fn${before !== null ? ' is-changed' : ''}`}
          onClick={() => setOpen({ fn: fn.functionId })}
        >
          <strong>{capLabel(cap.labels.functions, fn.functionId, lang)}</strong>
          <span className="cap-fn__grade">
            {before !== null && <>
              <em className="cap-chip cap-chip--plain">{capLabel(cap.labels.states, before, lang)}</em>
              <b aria-hidden="true">→</b>
            </>}
            <em className={`cap-chip cap-chip--${stateClass(fn.state)}`}>{capLabel(cap.labels.states, fn.state, lang)}</em>
            <b aria-hidden="true">›</b>
          </span>
          <code>{fn.functionId}</code>
          <small>
            {gap === null
              ? t('cap.reqOpt', { req: fn.required.length, opt: fn.optional.length })
              : t('cap.gap', {
                kind: capLabel(cap.labels.capabilityKinds, gap.kind, lang),
                why: (gapWhy === null ? null : capReason(cap.labels.reasons, gapWhy.reasonToken, gapWhy.reason, lang, gapWhy.reasonData))
                  ?? (gap.activated ? t('cap.noProvider') : t('cap.notActivated')),
              })}
          </small>
        </button>;
      })}
    </div>

    <footer className="capability-panel__foot">
      <span>
        {sample
          ? t('cap.sourceSample')
          : t('cap.source', { base: base === '' ? t('cap.noAddressShort') : base })}
        {cap.fetchedAtMs > 0 && ` · ${new Date(cap.fetchedAtMs).toLocaleTimeString()}`}
      </span>
      <button type="button" disabled={cap.loading} onClick={() => void loadCapability()}>
        {cap.loading ? t('cap.loading') : t('cap.refresh')}
      </button>
    </footer>

    {/* 드릴다운은 오버레이다 — 뒤의 두 판은 언마운트되지 않고, 닫으면 정확히 같은 자리다. */}
    {open !== null && <CapabilityDrill
      functionId={'fn' in open ? open.fn : null}
      onClose={() => setOpen(null)} />}
  </aside>;
}
