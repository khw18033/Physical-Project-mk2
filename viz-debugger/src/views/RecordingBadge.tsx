/**
 * src/views/RecordingBadge.tsx (261007 신설 — 녹화 중 알림)
 *
 * **화면 우측 상단 — 지금 녹화 중인 영상.** 수동 제어 알림(`ManualControlBadge`)과 같은 자리 · 같은 모양이고 그 아래에
 * 쌓인다(`.corner-alerts`). 줄마다 정지 버튼이 있다 — 창을 다시 열지 않고 멈출 수 있어야 한다. 끝난 녹화는 저장된
 * 경로를 잠깐 보이고 사라진다. 실패는 사람이 닫을 때까지 남긴다.
 */

import { useEffect, useState } from 'react';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { dismissRecording, isActive, stopRecording, useRecordings } from '../record/screenRecord.ts';
import { formatElapsed } from '../record/RecordFrame.tsx';

function mb(bytes: number): string {
  return (bytes / (1024 * 1024)).toFixed(1);
}

export function RecordingBadge() {
  useLang();
  const items = useRecordings();
  const [, setTick] = useState(0);
  const running = items.some((item) => item.phase === 'recording');
  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(() => setTick((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, [running]);
  if (items.length === 0) return null;
  return <aside className="rec-badge" aria-live="polite">
    {items.map((item) => <div key={item.id} className={`rec-badge__row rec-badge__row--${item.phase}`}>
      <span className="rec-badge__dot" aria-hidden="true" />
      <div>
        <b>{item.phase === 'recording' || item.phase === 'starting'
          ? t('rec.badge.line', { label: item.label })
          : item.phase === 'saving' ? t('rec.badge.saving', { label: item.label })
          : item.phase === 'saved' ? t('rec.badge.saved', { label: item.label })
          : t('rec.badge.failed', { label: item.label })}</b>
        <small>
          {item.phase === 'starting' ? t('rec.badge.asking')
            : item.phase === 'recording' ? t('rec.badge.meta', { elapsed: formatElapsed(Date.now() - item.startedAtMs), mb: mb(item.bytes) })
            : item.phase === 'saved' ? t('rec.badge.path', { path: item.path ?? '', mb: mb(item.bytes) })
            : item.phase === 'failed' ? item.error ?? ''
            : null}
          {item.phase !== 'failed' && item.error !== null ? <> · <em>{item.error}</em></> : null}
        </small>
      </div>
      {isActive(item)
        ? <button type="button" disabled={item.phase === 'saving'} onClick={(event) => { void stopRecording(item.id); event.currentTarget.blur(); }}>{t('rec.badge.stop')}</button>
        : <button type="button" onClick={() => dismissRecording(item.id)}>{t('rec.badge.dismiss')}</button>}
    </div>)}
  </aside>;
}
