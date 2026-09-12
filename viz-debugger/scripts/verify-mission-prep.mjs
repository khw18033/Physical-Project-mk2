// verify:mission-prep (260912 신설 — 「임무 시작을 누르면 바로 돈다」)
//
// **로봇이 돌기 전에 해야 할 두 가지가 있다.**
//
//   T-A1  2D 맵에서 문 위치 확인
//   T-A2  로봇 현재 위치와 각도 파악
//   T-A3  로봇이 1바퀴 돈다      ← 위의 둘 **뒤**에 오는 일이다
//
// 260912 실측: 「임무 시작」을 누르는 순간 로봇이 돌기 시작했고, 앞의 두 노드에는 **한 바퀴
// 다 돌고 나서** 완료가 떴다. 화면이 임무의 순서를 거꾸로 보여 준 것이다.
//
// 막으려는 실패 넷.
//
//  1. **눌렀는데 곧바로 돈다** — 준비 창이 없으면 `T-A1`·`T-A2` 가 진행 중인 동안 로봇이 돈다
//  2. **준비 중에 각도가 열린다** — 시료의 박자가 시작 시계를 쓰면, 로봇이 서 있는 동안
//     결과가 먼저 뜬다. **안 본 방향의 답이 먼저 나온다**
//  3. **정지했는데 나중에 돈다** — 준비 창이 타이머라, 그 타이머가 정지에 안 걸리면
//     멈춘 뒤에 창이 닫히면서 스캔이 나간다. 가장 위험한 실패다
//  4. **앞의 둘을 각도 결과로 끝냈다고 한다** — 그러면 이미 돌고 있는 중에 완료가 뜬다.
//     자세 역산(`localization_evidence.json`)이 그 둘의 근거다
//
// 대조군 포함.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const sample = (...p) => JSON.parse(readFileSync(join(root, '..', 'door_example', 'test', ...p), 'utf8'));
const strip = (t) => t.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
const src = (...p) => strip(readFileSync(join(root, 'src', ...p), 'utf8'));

const failures = [];
const controls = [];

const session = await load('src', 'physical', 'robotSession.ts');
const { shouldIssueScan } = await load('src', 'physical', 'robotCommands.ts');
const { sampleRevealed } = await load('src', 'detect', 'DetectClient.ts');
const { PREP_SEC, afterPrep } = session;

// ── 1. 준비 창이 닫히기 전에는 스캔이 안 나간다 ─────────────────────────────
{
  if (!(PREP_SEC > 0)) failures.push(`준비 창이 ${PREP_SEC}초다 — 0이면 누르는 즉시 돈다`);

  session.resetRobotSession();
  session.setConnection({ state: 'open' });
  session.markApproved();

  // 승인만으로는 안 돈다 (260912 지시 — 이미 걸려 있는 관문).
  if (shouldIssueScan()) failures.push('승인만으로 스캔이 나간다 — 시작 버튼이 있는 이유가 없어진다');

  session.markStarted();
  if (!session.robotSession().started) failures.push('시작이 안 걸렸다 — 검사가 헛돈다');
  if (session.robotSession().prepared) failures.push('누르자마자 준비가 끝났다고 한다');
  if (shouldIssueScan()) {
    failures.push('시작을 누르자마자 스캔이 나간다 — T-A1·T-A2 가 진행 중인데 로봇이 돈다');
  }

  session.finishPrep();
  if (!session.robotSession().prepared) failures.push('준비 창이 안 닫힌다');
  if (!shouldIssueScan()) failures.push('준비가 끝났는데 스캔이 안 나간다 — 로봇이 영영 안 돈다');
}

