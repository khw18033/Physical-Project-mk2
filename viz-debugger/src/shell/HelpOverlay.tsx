/**
 * src/shell/HelpOverlay.tsx (260831 신설 — 사이트 개선 요구 1)
 *
 * 우상단 `?` — **지금 보고 있는 것의 설명서만** 팝업으로 보인다 (사용자 결정 4).
 *
 * 260903(3단계 — 탭 제거)에 「현재 켜진 탭」이 **「캔버스, 또는 확대가 열려 있으면 그 노드」**
 * 가 됐다. 지시서 §3이 지목한 셸 5개소 중 넷째다. 판정 재료는 캔버스의 확대 상태 하나
 * (`canvas/zoomState.ts`)이고 셸은 읽기만 한다 — 셸이 캔버스 안을 알면 탭을 걷어낸 뜻이 없다.
 *
 * 내용은 각 화면의 `<Explain>` 이 자기 자리에서 등록한 문단들이다 — 글의 원본은
 * 여전히 그 컴포넌트 안에 있고, 여기는 모아 보여줄 뿐이다(요구 1 「자리만 옮긴다」).
 */

import { Fragment, useState } from 'react';
import { manualEntries, useManualVersion, type ManualScopeId } from '../shared/Explain.tsx';
import { setDevToolsVisible, useDevTools } from '../shared/renderMode.ts';
import { t } from '../i18n/dict.ts';
import { Rich } from '../i18n/RichText.tsx';
import { useLang } from '../shared/language.ts';

/**
 * 제목과 한 줄 요약은 **사전에 있다** (260917 — 영문화 2단계). 여기 표를 두면 모듈 최상위
 * 상수라 `t()` 가 로드 시점에 굳는다(지시서 §2 ②) — 키는 `scope` 값에서 바로 만든다.
 */

export function HelpOverlay({ scope }: { scope: ManualScopeId }) {
  useLang();
  const [open, setOpen] = useState(false);
  const devTools = useDevTools();
  useManualVersion(); // 확대 열고 닫기·마운트로 목록이 바뀌면 다시 그린다.

  return (
    <>
      <button type="button" className="help-btn" title={t('help.btn')} onClick={() => setOpen(true)}>?</button>
      {open && (
        <div className="help-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
          <section className="help-modal" role="dialog" aria-label={t('help.aria')}>
            <header>
              <div>
                <h2>{t(`help.scope.${scope}`)}</h2>
                <p>{t(`help.summary.${scope}`)}</p>
              </div>
              <button type="button" onClick={() => setOpen(false)}>{t('help.close')}</button>
            </header>

            <div className="help-body">
              {manualEntries(scope).map((entry) => (
                <Fragment key={entry.id}>
                  <div className="help-entry">{entry.read()}</div>
                </Fragment>
              ))}
              {manualEntries(scope).length === 0 && <p className="help-empty">{t('help.empty')}</p>}

              <h3>{t('help.modes.title')}</h3>
              <ul className="help-modes">
                <li><Rich id="help.modes.normal" /></li>
                <li><Rich id="help.modes.scenario" /></li>
                <li><Rich id="help.modes.mock" /></li>
              </ul>

              {scope === 'canvas' && (
                <>
                  <h3>{t('help.approval.title')} <small>(BE-X-04)</small></h3>
                  <p className="help-note"><Rich id="help.approval.p1" /></p>
                  <p className="help-note"><Rich id="help.approval.p2" /></p>
                  <p className="help-note"><Rich id="help.approval.p3" /></p>
                  <p className="help-note"><Rich id="help.approval.p4" /></p>
                </>
              )}

              <h3>{t('help.scenario.title')} <small>(2026-09-01)</small></h3>
              <p className="help-note"><Rich id="help.scenario.p1" /></p>
              <p className="help-note"><Rich id="help.scenario.p2" /></p>
              <h3>{t('help.pending.title')}</h3>
              <ul className="help-modes">
                <li><Rich id="help.pending.pool" /></li>
                <li><Rich id="help.pending.history" /></li>
                <li><Rich id="help.pending.registry" /></li>
              </ul>

              <label className="help-devtoggle">
                <input type="checkbox" checked={devTools} onChange={(event) => setDevToolsVisible(event.target.checked ? true : null)} />
                {t('help.devtoggle')}
              </label>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
