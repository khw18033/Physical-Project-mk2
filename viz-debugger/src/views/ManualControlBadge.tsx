/**
 * src/views/ManualControlBadge.tsx (261005 신설 — 로봇 수동 제어 알림)
 *
 * **화면 우측 상단 — 지금 수동 제어가 켜진 장비.** 카드를 닫고 다른 화면을 보면서 몰 때, 어느 장비가 키를
 * 받고 있는지 · 왜 안 움직이는지를 여기서 본다(지시 ④). 켜진 장비가 없으면 아무것도 안 그린다.
 *
 * 줄마다 끄기 버튼이 있다 — 카드를 다시 열지 않고 끌 수 있어야 한다. 같은 키를 둘 이상이 쓰면 경고 줄이
 * 붙는다(함께 움직인다).
 *
 * 막힘(자동 제어 · 입력 중 · 연결 없음)은 이벤트가 아니라 지금 상태라 1초마다 다시 본다.
 */

import { useEffect, useState } from 'react';
import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { deviceCandidates } from '../physical/deviceIdentity.ts';
import { enabledManualDevices, keyLabel, manualConfig, manualModeOf, setManualEnabled, sharedKeys, useManualState } from '../physical/manualControl.ts';
import { manualBlock, useManualEvents, type ManualEvent } from '../physical/manualDispatch.ts';

/** 1초마다 다시 그린다 — 막힘은 알림이 오는 값이 아니라 그때그때 보는 값이다. */
export function useEverySec(): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setTick((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, []);
}

function paramsText(parameters: Record<string, number>): string {
  return Object.entries(parameters).filter(([name]) => name !== 'hold_ms').map(([name, value]) => `${name}=${value}`).join(' ');
}

const KNOWN_REJECTS = new Set(['mission_in_progress', 'teleop_halted_by_abort']);

export function ManualEventLine({ event }: { event: ManualEvent }) {
  useLang();
  if (event.kind === 'sent') return <>{t('manual.event.sent', { action: event.action, params: paramsText(event.parameters) })}</>;
  if (event.kind === 'failed') return <>{t('manual.event.failed', { action: event.action, reason: event.reason })}</>;
  if (event.kind === 'rejected') {
    // pi7 이 정한 사유는 풀어 쓰고, 모르는 것은 장비가 준 그대로 적는다. 사유는 `code` 에 올 수도,
    // `FAILED_PRECONDITION` 뒤의 `message` 에 올 수도 있다(`scan_continue` 의 거절이 뒤쪽이었다) — 둘 다 본다.
    const known = [event.code, event.message].find((value) => value !== null && KNOWN_REJECTS.has(value.trim()));
    if (known != null) return <>{t(`manual.reject.${known.trim()}`, { action: event.action })}</>;
    return <>{t('manual.event.rejected', { action: event.action, detail: [event.code, event.message].filter((v) => v).join(' ') || t('robot.noReason') })}</>;
  }
  return <>{t(`manual.block.${event.block}`)}</>;
}

export function ManualControlBadge() {
  useLang();
  useManualState();
  useEverySec();
  const events = useManualEvents();
  const devices = enabledManualDevices();
  if (devices.length === 0) return null;
  const shared = [...sharedKeys(devices)];
  return <aside className="manual-badge" aria-live="polite">
    {devices.map((deviceId) => {
      const block = manualBlock(deviceId);
      const config = manualConfig(deviceId);
      const actions = deviceCandidates().find((candidate) => candidate.deviceId === deviceId)?.actions ?? null;
      const event = events[deviceId];
      return <div key={deviceId} className={block === null ? 'manual-badge__row' : 'manual-badge__row manual-badge__row--blocked'}>
        <span className="manual-badge__dot" aria-hidden="true" />
        <div>
          <b>{t('manual.badge.line', { id: deviceId })}</b>
          <small>
            {t(`manual.preset.${config.preset}`)} · {t(manualModeOf(actions) === 'velocity' ? 'manual.mode.velocity' : 'manual.mode.step')}
            {block !== null ? <> · <em>{t(`manual.block.${block}`)}</em></> : event !== undefined ? <> · <ManualEventLine event={event} /></> : null}
          </small>
        </div>
        <button type="button" onClick={(clicked) => { setManualEnabled(deviceId, false); clicked.currentTarget.blur(); }}>{t('manual.badge.off')}</button>
      </div>;
    })}
    {shared.length > 0 && <p className="manual-badge__warn">{t('manual.shared', {
      keys: shared.map(([key, ids]) => `${keyLabel(key)} (${ids.join(', ')})`).join(' · '),
    })}</p>}
  </aside>;
}
