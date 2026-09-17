/**
 * src/shell/ModeSwitch.tsx (260831 신설 — 사이트 개선 요구 4)
 *
 * 우상단 **모드 표시·전환** — `모드 [일반] [시나리오 ▾] [목·개발]`.
 *
 * 지금까지 모드가 세 군데에 흩어져 있었다(목 토글 · 승인 자동 진입 · 배너 안의 닫기).
 * 이 스위치가 그 셋을 한 자리에 모은다 — 지금 무엇을 보고 있는지가 세그먼트로 보이므로
 * 화면의 설명 문단이 줄어든다(요구 1).
 *
 * **승인 선을 우회하지 않는다** — 시나리오를 고르면 「그린다」까지다(정지 미리보기 ·
 * t=0 프레임). 재생은 여전히 VZ-U-07 승인 뒤이고, 그 사실이 상태 문구(`정지`/`재생 중`)로
 * 구분되어 보인다. 셸에만 있다 — 탭① 단독 빌드는 게이트웨이가 없으므로 이 스위치도 없다.
 */

import { useEffect, useRef, useState } from 'react';
import { enterScriptPreview } from '../scenarios/enterPreview.ts';
import { SCRIPT_LIBRARY } from '../scenarios/library.ts';
import { issueCommand } from '../shared/commandEgress.ts';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import {
  exitScenarioRender,
  setRenderMode,
  useRenderMode,
  useScenarioRender,
} from '../shared/renderMode.ts';

export function ModeSwitch() {
  const mode = useRenderMode();
  // **`t()` 는 부르는 순간의 언어를 줄 뿐 다시 그리게 하지 않는다.** 이 훅이 그 일을 한다 —
  // 빼면 언어를 바꿔도 이 부품만 옛 문구로 남는다 (영문화 1단계 §4).
  useLang();
  const scenario = useScenarioRender();
  const [menuOpen, setMenuOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  // 드롭다운 밖을 누르면 닫는다 — 메뉴가 열린 채로 남으면 스위치가 상태 표시 구실을 못 한다.
  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: PointerEvent) => {
      if (rootRef.current !== null && !rootRef.current.contains(event.target as Node)) setMenuOpen(false);
    };
    window.addEventListener('pointerdown', close);
    return () => window.removeEventListener('pointerdown', close);
  }, [menuOpen]);

  const toNormal = () => {
    setMenuOpen(false);
    setRenderMode('placeholder');
    if (scenario !== null) {
      // 게이트웨이가 재생·미리보기를 멈추고 장치를 평시로 되돌린다. 실패해도 화면은 복귀한다.
      void issueCommand({ action: 'script_close', entity: scenario.missionId }).catch(() => undefined);
      exitScenarioRender();
    }
  };

  // 진입 네 단계는 scenarios/enterPreview.ts 하나에 있다 — 접힘 카드의 「그 대본으로
  // 바꾸기」가 같은 경로를 부른다(두 벌로 만들지 않는다, 260901).
  const toPreview = (missionId: string) => {
    setMenuOpen(false);
    enterScriptPreview(missionId);
  };

  const toMock = () => {
    setMenuOpen(false);
    setRenderMode('mock');
  };

  const scenarioLabel =
    scenario === null
      ? t('mode.scenario')
      : t('mode.scenarioOn', {
          id: scenario.missionId.replace('MSN-', ''),
          state: scenario.playing ? t('mode.playing') : t('mode.stopped'),
        });

  return (
    <div className="modeswitch" role="group" aria-label={t('mode.aria')} ref={rootRef}>
      {/* 시범 키 ① 단순 라벨 (영문화 1단계 §4). `useLang()` 이 있어야 전환 때 다시 그린다. */}
      <span className="modeswitch__label">{t('mode.label')}</span>
      <button
        type="button"
        className={'modeswitch__seg' + (mode === 'placeholder' ? ' modeswitch__seg--on' : '')}
        onClick={toNormal}
      >
        {t('mode.normal')}
      </button>
      <div className="modeswitch__drop">
        <button
          type="button"
          className={'modeswitch__seg' + (mode === 'scenario' ? ' modeswitch__seg--on modeswitch__seg--scenario' : '')}
          onClick={() => setMenuOpen((open) => !open)}
          title={t('mode.scenarioTitle')}
        >
          {scenarioLabel}
        </button>
        {menuOpen && (
          <ul className="modeswitch__menu">
            {SCRIPT_LIBRARY.filter((entry) => entry.script !== null).map((entry) => (
              <li key={entry.missionId}>
                <button type="button" onClick={() => toPreview(entry.missionId)}>
                  <b>{entry.missionId}</b> {entry.script?.title}
                </button>
              </li>
            ))}
            <li className="modeswitch__menunote">{t('mode.menuNote')}</li>
          </ul>
        )}
      </div>
      <button
        type="button"
        className={'modeswitch__seg' + (mode === 'mock' ? ' modeswitch__seg--on modeswitch__seg--mock' : '')}
        onClick={toMock}
        title={t('mode.mockTitle')}
      >
        {/* 시범 키 ⑤ — **`en.ts` 에 일부러 없다.** 영문 화면에서 이 버튼만 한국어로 남고
            콘솔에 한 줄이 찍히면 fallback 이 도는 것이다 (영문화 1단계 §4). */}
        {t('mode.mock')}
      </button>
    </div>
  );
}
