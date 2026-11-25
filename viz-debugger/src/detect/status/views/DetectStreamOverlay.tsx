/**
 * src/detect/status/views/DetectStreamOverlay.tsx (261124 신설 — 객체 탐지 상태판 상세)
 *
 * **판의 카드(또는 모델 칩)를 더블클릭하면 뜨는 창.** 하드웨어 카드 상세의 객체 탐지 칸과 **같은 부품**(`VisionCam` →
 * `VisionCell`)을 쓴다 — 그래서 녹화 · 잘라내기, 근거 카드, 영역 지정, 재식별, 원본 나란히, 요약 표가 그대로 된다(요구 4).
 * 다른 것은 포트를 장비 묶음이 아니라 **카드가 준 포트로 연다**는 것 하나다(`fixedBase`) — 장비 없이도 열린다.
 *
 * 고름 저장 키는 `ds:<포트>` 다. 하드웨어 상세(`hw:<장비>`)와 나눈 것은, 여기서 모델을 바꿔도 장비 상세의 고름이 안 바뀌게
 * 하려는 것이다.
 *
 * 하드웨어 상세 · 전체 장치 확인과 **형제로 얹고 동시에 하나만** 연다(`main.tsx` — VZ-N-05 와 같은 규칙). 탭은 없다.
 */

import { useEffect } from 'react';
import { t } from '../../../i18n/dict.ts';
import { useLang } from '../../../shared/language.ts';
import { holdVisionSource } from '../../../vision/store.ts';
import { setVisionNodeChoice } from '../../../vision/nodeChoice.ts';
import { VisionCam } from '../../../vision/views/VisionViews.tsx';
import { useDetectHistory } from '../history.ts';
import { holdLatest } from '../latestStore.ts';
import { TARGETED } from '../summary.ts';
import { holdPlacement, usePlacement } from '../placement.ts';
import { DetectHistoryList, PlacementSection, TargetLine } from './DetectStatusParts.tsx';
import { useDetectRows } from './DetectModelPanel.tsx';

export function detectNodeId(base: string): string {
  return `ds:${base}`;
}

export function DetectStreamOverlay({ base, model, onClose }: { base: string; model: string | null; onClose(): void }) {
  useLang();
  // 상세가 열린 포트는 1초마다(판은 2초).
  useEffect(() => holdVisionSource(base), [base]);
  // 모델 칩을 더블클릭해 열었으면 그 모델 하나만 고른 채로 연다. 카드 빈 곳이면 고름을 건드리지 않는다(지난번 고름 · 자동).
  useEffect(() => { if (model !== null) setVisionNodeChoice(detectNodeId(base), { models: [model] }); }, [base, model]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  const { rows, infos } = useDetectRows();
  const row = rows.find((item) => item.base === base) ?? null;
  const info = infos[base] ?? null;
  // 판이 내려가 있어도(다른 화면) 대상은 읽는다.
  useEffect(() => holdLatest(base, row?.source ?? null, TARGETED), [base, row?.source]);
  const history = useDetectHistory();
  // 실행 장치 — 판이 내려가 있어도 읽는다(261125).
  useEffect(() => holdPlacement(), []);
  const placement = usePlacement();

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="modal dms-overlay" role="dialog" aria-label={t('dms.detailTitle', { name: row?.source ?? base })}>
      <header>
        <div>
          <h2>{t('dms.detailTitle', { name: row?.source ?? base })}</h2>
          <small><code>{base}</code>{row !== null && row.devices.length > 0 ? ` · ${t('dms.boundTo', { devices: row.devices.join(', ') })}` : ` · ${t('dms.noDevice')}`}</small>
        </div>
        <button type="button" onClick={onClose}>{t('dso.1')}</button>
      </header>
      <div className="dms-overlay__body">
        <div className="dms-overlay__main">
          <VisionCam nodeId={detectNodeId(base)} fixedBase={base} zoom />
        </div>
        <div className="dms-overlay__side">
          <PlacementSection row={row} state={placement} />
          {info !== null
            ? <TargetLine info={info} />
            : <section className="dms-sec"><h3>{t('dms.tg.title')}</h3><p className="vn-line vn-dim">{t('dms.tg.none')}</p></section>}
          <DetectHistoryList history={history} base={base} />
        </div>
      </div>
      <footer><span>{t('dms.detailFooter')}</span></footer>
    </section>
  </div>;
}