// ── 2. 준비 중에는 각도가 안 열린다 ─────────────────────────────────────────
//
// 시료의 박자가 **시작 시계**를 쓰면 로봇이 서 있는 동안 결과가 뜬다. 준비 창을 뺀
// 시계를 써야 첫 각도가 로봇이 돌기 시작한 뒤에 온다.
{
  if (afterPrep(0) !== 0) failures.push('시작 직후의 스캔 시계가 0이 아니다');
  if (afterPrep(PREP_SEC) !== 0) failures.push('준비가 막 끝난 순간의 스캔 시계가 0이 아니다');
  if (afterPrep(PREP_SEC + 4) !== 4) failures.push(`준비 뒤 4초가 ${afterPrep(PREP_SEC + 4)} 로 온다`);
  // 준비 중에는 한 각도도 안 열린다.
  for (const at of [0, 1, PREP_SEC - 0.1, PREP_SEC]) {
    if (sampleRevealed(afterPrep(at), 8) !== 0) {
      failures.push(`준비 중(${at}초)에 각도가 열린다 — 안 본 방향의 답이 먼저 뜬다`);
    }
  }
  if (sampleRevealed(afterPrep(PREP_SEC + 4), 8) !== 1) failures.push('돌기 시작하고 4초에 첫 각도가 안 온다');

  // 폴링이 실제로 그 시계를 쓰는가 — 함수만 있고 안 쓰면 소용이 없다.
  const poll = src('detect', 'poll.ts');
  if (!/scanElapsedSec\(\)/.test(poll)) failures.push('폴링이 시작 시계로 각도를 연다 — 준비 중에 결과가 뜬다');
  if (/fetchSummary\(source, 'door', elapsedSec\(\)\)/.test(poll)) {
    failures.push('폴링이 아직 elapsedSec 으로 각도를 연다');
  }
}

// ── 3. 정지하면 준비 창도 끊긴다 ────────────────────────────────────────────
//
// **가장 위험한 실패다.** 멈춘 뒤에 창이 닫히면서 스캔이 나가면, 누른 사람은 멈춘 줄 알고
// 로봇에 다가가 있다.
{
  session.resetRobotSession();
  session.setConnection({ state: 'open' });
  session.markApproved();
  session.markStarted();
  session.lockStopped(true, null);          // 정지가 하는 3번 — 타이머 정지
  session.finishPrep();                     // 창이 닫혀도
  if (shouldIssueScan()) failures.push('정지한 뒤에 스캔이 나간다 — 멈춘 줄 알고 다가간 사람이 있다');

  // 일시정지도 같다 — 멈춰 있는데 창이 닫혔다고 돌면 안 된다.
  session.resetRobotSession();
  session.setConnection({ state: 'open' });
  session.markApproved();
  session.markStarted();
  session.lockPaused('T-A3', true, null);
  session.finishPrep();
  const paused = session.robotSession().paused !== null;
  if (!paused) failures.push('일시정지가 안 걸렸다 — 검사가 헛돈다');

  // 「처음부터」는 준비 창도 처음으로 되돌린다.
  session.resetRobotSession();
  session.setConnection({ state: 'open' });
  session.markApproved();
  session.markStarted();
  session.finishPrep();
  session.clearStarted();
  if (session.robotSession().prepared) failures.push('처음으로 되돌렸는데 준비가 끝나 있다 — 다음 판에서 곧바로 돈다');
  if (shouldIssueScan()) failures.push('처음으로 되돌렸는데 스캔이 나간다');

  session.resetRobotSession();              // 타이머를 남기지 않는다
}

