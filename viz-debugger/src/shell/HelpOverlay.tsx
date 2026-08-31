/**
 * src/shell/HelpOverlay.tsx (260831 신설 — 사이트 개선 요구 1)
 *
 * 우상단 `?` — **현재 켜진 탭의 설명서만** 팝업으로 보인다 (사용자 결정 4).
 * 탭을 여섯으로 되돌리지 않는다 — 사용자가 지금 보고 있는 화면의 설명만 필요하다.
 *
 * 내용은 각 화면의 `<Explain>` 이 자기 자리에서 등록한 문단들이다 — 글의 원본은
 * 여전히 그 컴포넌트 안에 있고, 여기는 모아 보여줄 뿐이다(요구 1 「자리만 옮긴다」).
 */

import { Fragment, useState } from 'react';
import { manualEntries, useManualVersion, type ManualScopeId } from '../shared/Explain.tsx';
import { setDevToolsVisible, useDevTools } from '../shared/renderMode.ts';

const TAB_TITLE: Record<ManualScopeId, string> = {
  debugger: '① 임무 설계 및 디버깅',
  overview: '② 구역 현황판',
  control: '③ 제어 패널',
  metrics: '④ 지표 조회',
  video: '⑤ 영상 오버레이',
  shell: '상단 공통 바',
};

/** 탭별 한 줄 요약 — 손으로 쓴다 (지시서 §우상단 ? 오버레이). */
const TAB_SUMMARY: Record<ManualScopeId, string> = {
  debugger: '발화로 임무를 만들고, 마일스톤 → 태스크 그래프 → 액션으로 실행을 되짚는 본류 화면.',
  overview: '구역 장치의 상태 3층(자기보고·가용성·배포)과 위험도, 구역 맵 미니뷰를 카드로 본다.',
  control: '수동 제어 발행과 명령 4단계(발행→ACK→진행→완료) 추적, 감사 이력 조회.',
  metrics: '요약·원본 두 경로의 지표 질의 — 지금 보는 값이 요약인지 원본인지가 항상 표기된다.',
  video: '영상 위 탐지 박스·궤적 정합 — 프레임 참조가 없으면 박스가 어긋난다는 것을 실측한다.',
  shell: '임무 이름·임무 제어·알림. 공통 명령은 단일 출구로 나가고 게이트웨이도 하나다.',
};

export function HelpOverlay({ tab }: { tab: ManualScopeId }) {
  const [open, setOpen] = useState(false);
  const devTools = useDevTools();
  useManualVersion(); // 탭 전환·마운트로 목록이 바뀌면 다시 그린다.

  return (
    <>
      <button type="button" className="help-btn" title="현재 탭의 설명서" onClick={() => setOpen(true)}>?</button>
      {open && (
        <div className="help-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
          <section className="help-modal" role="dialog" aria-label="화면 설명서">
            <header>
              <div>
                <h2>{TAB_TITLE[tab]}</h2>
                <p>{TAB_SUMMARY[tab]}</p>
              </div>
              <button type="button" onClick={() => setOpen(false)}>닫기</button>
            </header>

            <div className="help-body">
              {manualEntries(tab).map((entry) => (
                <Fragment key={entry.id}>
                  <div className="help-entry">{entry.read()}</div>
                </Fragment>
              ))}
              {manualEntries(tab).length === 0 && <p className="help-empty">이 탭에 등록된 설명이 없습니다.</p>}

              <h3>모드 — 우상단 스위치</h3>
              <ul className="help-modes">
                <li><b>일반</b> — 기본값. 남이 줄 데이터 자리는 「연결 예정(무엇을·누구에게서)」 카드로 뜬다. 무엇이 아직 안 왔는지가 화면에 드러난다.</li>
                <li><b>시나리오</b> — 대본을 골라 <b>정지 미리보기</b>(t=0 화면)로 들어간다. <b>재생은 여전히 승인(VZ-U-07) 뒤다.</b> 발화 → 매칭 → 승인으로 들어오면 「재생 중」이 된다. 대본 등장 장비만 그려지고, 대본에 없는 축은 「이 대본에는 해당 없음」으로 갈린다.</li>
                <li><b>목·개발</b> — 남이 줄 데이터 자리에 그럴듯한 목을 그린다. 붉은 배지가 유지되며 <b>시연 중에는 켜지 말 것.</b> 개발 도구(시나리오 재생 버튼·계약 확인)도 이 모드에서 보인다.</li>
              </ul>

              <label className="help-devtoggle">
                <input type="checkbox" checked={devTools} onChange={(event) => setDevToolsVisible(event.target.checked ? true : null)} />
                개발 도구 표시 (시나리오 재생 버튼 · 계약 확인 · 리렌더 카운터) — 기본은 목·개발 모드에서만
              </label>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
