/**
 * src/detect/scan/DetectSourceSwitch.tsx (261123 신설 — 스캔 탐지를 data_stream 으로 · S9)
 *
 * 연결 판 「탐지」 줄의 **탐지 방식** 고르기. 옛 탐지기(`:8000`) 편과 data_stream 편 중 어느 쪽이 발화 매칭에 서는가.
 */

import { useEffect } from 'react';
import { t } from '../../i18n/dict.ts';
import { useLang } from '../../shared/language.ts';
import { DETECT_SOURCE_MODES, type DetectSourceMode } from '../../scenarios/detectSource.ts';
import { changeDetectSource, pullDetectSource, useDetectSource, useDetectSourceSync } from './detectSourceSync.ts';

export function DetectSourceSwitch() {
  useLang();
  const mode = useDetectSource();
  const sync = useDetectSourceSync();
  useEffect(() => { void pullDetectSource(); }, []);
  return <label className="conn-test" title={t('sd.source.title')}>
    {t('sd.source.label')}{' '}
    <select value={mode} onChange={(event) => { void changeDetectSource(event.target.value as DetectSourceMode); }}>
      {DETECT_SOURCE_MODES.map((option) => <option key={option} value={option}>{t(`sd.source.${option}`)}</option>)}
    </select>
    {!sync.synced && <small> {t('sd.source.local')}</small>}
    {sync.blockedKey !== null && <small> {t(sync.blockedKey)}</small>}
  </label>;
}