// ── 4. 앞의 둘은 자세 역산으로 끝난다 ───────────────────────────────────────
//
// 각도 결과로 끝내면 **이미 돌고 있는 중에** 완료가 뜬다. 자세는 스캔 결과와 다른 파일에
// 있고 먼저 온다.
{
  const evidence = sample('unidepth_localization', 'localization_evidence.json');
  // 재료가 실제로 있어야 검사가 헛돌지 않는다.
  if (evidence.door_position_cm_fixed_from_gt === undefined) failures.push('시료에 문의 도면 위치가 없다 — 검사가 헛돈다');
  if (evidence.robot_position_cm === undefined) failures.push('시료에 로봇 위치가 없다 — 검사가 헛돈다');
  if (evidence.current_heading_map_deg === undefined) failures.push('시료에 로봇 방위가 없다 — 검사가 헛돈다');

  const trace = src('detect', 'detectTrace.ts');
  if (!/door_position_cm_fixed_from_gt/.test(trace)) {
    failures.push('T-A1 이 문의 도면 위치를 안 본다 — 각도 결과로 끝내면 이미 돌고 있는 중에 완료가 뜬다');
  }
  if (!/current_heading_map_deg/.test(trace)) failures.push('T-A2 가 로봇 방위를 안 본다');
  // 진행 중 표시가 있어야 준비 창이 빈 시간으로 안 보인다.
  if (!/'T-A1', 'running'/.test(trace)) failures.push('준비 중에 T-A1 이 진행 중으로 안 뜬다 — 그 몇 초가 빈 화면이 된다');

  const client = src('detect', 'DetectClient.ts');
  if (!/unidepth_localization\/localization_evidence\.json/.test(client)) {
    failures.push('자세 역산을 읽는 자리가 없다');
  }
}

// ── 5. 2D 맵은 경로 전후로 다른 그림이다 (260912 지시) ──────────────────────
//
// 도면은 임무 내내 있는 것이다. 경로가 없다고 그 자리를 비워 두면 발표 초반 내내 빈 상자다.
// 바뀌는 시점은 `T-B1` 의 완료와 **같은 값**에 걸려 있어야 한다 — 두 군데서 따로 판단하면
// 노드는 초록인데 그림은 그대로인 날이 온다.
{
  const { mapImageUrl, pathImageUrl, sourceOf } = await load('src', 'detect', 'DetectClient.ts');
  const at = sourceOf(true);
  if (mapImageUrl(at) === pathImageUrl(at)) failures.push('경로 전후의 그림이 같다 — 바뀌는 것이 안 보인다');
  if (!/map_original\.jpg$/.test(mapImageUrl(at))) failures.push(`기본 도면이 ${mapImageUrl(at)} 다`);
  if (!/path_overlay\.jpg$/.test(pathImageUrl(at))) failures.push(`경로 그림이 ${pathImageUrl(at)} 다`);

  const views = src('detect', 'views', 'DetectViews.tsx');
  if (!/mapImageUrl\(source\)/.test(views)) failures.push('경로 전에 도면을 안 그린다 — 그 자리가 빈 상자가 된다');
  if (!/path === null/.test(views)) failures.push('그림을 바꾸는 기준이 경로가 아니다');

  // 그림이 바뀌는 값과 T-B1 이 끝나는 값이 같은가.
  const trace = src('detect', 'detectTrace.ts');
  if (!/state\.path !== null.*T-B1/s.test(trace)) {
    failures.push('T-B1 이 경로로 끝나지 않는다 — 노드와 그림이 다른 순간에 바뀐다');
  }
}

