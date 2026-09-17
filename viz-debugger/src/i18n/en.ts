/**
 * src/i18n/en.ts — 영어 사전 (260916 — 영문화 1단계 §2)
 *
 * **여기 적힌 영어는 전부 가안이다.** 0단계 용어집이 확정되면 바뀐다 (지시서 §5).
 *
 * `ko.ts` 와 같은 모양의 평평한 객체. **`ko` 에 있는 키가 여기 없어도 된다** —
 * 없으면 한국어로 떨어지고 콘솔에 한 줄 남는다(`dict.ts`). 4단계까지 1,249줄을 다 못
 * 옮긴다는 전제로 설계한 것이다.
 */

export const en: Record<string, string> = {
  // ① 단순 라벨
  'mode.label': 'Mode',

  // ② 치환이 있는 문장 — **어순이 한국어와 반대다.**
  //    ko 는 「{sec}초째 … 않습니다」로 숫자가 앞, en 은 'No signal for {sec}s' 로 뒤다.
  //    조각을 이어붙이는 방식이었다면 이 한 줄이 불가능했다 (지시서 §2 ③).
  'check.robot.stale': 'No signal for {sec}s — the last value is not treated as current',

  // ③ 긴 오류 문장 — 한국어보다 길다. 좁은 판에서 몇 줄이 되는지가 2단계에 알아야 할 것이다
  'conn.storageBlocked': 'Storage is blocked — changes apply to this session only and revert to defaults on refresh.',

  // ④ 열거형 라벨
  'plane.business': 'Business plane',
  'plane.control': 'Business plane (control)',
  'plane.observability': 'Observability plane',
  'plane.media': 'Media plane',

  // ⑤ `mode.mock` 은 **일부러 비워 둔다.** 지우지 마라 — 이 빈자리가 시범 키 다섯째다.
  //    영문 화면에서 이 버튼만 「목·개발」로 남고 콘솔에 한 줄이 찍히면 fallback 이 도는 것이다.

  // ── 2단계 · 시연 경로 ──────────────────────────────────────────────────────

  // 태스크 상태 8종.
  //
  // **`대기` 를 `Pending` 으로 옮기지 않았다.** 용어집이 `Pending` 을 **자리표시**(남이 줄
  // 데이터를 기다리는 자리)에 고정해 놨다 — 같은 화면에서 태스크가 `Pending` 이고 데이터 칸도
  // `Pending` 이면 서로 다른 두 가지가 같은 말이 된다. 태스크 쪽은 `Waiting` 이다.
  'task.state.pending': 'Waiting',
  'task.state.running': 'Running',
  'task.state.done': 'Done',
  'task.state.failed': 'Failed',
  'task.state.skipped': 'Skipped',
  'task.state.awaiting_evaluation': 'Awaiting evaluation',
  'task.state.not_executed': 'Not executed',
  'task.state.rerunning': 'Re-running',

  // 그래프 머리줄 — 「tree」라고 쓰지 않는다. 합류와 되돌아감이 트리로 안 되는 바로 그것이다
  'shape.dag': 'Task DAG — {parts}',
  'shape.nodes': '{n} nodes',
  'shape.merges': '{n} merges',
  'shape.loops': '{n} loops',
  'shape.linear': 'linear',

  // 연결 표시등
  'lamp.unknown': 'Connections unchecked — click to manage',
  'lamp.broken': '{target} {line} down — click to manage',
  'lamp.partial': 'Connected {ok}/{total} · unchecked {unknown}',
  'lamp.ok': 'Connected {ok}/{total}',

  // 캔버스 저장
  'canvas.readFailed': 'Could not read the saved canvas layout — starting from the default.',
  'canvas.shapeChanged': 'The saved canvas layout has a different shape — starting from the default.',
  'canvas.oldVersion': 'The saved canvas layout is an old version (v{version}) — discarding it and starting from the default.',
  'canvas.lostTasks': 'Tasks {tasks} are no longer in this script, so their nodes were left as global nodes (not deleted).',
  'canvas.notSaved': 'This browser does not save the canvas layout — a refresh returns to the default.',
  'canvas.notSavedShort': 'This browser does not save the canvas layout — the screen still works.',

  // 확대 오버레이
  'zoom.noTarget': 'No target',
  'zoom.globalNode': 'Global node · whole mission',
  'zoom.close': 'Close (Esc)',
  'zoom.note': 'Zooming does not replace the canvas — it stays behind, and closing returns you to the same place.',

  // 팔레트
  'palette.title': 'View nodes',
  'palette.placeGlobal': 'Placed as a global node',
  'palette.placeLinked': 'Placed linked to {task}',
  'palette.resetTitle': 'Reset this milestone’s canvas layout to the default',
  'palette.notInScript': '· not in this script',
  'palette.linkTarget': 'Link target',
  'palette.reset': 'Reset to default layout',

  // 뷰 노드 카드
  'viewnode.noRenderer': 'This build has no renderer, so there is nothing to zoom into',
  'viewnode.zoomTitle': 'Zoom (double-click does the same) — the canvas stays behind',
  'viewnode.unlink': 'Unlink and make global',
  'viewnode.pickTaskFirst': 'Pick a task first (click a task once)',
  'viewnode.linkTo': 'Link to {task}',
  'viewnode.remove': 'Remove this view node from the canvas',
  'viewnode.noTarget': 'No target',
  'viewnode.global': 'Global',
  'viewnode.rendererMissing': 'This build has no renderer — it appears in the integrated app.',

  // 재시작·초기화
  'zoom.aria': '{label} zoomed',
  'zoom.linkedTo': '◂ linked to {task}',
  'zoom.head': 'playhead T+{sec}s',
  'reset.restartTitle': 'Run this mission again from the start — no need to repeat the utterance and approval',
  'reset.resetTitle': 'Clears the mission, progress and the eight slots. The broker connection stays',
  'reset.restart': '↻ From the start',
  'reset.reset': '↺ Reset',
  'reset.confirm': 'Reset — this run will be discarded',
  'reset.cancel': 'Cancel',

  // 팔레트 툴팁 · 뷰 노드 카드 (2차)
  'palette.hintUnused': '{hint} — this script does not use this node (you can still place it to check)',
  'palette.hintGlobal': '{hint} — placed as a global node',
  'palette.hintLinked': '{hint} — placed linked to {task}',
  'viewnode.scopeTitle': 'This node reads the target and time span of that task ({span})',
  'viewnode.globalTitle': 'Unlinked global node — reads the whole mission span',
  'viewnode.rendererMissingFor': 'This build has no {kind} renderer — it appears in the integrated app.',

  // 연결 관리 판
  'conn.title': '⇄ Connections',
  'conn.close': 'Close',
  'conn.applied': 'Applied — if the gateway address changed, it reconnects to the new one.',
  'conn.appliedSession': 'Applied for this session only — storage is blocked, so a refresh returns to the defaults.',
  'conn.restored': 'Restored the defaults.',
  'conn.pendingBadge': 'Pending',
  'conn.presetUndecided': ' (undecided)',
  'conn.placeholderPending': 'Opens once the counterpart is decided',
  'conn.restore': 'Restore defaults',
  'conn.apply': 'Apply',
  'conn.notChecked': 'Not checked yet',
  'conn.testTitle': 'Reads the real output handed over by the detection team as if it were a live result',
  'conn.test': 'Test',
  'conn.checking': 'Checking…',
  'conn.check': 'Check',

  // 모드 스위치
  'mode.normal': 'Normal',
  'mode.scenario': 'Scenario ▾',
  'mode.scenarioOn': 'Scenario · {id} {state} ▾',
  'mode.playing': 'playing',
  'mode.stopped': 'stopped',
  'mode.aria': 'Render mode',
  'mode.scenarioTitle': 'Picking a script enters a stopped preview. Playback still requires approval (VZ-U-07).',
  'mode.menuNote': 'Stopped preview — playback comes after approval (VZ-U-07)',
  'mode.mockTitle': 'Draws mock values where other teams’ data belongs. A red badge stays up while this is on',

  // 상단 바 · 배너
  'conn.state.open': 'Gateway connected',
  'conn.state.reconnecting': 'Reconnecting',
  'conn.state.connecting': 'Connecting',
  'conn.state.closed': 'Disconnected',
  'conn.attempts': ' ({n})',
  'bar.subtitle': 'Integrated view · node canvas',
  'bar.history': '◷ Mission history',
  'bar.notifications': 'Alerts',
  'bar.connections': '⇄ Connections',
  'banner.mock': 'Mock rendering is on — data from other teams is {strong}. Turn this off before a demo.',
  'banner.mock.strong': 'entirely made up',
  'banner.legacy': 'Legacy-world script ({id}) — it is not wired to zone devices, so tabs ②–⑤ do not follow (7.8 exception)',
  'banner.script': 'Script',
  'banner.synthetic': 'synthetic data',
  'banner.castNote': '— devices outside the cast stay pending',
  'banner.now': 'Now:',
  'banner.gotoNode': 'Go to {label} node',
  'banner.close': 'Close script',
  'script.ended': 'Playback ended — final state',
  'script.preview': 'Stopped preview',
  'panel.history': 'Mission history',
  'panel.notifications': 'Alerts',
  'panel.close': 'Close',
  'panel.noNotifications': 'No alerts yet',

  // 정지·일시정지·시작·접근
  'stop.stopTitle': 'Stops the robot and ends the mission — progress is closed and approval is needed again',
  'stop.stop': '■ Stop',
  'stop.pauseTitle': 'Stops the robot but keeps progress — restarting repeats that step',
  'stop.paused': '⏸ Paused',
  'stop.pause': '⏸ Pause',
  'stop.resumeNavTitle': 'Resumes and paints the pi1 relay again — nothing is sent to the robot',
  'stop.noApproved': 'No approved mission — approve one first',
  'stop.startNavTitle': 'Starts the approved autonomous-driving mission now — from here the pi1 relay paints the nodes (Unity drives the robot)',
  'stop.restartTitle': 'Re-issues the step that was paused — the robot cannot resume mid-step, so it starts that step over',
  'stop.startTitle': 'Starts the approved mission now — the robot does not move until this button is pressed',
  'stop.restart': '▶ Restart',
  'stop.start': '▶ Start mission',
  'stop.nothingToSend': 'No command to send',
  'stop.approachTitle': 'Issues the turn and the straight run from the path solver in order — the straight run waits for the turn',
  'stop.busy': '▶ Robot is busy — waiting for the previous command to finish',
  'stop.approach': '▶ Follow the path',
  'stop.sendFailed': '▶ Could not send — {reason}',
};
