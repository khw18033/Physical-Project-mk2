/**
 * src/shell/ConnectionsPanel.tsx (260904 — `VZ-C-07` 연결 대상 설정)
 *
 * **접속 주소를 화면에서 정한다.** 지금까지는 빌드 시점 환경변수라 바꾸려면 다시 빌드해야
 * 했고, 현장에서 게이트웨이·제어 노드 IP가 바뀔 때마다 빌드할 수는 없었다.
 *
 * 화면은 **대상 목록을 그린다** — 손으로 넷을 적지 않는다. 목록의 원천은
 * `shared/connections.ts` 하나이고, 대상이 늘거나 줄면 이 파일은 그대로다.
 *
 * `live: false` 인 대상(제어 노드 · 디지털 트윈)은 **주소를 넣어도 붙을 곳이 없다.**
 * 칸을 잠그고 「연결 예정」으로 둔다 — 없는 것을 있는 척하지 않는다(다른 자리표시와 같은 규칙).
 *
 * ## 설정만이 아니라 확인까지 (260910 — 연결 관리 통합)
 *
 * 260904 에는 이 판이 **설정**(어디에 붙을 것인가)만 하고 상태는 상단 배지가 말했다.
 * 그 가름이 하드웨어가 붙으면서 깨졌다 — 로봇은 「주소가 맞는가」와 「로봇이 답하는가」가
 * 따로 놀고, 둘 다 무대에 오르기 전에 확인해야 하는 것이다. 그래서 대상마다 **네 줄**을 둔다:
 * 주소 · 상태 · 확인 버튼 · 마지막 확인.
 *
 * **「붙었다」와 「답한다」는 다르다.** 브로커는 살아 있는데 로봇이 꺼져 있으면 연결은
 * 성공이고 왕복은 실패다. `physical` 이 줄을 둘 갖는 이유가 그것이다.
 *
 * 상단의 `conn` 배지는 여전히 게이트웨이 연결 하나를 말한다 — 그건 늘 붙어 있어야 하는
 * 것이라 성격이 다르다.
 *
 * ## 260922 — **「확인」이 곧 적용이다** (사람이 화면에서 걸렸다)
 *
 * 드론 프리셋을 골라 주소가 `pi3` 로 보이는데 **확인을 누르면 `pi7` 로 나갔다.** 콘솔에도
 * `pi7` 만 찍혔다. 버그가 아니라 설계였다 — 입력칸은 초안이고, 저장은 판 맨 아래 「적용」이
 * 하며, 「확인」은 **저장된 주소**로 붙어 본다. 그래서 적용을 안 누르면 화면에 적힌 주소와
 * 확인하는 주소가 갈린다.
 *
 * 초안을 둔 이유 자체는 맞다 — 한 글자 칠 때마다 끊고 다시 붙으면 못 쓴다. 틀린 것은
 * **초안을 끝내는 자리**였다. 주소를 고친 사람이 다음에 누르는 것은 바로 옆의 「확인」이지
 * 스크롤 끝의 「적용」이 아니다.
 *
 * 그래서 **「확인」이 그 대상의 초안을 먼저 저장하고 확인한다.** 초안은 남기되 끝내는 자리를
 * 옮긴 것이고, 「적용」은 확인 버튼이 없는 칸(게이트웨이·영상)을 위해 남는다.
 *
 * **최상단 안내는 여전히 없다** (260913 지시 — 시연 직전에 여는 사람에게 매번 같은 자리를
 * 차지한다). 대신 **초안이 저장값과 다를 때만** 그 칸 아래 한 줄이 뜬다. 늘 떠 있는 설명이
 * 아니라 그 상태의 사유다 — 「상태」 줄이 이미 그 규칙으로 돈다.
 */