// ── 6. 이동 버튼이 어느 화면에 있든 보인다 ──────────────────────────────────
//
// 260912 실측: 「산출된 경로에 따라 이동 직전에서 막힘」. 버튼이 `RobotPanel` 안에 있었고,
// 그 패널은 **마일스톤 목록 화면에만** 있다. 마지막 마일스톤이 끝나면 화면이 다음
// 마일스톤의 노드 그래프로 저절로 넘어가는데 거기에는 패널이 없다 — 경로까지 다 나왔는데
// **누를 것이 아무 데도 없었다.**
//
// 정지·일시정지·재시작과 같은 자리에 둔다. 연결이 없어도 감추지 않는다(정지와 같은 규칙).
{
  const panel = src('physical', 'RobotPanel.tsx');
  if (/canApproach\(\)/.test(panel)) {
    failures.push('이동 버튼이 아직 패널 안에 있다 — 노드 그래프로 넘어가면 사라진다');
  }
  const button = src('physical', 'StopButton.tsx');
  if (!/export function ApproachButton/.test(button)) failures.push('머리줄에 이동 버튼이 없다');
  if (/disabled/.test(button)) failures.push('머리줄 버튼을 비활성화한다 — 누르게 하고 못 보냈다고 말해야 한다');
  if (!/못 보냈습니다/.test(button)) failures.push('못 보낸 것을 버튼 자리에 안 적는다');
  for (const bar of [src('shell', 'AppShell.tsx'), src('views', 'TopBar.tsx')]) {
    if (!/<ApproachButton \/>/.test(bar)) failures.push('머리줄이 이동 버튼을 안 건다 — 어느 화면에서는 안 보인다');
  }
  // 머리줄의 `.global-bar button` 이 더 구체적이라, 클래스만 쓰면 초록이 안 뜬다.
  const css = readFileSync(join(root, 'src', 'style.css'), 'utf8');
  if (!/button\.robot-approach\{/.test(css)) {
    failures.push('이동 버튼 모양에 button. 이 없다 — 머리줄에서 흰 버튼으로 묻힌다');
  }

  const { issueApproach } = await load('src', 'physical', 'robotCommands.ts');
  session.resetRobotSession();
  session.markApproved();
  const outcome = await issueApproach(null, null);
  if (outcome?.sent !== false) failures.push('연결 없이 냈는데 보냈다고 한다');
  if (!outcome?.reason) failures.push('못 보낸 사유가 없다 — 발표자가 원인을 모른다');
  session.resetRobotSession();
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
  controls.push(name);
}
{
  // **준비 창이 없는 사본.** 시작 시계를 그대로 쓰면 4초에 첫 각도가 열린다 —
  // 로봇은 아직 서 있다.
  control('준비 창을 안 뺀 사본 (elapsed 를 그대로)', sampleRevealed(4, 8) === 1 && sampleRevealed(afterPrep(4), 8) === 0);
}
{
  // **준비를 참으로 박아 둔 사본.** 누르는 즉시 관문이 열린다.
  session.resetRobotSession();
  session.setConnection({ state: 'open' });
  session.markApproved();
  session.markStarted();
  const blocked = !shouldIssueScan();
  session.finishPrep();
  control('준비를 건너뛴 사본 (prepared 를 안 보는 관문)', blocked && shouldIssueScan());
  session.resetRobotSession();
}
{
  // **각도 결과로 앞의 둘을 끝내는 사본.** 첫 각도는 로봇이 이미 돈 뒤에 온다.
  const trace = src('detect', 'detectTrace.ts');
  const onlyFrames = /if \(state\.frames\.length > 0\) \{\s*put \+= emit\(missionId, 'T-A1'/.test(trace);
  control('각도 결과로 T-A1 을 끝내는 사본', !onlyFrames);
}

if (failures.length) {
  console.error(`❌ verify:mission-prep\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 시작을 눌러도 준비 창(${PREP_SEC}초)이 닫히기 전에는 스캔이 안 나간다 — T-A1·T-A2 가 먼저다`);
console.log('✅ 준비 중에는 한 각도도 안 열린다 — 로봇이 서 있는 동안 안 본 방향의 답이 뜨지 않는다');
console.log('✅ 정지·일시정지·처음으로가 준비 창을 같이 끊는다 — 멈춘 뒤에 창이 닫혀도 안 돈다');
console.log('✅ T-A1·T-A2 는 자세 역산으로 끝난다 (문의 도면 위치 · 로봇 위치와 방위)');
console.log('✅ 2D 맵은 경로 전후로 다른 그림이고, 바뀌는 값이 T-B1 의 완료와 같다');
console.log('✅ 이동 버튼이 머리줄에 있어 어느 화면에서도 보이고, 연결이 없어도 눌린다');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
