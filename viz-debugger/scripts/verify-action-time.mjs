// verify:action-time (261025 신설 — 액션 층 시각 · 지시서 §4 첫째)
//
// **액션 층 시각이 0이나 축 끝으로 깎이지 않는가.**
//
// 보관 113판 중 명령이 있는 37판에서 이렇게 갈렸다.
//
//   생성 임무 `MSN-Q-*` 11판      `durationSec` 0 에 자름 → 명령·응답 전부 0초
//   장치 두 대 `MSN-260929-02` 13판 시계가 안 선 판의 `elapsedSec()` 0 → 전부 0초
//   문 찾기 `MSN-260909-01` 13판    0은 없지만 544건 중 232건이 축 끝 48초에 깎임(11판)
//
// 원인은 `scenario.ts` 의 `Math.min(at, durationSec)`(260904 사람 층 지킴이를 260921 에 옮긴 줄)과,
// 명령 기록이 탐지용 시계(`elapsedSec`, 시작 전 0)를 그대로 쓴 것이었다. 고친 뒤에는 명령 기록이
// `commandClockSec()`(모르면 `null`)를 읽고, `null` 은 `liveNowSec()` 가 그 판의 축으로 푼다.
//
// 보는 것 — 세 판을 실제 기록 길로 몬다(`lib/actionTimeProbe.mjs`).
//   gen   `durationSec` 0 인데 시작 150 ms 뒤에 나간 명령과 그 응답이 0초가 아니다
//   local 시작 없이 축이 60초(축 끝 52초 너머)에 선 판 — 액션 층이 60초에 놓인다. 0도 52도 아니다
//   door  시작을 누른 판 — 명령이 0초에 몰리지 않는다(첫 명령 뒤로 시각이 는다)
//
// 대조군 셋 — `src/` 를 통째로 복사해 한 줄 바꾼 트리로 같은 판을 몬다(LF 정규화 원본에서).
//   `Math.min` 을 되돌린 사본 · `elapsedSec` 의 0을 주는 사본 · 기록이 명령 시계를 안 받는 사본
import { checkWithControls, fmt, of } from './lib/actionTimeCheck.mjs';

function judge({ gen, local, door }) {
  const bad = [];
  if (gen.durationSec !== 0) bad.push(`생성 임무 판의 durationSec 이 ${gen.durationSec} — 0이어야 이 판이 뜻이 있다`);
  const genAct = of(gen, 'action');
  if (genAct.length === 0) bad.push('생성 임무 판에 액션 층 사건이 없다');
  for (const e of genAct) if (!(e.atSec > 0.1)) bad.push(`생성 임무: ${e.kind} 가 ${fmt(e.atSec)}초 — 시작 150 ms 뒤에 나갔다. 0으로 깎였다`);

  if (local.started) bad.push('장치 두 대 판이 시작돼 있다 — 시계가 안 선 판을 몰아야 한다');
  const localAct = of(local, 'action');
  if (localAct.length === 0) bad.push('장치 두 대 판에 액션 층 사건이 없다');
  for (const e of localAct) {
    if (e.atSec !== local.head) bad.push(`장치 두 대: ${e.kind} 가 ${fmt(e.atSec)}초 — 축은 ${local.head}초다${e.atSec === 0 ? ' (시계가 안 선 0)' : e.atSec === local.durationSec ? ' (축 끝에 깎임)' : ''}`);
  }

  if (!door.started) bad.push('문 찾기 판을 모는 도구가 「임무 시작」을 안 눌렀다 — 그 판은 결함을 재현하는 판이다');
  const cmds = of(door, 'action', 'commanded');
  if (cmds.length < 3) bad.push(`문 찾기 판의 명령이 ${cmds.length}건 — 셋 이상이어야 시각이 느는지 본다`);
  const last = cmds.at(-1);
  if (last !== undefined && !(last.atSec > cmds[0].atSec)) bad.push(`문 찾기: 명령 ${cmds.length}건이 전부 ${fmt(cmds[0].atSec)}초 — 시각이 안 는다`);
  return bad;
}

checkWithControls('verify:action-time', {
  judge,
  boards: ['gen', 'local', 'door'],
  controls: [
    {
      name: 'Math.min 을 되돌린 사본',
      prefix: '.verify-actiontime-',
      file: 'src/data/scenario.ts',
      from: '  return Math.max(0, atSec ?? liveNowSec());',
      to: '  return Math.max(0, Math.min(atSec ?? liveNowSec(), state.current.durationSec));',
    },
    {
      name: 'elapsedSec 의 0을 주는 사본 (시계가 안 서도 값을 낸다)',
      prefix: '.verify-actiontime-',
      file: 'src/physical/robotSession.ts',
      from: '  if (!robotDrives() || session.startedAtMs === null) return null;\n  return elapsedSec();',
      to: '  return elapsedSec();',
    },
    {
      name: '기록이 명령 시계를 안 받는 사본 (재생 머리로만 떨어진다)',
      prefix: '.verify-actiontime-',
      file: 'src/data/scenario.ts',
      from: '  return Math.max(0, commandClockSec() ?? state.headSec);',
      to: '  return Math.max(0, state.headSec);',
    },
  ],
});
console.log('✅ verify:action-time — 액션 층 시각이 0 · 축 끝에 깎이지 않는다');
