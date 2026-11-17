/**
 * src/views/ArmKeysBadge.tsx (261117 신설 — 로봇팔 키보드 제어 알림)
 *
 * **화면 우측 상단 — 지금 키보드 제어가 켜진 로봇팔.** Go1 의 `ManualControlBadge` 와 같은 자리 · 같은 모양이다.
 * 카드를 닫고 다른 화면을 보면서 몰 때 어느 팔이 키를 받는지, 마지막 명령이 어떻게 됐는지를 여기서 본다.
 * 켜진 팔이 없으면 아무것도 안 그린다. 줄마다 끄기 버튼이 있다.
 */

import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { useArmEvents } from '../physical/armControl.ts';
import { armKeyConfig, enabledArmDevices, keysSharedWithGo1, setArmKeysEnabled, useArmKeysState } from '../physical/armKeys.ts';
import { useManualState } from '../physical/manualControl.ts';

export function ArmKeysBadge() {
  useLang();
  useArmKeysState();
  useManualState();
  const events = useArmEvents();
  const devices = enabledArmDevices();
  if (devices.length === 0) return null;
  const shared = keysSharedWithGo1();
  return <aside className="manual-badge" aria-live="polite">
    {devices.map((deviceId) => {
      const event = events[deviceId];
      const blocked = event?.tone === 'bad';
      return <div key={deviceId} className={blocked ? 'manual-badge__row manual-badge__row--blocked' : 'manual-badge__row'}>
        <span className="manual-badge__dot" aria-hidden="true" />
        <div>
          <b>{t('arm.badge.line', { id: deviceId })}</b>
          <small>{t(`arm.keys.mode.${armKeyConfig(deviceId).mode}`)}{event !== undefined && <> · {event.line}</>}</small>
        </div>
        <button type="button" onClick={(clicked) => { setArmKeysEnabled(deviceId, false); clicked.currentTarget.blur(); }}>{t('manual.badge.off')}</button>
      </div>;
    })}
    {shared.length > 0 && <p className="manual-badge__warn">{t('arm.keys.shared', {
      keys: shared.map((item) => `${item.key} (${item.devices.join(', ')})`).join(' · '),
    })}</p>}
  </aside>;
}