import { useState } from 'react';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { DETECT_PRESETS, detectPresetReady } from '../detect/presets.ts';
import { BROKER_PRESETS, presetReady } from '../physical/presets.ts';
import { checkTarget, type PhysicalProbe } from '../shared/connectionCheck.ts';
import { robotFacts } from '../physical/robotFacts.ts';
import { armLinkWatch } from '../physical/linkWatch.ts';
import { navProbe } from '../physical/NavClient.ts';
import { robotProbe, robotProbes } from '../physical/robotClient.ts';
import { setTestMode, useDetect } from '../detect/store.ts';
import { CAPABILITY_PRESETS, capabilityPresetReady } from '../capability/presets.ts';
import { MEDIA_PRESETS, mediaPresetReady } from '../media/presets.ts';
import { setCapabilityTestMode, useCapability } from '../capability/store.ts';
import { useDeviceStates } from '../physical/deviceState.ts';
import { CHECKED_TARGETS, healthOf, useConnectionHealth, type TargetHealth } from '../shared/connectionHealth.ts';
import { applyPresetChoice, selectedPresetId } from './presetChoice.ts';
import { commitDraft } from './draftCommit.ts';
import type { ConnectionTarget, ConnectionTargetId } from '../shared/connections.ts';
import {
  CONNECTION_TARGETS,
  connectionKey,
  connectionsWritable,
  resetConnections,
  joinAddressList,
  saveConnections,
  splitAddressList,
  useConnections,
} from '../shared/connections.ts';

/** 260918 — `labelKey`·`whyKey` 는 **사전 키**다. 프리셋 목록은 모듈 최상위 상수라 글자를 못 든다. */
type AddressPreset = { id: string; labelKey: string; url: string; whyKey: string };

/**
 * **네트워크 환경을 고르는 칸이 있는 대상** (260910 로봇 · 260914 객체 탐지).
 *
 * 둘 다 망에 따라 주소가 갈리는 상대다 — 테일넷 이름 · 같은 랜 · 직접 입력. 프리셋 목록은
 * 각자의 경계(`src/physical/` · `src/detect/`)에 두고, 이 화면은 고르는 칸만 그린다.
 * 대상이 늘면 여기 한 줄을 더한다.
 */
const ADDRESS_PRESETS: Partial<Record<ConnectionTargetId, { presets: readonly AddressPreset[]; ready(preset: AddressPreset): boolean }>> = {
  physical: { presets: BROKER_PRESETS, ready: presetReady },
  detect: { presets: DETECT_PRESETS, ready: detectPresetReady },
  // 260920 — 기능 상태. 실제 배치(k3s)의 주소는 아직 비어 있어 고를 수 없다.
  capability: { presets: CAPABILITY_PRESETS, ready: capabilityPresetReady },
  // 260921 — 영상 소켓. 서버 주소가 tailnet 값이라 아직 비어 있어 고를 수 없다.
  media: { presets: MEDIA_PRESETS, ready: mediaPresetReady },
};

/**
 * **「테스트」를 두는 대상** (260912 객체 탐지 · 260920 기능 상태).
 *
 * 켜면 그 경계가 가진 **받아 둔 자료**를 진짜처럼 읽는다. 목록으로 둔 이유는 대상마다
 * 끄고 켜는 함수가 다르기 때문이고, 손으로 `target === '…'` 를 늘리면 세 번째가 붙을 때
 * 한 자리가 빠진다 — 실제로 탐지 한 대상만 보던 분기가 여기 있었다.
 *
 * **분리는 각자의 저장소가 책임진다.** 이 표는 화면일 뿐이고, 끌 때 값을 버리는 규칙은
 * `detect/store.ts` 와 `capability/store.ts` 안에 있다.
 */
type TestToggle = { on: boolean; set(next: boolean): void; titleKey: string };

/**
 * **「확인」 버튼이 있는 대상인가.** 두 곳이 이 목록을 묻는다 — 확인 줄을 그릴 때와,
 * 저장 안 된 칸이 「무엇을 누르면 되는지」 적을 때다 (260922).
 *
 * 손으로 `target === '…'` 를 두 번 늘어놓으면 대상이 하나 붙을 때 **한쪽만 는다** — 그러면
 * 확인 버튼은 있는데 안내는 「아래 적용」이라고 말하는 칸이 생긴다. 표와 같은 이유로 함수 하나다.
 */
