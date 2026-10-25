// verify:layer-time-agree (261025 신설 — 액션 층 시각 · 결정 ③ 뒤에 더한 셋째 검사)
//
// **같은 명령의 층별 시각이 맞는가.**
//
// 지시서가 찾은 그림이 이것이었다 — 판 `260929/204133_MSN-260929-02` 에서 같은 `turn` 이 사람 층 37.8초,
// 태스크 층 37.8초, 액션 층 0초. 그리고 문 찾기 편 11판에서는 사람 층과 액션 층이 **둘 다** 48초에 깎여
// 태스크 층(65.7초)과 갈렸다. 사람 층의 같은 자름(`recordHuman`)도 이번에 걷었다(결정 ③).
//
// ## 이 검사가 뜻이 있으려면 도구부터 고쳐야 했다
//
// 문 찾기 판을 모는 `lib/pi7Run.mjs` 가 「임무 시작」을 안 누르고 응답 시각을 3초로 박아 넣었다. 그 판의
// 명령은 0초, 응답·태스크는 3초 — **결함이 검사 안에서 매번 재현되고 있었다.** 지금 그 도구는 시작을
// 누르고 앱의 귀(`useRobotUplink`)처럼 `elapsedSec()` 를 단다. 이 검사는 그 도구가 시작을 눌렀는지도 본다.
//
// 보는 것.
//   door  ① 응답이 칠한 태스크 사건은 그 응답과 **같은 시각**이다 — 태스크 `started` 마다 같은 태스크의
//           응답이 같은 초에 있다
//         ② 명령은 제 응답보다 늦지 않다(`commanded ≤ 첫 answered`)
//   local ③ 사람이 누른 일시정지(사람 층)와 장비에 나간 일시정지(액션 층)가 **같은 초**다
//         ④ 그 명령의 응답도 같은 축이다 — 명령보다 이르지 않다
//
// 대조군 — `recordHuman` 의 자름을 되돌린 사본(사람 층만 축 끝에 깎인다) · 응답이 시계 안 선 0을 그대로
// 받는 사본(`robotBridge.ts` 가 `atSec` 을 늘 넘긴다).
import { checkWithControls, fmt, of } from './lib/actionTimeCheck.mjs';

function judge({ door, local }) {
  const bad = [];
  if (!door.started) bad.push('문 찾기 판을 모는 도구가 「임무 시작」을 안 눌렀다 — 그 판의 시각은 비교할 수 없다');

  // ① 응답이 칠한 태스크 사건 — 같은 초에 같은 태스크의 응답이 있어야 한다.
  const answers = of(door, 'action', 'answered');
  const startedTasks = of(door, 'task', 'started');
  if (startedTasks.length === 0) bad.push('문 찾기 판에 태스크 started 가 없다 — 비교할 재료가 없다');
  for (const t of startedTasks) {
    if (!answers.some((a) => a.taskId === t.taskId && a.atSec === t.atSec)) {
      const near = answers.filter((a) => a.taskId === t.taskId).map((a) => fmt(a.atSec)).join(',');
      bad.push(`문 찾기: ${t.taskId} started ${fmt(t.atSec)}초에 같은 태스크의 응답이 없다 (응답: ${near || '없음'})`);
    }
  }
  // ② 명령은 제 응답보다 늦지 않다.
  for (const c of of(door, 'action', 'commanded')) {
    const first = answers.find((a) => a.commandId === c.commandId);
    if (first !== undefined && c.atSec > first.atSec) bad.push(`문 찾기: ${c.action} 명령 ${fmt(c.atSec)}초가 제 응답 ${fmt(first.atSec)}초보다 늦다`);
  }

  // ③ 같은 순간의 누름과 바이트 — 일시정지는 순서도에 자리가 없는 명령이다(`no-node`).
  const press = of(local, 'human', 'mission_paused')[0];
  const pause = of(local, 'action', 'commanded').find((c) => c.taskId === 'no-node');
  if (press === undefined || pause === undefined) bad.push('장치 두 대 판에 일시정지 누름이나 명령이 없다');
  else if (press.atSec !== pause.atSec) bad.push(`장치 두 대: 같은 일시정지가 사람 층 ${fmt(press.atSec)}초 · 액션 층 ${fmt(pause.atSec)}초`);
  // ④ 명령마다 그 응답 — 태스크가 달린 명령(`T-E3 turn`)의 응답은 `robotBridge.ts` 가 적는다.
  if (!local.walked) bad.push('장치 두 대 판에서 태스크 명령이 안 나갔다 — robotBridge 길을 못 본다');
  for (const c of of(local, 'action', 'commanded')) {
    const lines = of(local, 'action', 'answered').filter((x) => x.commandId === c.commandId);
    if (lines.length === 0) bad.push(`장치 두 대: ${c.action} 명령에 응답이 없다`);
    for (const a of lines) {
      if (a.atSec < c.atSec) bad.push(`장치 두 대: ${c.action} 응답 ${fmt(a.atSec)}초가 명령 ${fmt(c.atSec)}초보다 이르다`);
    }
  }
  return bad;
}

checkWithControls('verify:layer-time-agree', {
  judge,
  boards: ['door', 'local'],
  controls: [
    {
      name: 'recordHuman 의 자름을 되돌린 사본',
      prefix: '.verify-layertime-',
      file: 'src/data/scenario.ts',
      from: '    liveNowSec(),\n    payload,\n  );',
      to: '    Math.min(liveNowSec(), state.current.durationSec),\n    payload,\n  );',
    },
    {
      name: '응답이 시계 안 선 0을 그대로 받는 사본',
      prefix: '.verify-layertime-',
      file: 'src/physical/robotBridge.ts',
      from: '      atSec: commandClockSec() === null ? undefined : atSec,',
      to: '      atSec,',
    },
  ],
});
console.log('✅ verify:layer-time-agree — 같은 명령이 사람 층 · 액션 층 · 태스크 층에서 같은 축에 놓인다');
