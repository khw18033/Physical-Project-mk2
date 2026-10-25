// verify:action-replay-generated (261025 신설 — 액션 층 시각 · 지시서 §4 둘째)
//
// **생성 임무에서 명령 층이 재생 머리를 따라가는가** — 과거 시점에는 그때까지 오간 것만 보인다.
//
// 기여 1 의 「세 층이 재실행 없이 되감긴다」가 생성 임무에서도 서는지 보는 자리다. 보관 생성 임무 11판은
// 액션 층이 전부 0초라, 재생 머리를 어디 두든 명령이 다 보였다. 접기 검사(`fold-actions` · `no-answer`)는
// 시각을 손으로 넣은 열을 접어서 그것을 못 봤다 — 이 검사는 **실제 기록 길로 쓴 열**을 접는다.
//
// 보는 것 — 정량 명령 한 편(`durationSec` 0)을 몰고(`lib/actionTimeProbe.mjs` 의 `gen`), 화면이 명령 표를
// 그릴 때 쓰는 `actionsAt()` 을 머리를 옮겨 가며 부른다.
//   ① 명령이 나가기 전 — 접힌 명령 0
//   ② 명령 뒤 · 수락 전 — 명령 1 · 응답 0
//   ③ 수락 뒤 · 종료 전 — 응답 1 · 아직 안 끝남
//   ④ 끝 — 응답 2 · 완료
//   ⑤ 머리가 갈 때 접힌 수가 줄지 않는다
//
// 대조군 — 시각을 0으로 적는 사본(`Math.min(…, durationSec)` 를 되돌린다 — 생성 임무는 축이 0이다).
import { checkWithControls } from './lib/actionTimeCheck.mjs';

function judge({ gen }) {
  const bad = [];
  const cmd = gen.events.find((e) => e.layer === 'action' && e.kind === 'commanded');
  const lines = gen.events.filter((e) => e.layer === 'action' && e.kind === 'answered' && e.commandId === cmd?.commandId);
  if (cmd === undefined || lines.length < 2) return ['생성 임무 판에 명령과 응답 둘이 없다 — 접을 재료가 없다'];
  const at = (sec) => gen.folds.filter((f) => f.at <= sec).at(-1) ?? { commands: 0, lines: 0, statuses: [] };
  // 증상 그대로 — 머리를 0초에 두었는데 끝난 명령이 보이면 되감기가 액션 층에서 안 먹는 것이다.
  const zero = at(0);
  if (zero.commands > 0) bad.push(`① 머리 0초에 명령 ${zero.commands}건 · 응답 ${zero.lines}줄이 접힌다 — 시작 150 ms 뒤에 나간 명령이다`);
  const before = gen.folds.filter((f) => f.at < cmd.atSec).at(-1);
  if (before === undefined) bad.push('명령 앞 시점의 접기가 없다');
  else if (before.commands !== 0) bad.push(`① 명령이 나가기 전(${before.at.toFixed(3)}초)에 명령 ${before.commands}건이 접힌다 — 되감기가 안 먹는다`);
  const issued = gen.folds.filter((f) => f.at >= cmd.atSec && f.at < lines[0].atSec).at(-1);
  if (issued === undefined || issued.commands !== 1 || issued.lines !== 0) bad.push(`② 명령 뒤 · 수락 전에 명령 1 · 응답 0 이어야 한다 — ${JSON.stringify(issued ?? null)}`);
  const accepted = gen.folds.filter((f) => f.at >= lines[0].atSec && f.at < lines[1].atSec).at(-1);
  if (accepted === undefined || accepted.lines !== 1 || accepted.statuses.includes('done')) bad.push(`③ 수락 뒤 · 종료 전에 응답 1 · 진행 중이어야 한다 — ${JSON.stringify(accepted ?? null)}`);
  const end = at(Infinity);
  if (end.lines !== 2 || !end.statuses.includes('done')) bad.push(`④ 끝에 응답 2 · 완료여야 한다 — ${JSON.stringify(end)}`);
  for (let i = 1; i < gen.folds.length; i += 1) {
    if (gen.folds[i].lines < gen.folds[i - 1].lines) bad.push(`⑤ 머리가 ${gen.folds[i - 1].at.toFixed(3)} → ${gen.folds[i].at.toFixed(3)}초로 갈 때 응답 줄이 줄었다`);
  }
  return bad;
}

checkWithControls('verify:action-replay-generated', {
  judge,
  boards: ['gen'],
  controls: [
    {
      name: '시각을 0으로 적는 사본 (축 끝 자름을 되돌림 · 생성 임무 축은 0)',
      prefix: '.verify-actionreplay-',
      file: 'src/data/scenario.ts',
      from: '  return Math.max(0, atSec ?? liveNowSec());',
      to: '  return Math.max(0, Math.min(atSec ?? liveNowSec(), state.current.durationSec));',
    },
  ],
});
console.log('✅ verify:action-replay-generated — 생성 임무에서도 명령 층이 재생 머리를 따라간다');