function hasCheck(target: ConnectionTargetId): boolean {
  return CHECKED_TARGETS.includes(target)
    || target === 'autodrive' || target === 'autodrive-ai' || target === 'capability';
}

export function ConnectionsPanel({ onClose, physical }: { onClose(): void; physical?: PhysicalProbe | null }) {
  const current = useConnections();
  /**
   * 편집 중인 값. **누르기 전까지는 안 적용된다** — 한 글자 칠 때마다 끊고 다시 붙으면
   * 못 쓴다. 끝내는 자리가 둘이다: 그 대상의 「확인」(260922)과 판 아래 「적용」.
   */
  const [draft, setDraft] = useState<Record<string, string>>({ ...current });
  /**
   * **「직접 입력」을 고른 칸.** 주소와 따로 들고 있어야 하는 이유는 `presetChoice.ts` 에
   * 적어 두었다 — 주소만 보고는 「사람이 직접 입력을 골랐다」를 알 수 없다.
   */
  const [manual, setManual] = useState<Record<string, boolean>>({});
  const [note, setNote] = useState<string | null>(null);
  // 언어가 바뀌면 다시 그린다 — `t()` 는 값을 줄 뿐 리렌더를 일으키지 않는다 (§4).
  useLang();
  const writable = connectionsWritable();
  const dirty = CONNECTION_TARGETS.some((target) => target.fields.some((field) => {
    const key = connectionKey(target.id, field.key);
    return (draft[key] ?? '') !== (current[key] ?? '');
  }));

  const apply = () => {
    const saved = saveConnections(draft);
    setNote(saved
      ? t('conn.applied')
      : t('conn.appliedSession'));
  };
  /**
   * **이 대상의 초안만 저장한다.** 「확인」이 붙어 보기 직전에 부른다 (260922 — 위 §260922).
   *
   * 얹는 규칙과 「안 바뀌었으면 `null`」은 `draftCommit.ts` 에 있다 — 여기 두면 검사가
   * 글자로만 읽어서 무엇을 넘기는지 못 본다(`presetChoice.ts` 와 같은 이유).
   */
  const commit = (target: ConnectionTarget) => {
    const next = commitDraft(current, draft, target.fields.map((field) => connectionKey(target.id, field.key)));
    if (next === null) return;
    setNote(saveConnections(next) ? t('conn.applied') : t('conn.appliedSession'));
  };
  const restore = () => {
    resetConnections();
    setDraft({});
    // 기본값으로 되돌리면 고름도 되돌린다 — 안 그러면 주소는 프리셋인데 목록만 직접 입력이다.
    setManual({});
    setNote(t('conn.restored'));
  };

  return <aside className="global-panel global-panel--connections">
    <header><b>{t('conn.title')}</b><button onClick={onClose}>{t('conn.close')}</button></header>
    {/* **최상단 안내를 뺐다** (260913 지시). 여기 있던 세 줄은 이 판을 처음 여는 사람에게
        필요한 말이고, 시연 직전에 여는 사람에게는 매번 같은 자리를 차지할 뿐이었다.
        규칙 자체는 그대로다 — 환경변수가 기본값이고 여기서 넣은 값이 이긴다. */}
    {/* 시범 키 ③ 긴 오류 문장 (영문화 1단계 §4). 좁은 판이라 **줄바꿈이 레이아웃을 깨는지**를
        여기서 본다 — 영어가 한국어보다 길다. 2단계에 미리 알아야 할 것이 이런 자리다. */}
    {!writable && <p className="connections__warn">
      {t('conn.storageBlocked')}
    </p>}
    {/* 목록을 그린다. 대상이 늘면 이 파일이 아니라 shared/connections.ts 가 바뀐다. */}
    {CONNECTION_TARGETS.map((target) => <section key={target.id} className={`conn-target${target.live ? '' : ' conn-target--pending'}`}>
      {/* 대상 이름·설명은 `shared/connections.ts` 가 **키로** 들고 있다 — 여기서 푼다.
          그 파일에서 t() 를 부르면 모듈 최상위 상수라 언어가 로드 시점에 굳는다 (260918). */}
      <h3>{t(target.labelKey)}{target.live ? null : <em>{t('conn.pendingBadge')}</em>}</h3>
      {/* 설명이 없는 대상도 있다 (260913 지시 — 로봇·객체 탐지). 늘 쓰는 둘이라
          매번 읽을 문장이 아니다. 자리도 그만큼 줄어든다. */}
      {target.whatKey !== undefined && <p>{t(target.whatKey)}</p>}
      {target.pendingKey !== undefined && <p className="conn-target__pending">{t(target.pendingKey)}</p>}
      {target.fields.map((field) => {
        const key = connectionKey(target.id, field.key);
        const choice = ADDRESS_PRESETS[target.id];
        /**
         * **주소가 여럿인 칸** (260922 — 로봇 N대). 줄마다 입력을 하나씩 그리고, 저장할 때
         * 줄바꿈으로 이어 붙인다(`joinAddressList`). 사람은 줄바꿈을 보지 않는다.
         *
         * 빈 줄 하나를 늘 뒤에 둔다 — 「+ 추가」를 누르고 나서 어디에 쓰는지 찾는 것보다,
         * 빈 칸이 이미 있고 거기 쓰면 되는 편이 빠르다.
         */
        if (field.list === true) {
          const rows = splitAddressList(draft[key] ?? '');
          const shown = [...rows, ''];
          const write = (next: readonly string[]) =>
            setDraft((prev) => ({ ...prev, [key]: joinAddressList(next) }));
          return <div key={key} className="conn-list">
            {shown.map((row, index) => <label key={index}>
              <span>{index === 0 ? t(field.labelKey) : ''}</span>
              {choice !== undefined && <select
                className="conn-preset"
                value={selectedPresetId(choice.presets, row, manual[`${key}.${index}`] === true)}
                onChange={(event) => {
                  const next = applyPresetChoice(choice.presets, event.target.value);
                  setManual((prev) => ({ ...prev, [`${key}.${index}`]: next.manual }));
                  if (next.url !== null) {
                    const copy = [...shown];
                    copy[index] = next.url;
                    write(copy);
                  }
                }}
              >
                {choice.presets.map((preset) => <option
                  key={preset.id}
                  value={preset.id}
                  title={t(preset.whyKey)}
                  disabled={!choice.ready(preset)}
                >{t(preset.labelKey)}{choice.ready(preset) || preset.id === 'manual' ? '' : t('conn.presetUndecided')}</option>)}
              </select>}
              <input
                value={row}
                placeholder={index === rows.length ? t('conn.addAddress') : field.fallback}
                onChange={(event) => {
                  const copy = [...shown];
                  copy[index] = event.target.value;
                  write(copy);
                }} />
              {/* 지우는 길. 빈 줄에는 안 붙는다 — 지울 것이 없다. */}
              {index < rows.length && <button type="button" className="conn-row-drop"
                title={t('conn.dropAddress')}
                onClick={() => write(rows.filter((_, i) => i !== index))}
              >×</button>}
            </label>)}
            {(draft[key] ?? '') !== (current[key] ?? '') && <p className="conn-unsaved">
              {t(hasCheck(target.id) ? 'conn.unsavedCheck' : 'conn.unsavedApply')}
            </p>}
          </div>;
        }
        return <label key={key}>
          <span>{t(field.labelKey)}</span>
          {/* 프리셋이 있는 대상은 네트워크 환경을 고르는 자리도 준다 (§2) — 로봇과 객체 탐지.
              이름이 안 풀릴 때 손으로 IP 를 치는 것보다 고르는 편이 빠르다. */}
          {choice !== undefined && <select
            className="conn-preset"
            /* 고름은 **주소에서 되풀이해 유도할 수 없다** — 「직접 입력」은 주소가 아니라
               사람의 뜻이다. 그래서 고른 것을 기억하고 그 둘로 정한다 (`presetChoice.ts`). */
            value={selectedPresetId(choice.presets, draft[key] ?? '', manual[key] === true)}
            onChange={(event) => {
              const next = applyPresetChoice(choice.presets, event.target.value);
              setManual((prev) => ({ ...prev, [key]: next.manual }));
              // `null` 이면 주소를 안 건드린다 — 직접 입력으로 넘어갈 때 칸을 비우면
              // 고쳐 쓰려던 주소를 잃는다.
              if (next.url !== null) setDraft((prev) => ({ ...prev, [key]: next.url as string }));
            }}
          >
            {choice.presets.map((preset) => <option
              key={preset.id}
              value={preset.id}
              title={t(preset.whyKey)}
              // 값이 빈 프리셋은 **아직 없는 것**이다 — 고를 수 없게 막는다.
              disabled={!choice.ready(preset)}
            >{t(preset.labelKey)}{choice.ready(preset) || preset.id === 'manual' ? '' : t('conn.presetUndecided')}</option>)}
          </select>}
          <input
            value={draft[key] ?? ''}
            disabled={!target.live}
            placeholder={target.live ? field.fallback : t('conn.placeholderPending')}
            onChange={(event) => setDraft((prev) => ({ ...prev, [key]: event.target.value }))} />
          {/* **저장 안 된 칸만 말한다** (260922). 늘 떠 있는 안내는 260913 에 걷어냈고
              그 결정은 그대로다 — 이 줄은 설명이 아니라 **이 칸이 지금 어떤 상태인지**다.
              무엇을 누르면 되는지까지 적는다: 확인이 있는 대상은 확인이 저장까지 한다. */}
          {target.live && (draft[key] ?? '') !== (current[key] ?? '') && <p className="conn-unsaved">
            {t(hasCheck(target.id) ? 'conn.unsavedCheck' : 'conn.unsavedApply')}
          </p>}
        </label>;
      })}
      {/* 상태 · 확인 · 마지막 확인 — 나머지 세 줄 (§2). 확인 방법이 있는 대상만.
          자율주행(pi1)도 확인은 되지만 머리줄 표시등의 목록(`CHECKED_TARGETS`)에는 안 넣는다 —
          문 찾기 시연의 「n/4 확인됨」이 그대로여야 한다 (260915). */}
      {hasCheck(target.id) && <HealthRow
        target={target.id}
        physical={target.id === 'physical' ? (physical ?? null) : null}
        onCommit={() => commit(target)}
      />}
    </section>)}
    <footer className="connections__actions">
      {note && <span className="connections__note">{note}</span>}
      {/* 되돌아올 길. 틀린 주소를 넣으면 아무 데도 못 붙으므로 이 길이 없으면 갇힌다. */}
      <button onClick={restore}>{t('conn.restore')}</button>
      <button className="connections__apply" onClick={apply} disabled={!dirty}>{t('conn.apply')}</button>
    </footer>
  </aside>;
}

/**
 * 대상 하나의 **상태 · 확인 · 마지막 확인** 세 줄.
 *
 * 줄이 여럿일 수 있다 — `physical` 이 브로커와 로봇 둘이다. 한 줄로 뭉치면 발표 직전에
 * 주소를 봐야 하는지 로봇 전원을 봐야 하는지 못 가른다 (§3).
 */
function HealthRow({ target, physical, onCommit }: {
  target: ConnectionTargetId;
  physical: PhysicalProbe | null;
  /**
   * **누르기 직전에 이 대상의 초안을 저장한다** (260922). 확인이 저장된 주소로 붙기
   * 때문에, 이것이 없으면 화면에 적힌 주소와 확인하는 주소가 갈린다 — 파일 머리 §260922.
   */
  onCommit(): void;
}) {
  // **같은 파일 안이어도 별개 컴포넌트는 자기 훅이 필요하다** (지시서 §2 ①).
  // 위 `ConnectionsPanel` 의 `useLang()` 은 이 부품을 다시 그리게 하지 않는다 — 빼면
  // 언어를 바꿔도 「확인」 버튼과 「아직 확인하지 않았습니다」만 옛 언어로 남는다.
  useLang();
  const health = useConnectionHealth();
  // 장비 상태를 구독한다 — 로봇 줄이 그 값으로 채워진다.
  useDeviceStates();
  const state: TargetHealth = health[target] ?? { checking: false, lines: [] };
  // 「테스트」가 있는 대상은 둘이다. **훅은 조건 없이 부른다** — 그리기마다 수가 달라지면 안 된다.
  const detect = useDetect();
  const capability = useCapability();
  const test: Partial<Record<ConnectionTargetId, TestToggle>> = {
    detect: { on: detect.testMode, set: setTestMode, titleKey: 'conn.testTitle' },
    capability: { on: capability.testMode, set: setCapabilityTestMode, titleKey: 'conn.testTitleCapability' },
  };
  const toggle = test[target];
  return <div className="conn-health">
    <div className="conn-health__lines">
      {state.lines.length === 0
        ? <span className="conn-dot conn-dot--unknown">{t('conn.notChecked')}</span>
        : state.lines.map((row) => <span key={row.id} className={`conn-dot conn-dot--${row.ok === true ? 'ok' : row.ok === false ? 'bad' : 'unknown'}`}>
          {/* **어느 주소의 줄인가** (260922). 상대가 하나면 안 적는다 — 반복하면 읽을 것만 는다. */}
          {row.scope !== undefined && <em className="conn-dot__scope">{row.scope}</em>}
          {t(row.labelKey)} {row.ok === true ? '✓' : row.ok === false ? '✕' : '?'}
          {row.roundTripMs !== null && ` ${row.roundTripMs}ms`}
          {row.reason !== null && ` — ${row.reason}`}
        </span>)}
    </div>
    {/*
      **탐지만의 「테스트」** (260912 지시). 확인 버튼 왼쪽이다.

      켜면 탐지 담당이 준 **실제 산출물**(`door_example/`)을 진짜 결과처럼 읽는다. 목을
      지어내는 것이 아니라 받은 값 그대로다 — 그래서 화면이 「테스트 자료」라고 적되 값은
      손대지 않는다. 탐지 서비스가 붙기 전에 화면 쪽을 다 맞춰 둘 수 있다.

      **끄면 읽어 둔 것도 같이 버린다.** 시료가 실제 결과로 남아 있으면 안 된다.
    */}
    {toggle !== undefined && <label className="conn-test" title={t(toggle.titleKey)}>
      <input type="checkbox" checked={toggle.on} onChange={(event) => toggle.set(event.target.checked)} />
      {t('conn.test')}
    </label>}
    <button
      type="button"
      className="conn-check"
      disabled={state.checking}
      /**
       * 확인이 끝나면 **FC 링크 줄이 있는 장비에 한해** 그 줄을 계속 다시 재게 한다
       * (260921). 브로커·단말과 달리 FC 링크는 시연 도중에 바뀌므로, 눌렀을 때의 값을
       * 계속 보여 주면 점퍼가 빠진 것을 무대에서 모른다. Go1 은 그 줄이 없어 안 켜진다.
       */
      onClick={() => {
        // **저장이 먼저다.** 확인은 저장된 주소로 붙으므로, 여기서 안 끝내면 방금 고친
        // 주소가 아니라 옛 주소를 확인한다 (260922 — 파일 머리 §260922).
        onCommit();
        /**
         * **주소가 여럿이면 줄마다 확인한다** (260922). 로봇이 둘이면 「하나는 붙고 하나는
         * 안 붙은」 상태가 정상적으로 생기고, 한 줄로 뭉치면 어느 쪽인지 못 가른다.
         */
        void checkTarget(
          target, physical, robotFacts,
          target === 'autodrive' ? navProbe() : null,
          target === 'physical' ? robotProbes() : null,
        ).then(() => { if (target === 'physical') armLinkWatch(healthOf('physical').lines, robotProbe, robotFacts); });
      }}
    >{state.checking ? t('conn.checking') : t('conn.check')}</button>
    {state.lines.length > 0 && <small className="conn-health__at">
      {new Date(state.lines[0].checkedAtIso).toLocaleTimeString()}
    </small>}
  </div>;
}
