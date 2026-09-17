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

  // ── 자리표시 20건 · 상대 요구사항 제목 61 · 파트명 ───────────────────────────
  //
  // **힘을 빼고 갔다** (지시서 §1). 자리표시는 남이 줄 데이터가 도착하면 사라지는 비계다 —
  // 키는 제대로 만들되 영어 문안 다듬기에 시간을 쓰지 않는다. 요구사항 제목은 상대 시트의
  // 소분류를 푼 것이고, **찾아갈 수 있는 원본은 ID(`HW-C-04` …) 쪽**이다.
  'pending.registry.title': 'Registry pending',
  'pending.registry.what': 'Target list · owning zone · node mapping · declared channels',
  'pending.role-scope.title': 'Role and scope pending',
  'pending.role-scope.what': 'The signed-in user’s role and the zones they cover',
  'pending.ai-failure-alert.title': 'External AI failure alerts pending',
  'pending.ai-failure-alert.what': 'Errors and anomalies from AI components (latency · inference failure · model anomaly)',
  'pending.zone-summary.title': 'Zone status roll-up pending',
  'pending.zone-summary.what': 'Roll-up of the four statuses across a zone’s targets (normal · fault · not deployed · undecidable)',
  'pending.device-cards.title': 'Device status pending',
  'pending.device-cards.what': 'Three status layers per target (self-report · availability · deployment) plus domain readings (battery · water level · fps · CPU · opening ratio)',
  'pending.zone-map.title': 'Zone map coverage pending',
  'pending.zone-map.what': 'Camera coverage over the zone plan (FOV projection) · blind-spot cells · last observation time per cell (freshness)',
  'pending.risk-state.title': 'Environmental risk verdict pending',
  'pending.risk-state.what': 'Risk level · score · rationale with contributions · recommended action',
  'pending.actuator-state.title': 'Actuator status pending',
  'pending.actuator-state.what': 'Motion stage · opening ratio · control lock and the reason for it',
  'pending.command-result.title': 'Command results pending',
  'pending.command-result.what': 'Acceptance · correlation key · execution progress · final outcome (four stages)',
  'pending.audit-history.title': 'Audit history pending',
  'pending.audit-history.what': 'Who · when · what · through which input method and decision maker',
  'pending.action-catalog.title': 'Available action list pending',
  'pending.action-catalog.what': 'The abstract actions issuable to this target right now, and which of them cannot be undone',
  'pending.metrics-query.title': 'Metrics query responses pending',
  'pending.metrics-query.what': 'Time series asked for by target, metric and span (summary / raw, two routes)',
  'pending.client-metrics-sink.title': 'Self-observability metric sink pending',
  'pending.client-metrics-sink.what': 'A collector to receive the 60-second roll-up this view measures on itself (trace rate · log capacity · fold time · receive latency)',
  'pending.metrics-push.title': 'Steady-state metric push pending',
  'pending.metrics-push.what': 'Observability metrics pushed on a schedule without a query, and how their aggregation layer is marked',
  'pending.video-stream.title': 'Video stream pending',
  'pending.video-stream.what': 'Control-room video pixels and frame identifiers',
  'pending.detections.title': 'Detection results pending',
  'pending.detections.what': 'Detection boxes · classes · confidence, and **which frame each box came from** (frame reference)',
  'pending.tracking.title': 'Object tracking and trajectories pending',
  'pending.tracking.what': 'Track identifier · trajectory · whether multiple observations were linked',
  'pending.mission-history.title': 'Mission history pending',
  'pending.mission-history.what': 'Past missions and their outcomes — the backend keeps them and we query and display them (decided 2026-08-31). The current mission’s trace log (the raw material for replay) is ours and is not part of this',
  'pending.robot-status-strip.title': 'Assigned-device measured status pending',
  'pending.robot-status-strip.what': 'Battery · signal strength · latency · IP · firmware · joint temperature · heartbeat',
  'pending.hardware-pool-status.title': 'Assignment-pool device status pending',
  'pending.hardware-pool-status.what': 'Connection status · battery · signal strength of candidate devices in the pool',
  'req.AI-C-03': 'Frame reference and time conventions',
  'req.AI-C-08': 'Media input management',
  'req.AI-C-14': 'Path separation by data type',
  'req.AI-E-01': 'Perception',
  'req.AI-E-04': 'Optional assistive function execution',
  'req.AI-N-01': 'Local safety judgement',
  'req.AI-O-01': 'Execution performance and resource observability',
  'req.AI-O-02': 'AI error and anomaly event logging',
  'req.AI-O-04': 'Execution availability signal linkage',
  'req.AI-R-02': 'Risk level and rationale state computation',
  'req.AI-R-03': 'Risk verdict and recommendation output',
  'req.AI-S-01': 'Object tracking',
  'req.AI-S-02': 'Multi-observation object linkage',
  'req.AI-S-03': 'Uncertainty and rationale-sufficiency assessment',
  'req.BE-A-01': 'Control command assembly and publication',
  'req.BE-A-02': 'Command validity and safety-condition checks',
  'req.BE-A-04': 'Risk-verdict-based control publication',
  'req.BE-C-01': 'Common message schema and field conventions',
  'req.BE-C-02': 'Identifier hierarchy (Entity/Node/Zone) conventions',
  'req.BE-C-03': 'Frame reference and time synchronisation conventions',
  'req.BE-C-05': 'Contract-axis and undeployed-target representation conventions',
  'req.BE-Q-01': 'Metrics query proxy',
  'req.BE-Q-02': 'Audit history query API',
  'req.BE-Q-03': 'Registry query API',
  'req.BE-Q-04': 'Role and scope lookup with access enforcement (RBAC)',
  'req.BE-S-01': 'Time-series and status history storage',
  'req.BE-S-02': 'OTel observability pipeline (Agent + Gateway)',
  'req.BE-S-03': 'Tiered observability storage (edge-local + federated summary)',
  'req.BE-S-05': 'Central audit storage (direct-to-MySQL exception)',
  'req.BE-S-06': 'Aggregation-layer boundary marking',
  'req.BE-T-03': 'Real-time channel gateway for visualisation clients (WebSocket)',
  'req.BE-T-04': 'Device registration, zone membership and availability management',
  'req.BE-T-05': 'Private-IP routing and proxy relay',
  'req.BE-T-06': 'Immediate current-value delivery on reconnect (backend cache)',
  'req.BE-X-01': 'Correlation key (command_id) issuance and mapping',
  'req.BE-X-02': 'Audit record writing (actor and timestamp injection)',
  'req.BE-X-03': 'Four-stage command result promotion',
  'req.BE-X-05': 'AI failure event relay',
  'req.DT-01': 'Twin coordinate fusion (uncertainty-weighted)',
  'req.DT-02': 'Bayesian class fusion',
  'req.DT-04': 'Coverage map and blind-spot computation',
  'req.DT-05': 'Twin staleness verdict',
  'req.HW-A-01': 'Actuator status collection',
  'req.HW-A-02': 'Actuator control command reception',
  'req.HW-A-03': 'Control command acknowledgement (ACK)',
  'req.HW-A-04': 'Actual execution result confirmation',
  'req.HW-A-05': 'Safe handling of link loss and abnormal states',
  'req.HW-C-04': 'Device status and zone registration management',
  'req.HW-C-05': 'Observability data (OpenTelemetry) instrumentation',
  'req.HW-C-06': 'Control command reception and ACK response',
  'req.HW-C-07': 'device_id-based device identification and edge-node mapping',
  'req.HW-R-02': 'Heartbeat transmission',
  'req.HW-R-03': 'Status data delivery',
  'req.HW-R-04': 'Environment-perception imagery and on-device recognition',
  'req.HW-R-05': 'Mission (subtask) reception',
  'req.HW-R-07': 'High-resolution control-room video stream (on demand)',
  'req.HW-S-02': 'Measurement data delivery (steady state)',
  'req.HW-S-03': 'High-rate reporting in event mode',
  'req.HW-S-05': 'Sensor node (Raspberry Pi) heartbeat',
  'req.HW-S-06': 'Fixed vision sensor (CCTV) video delivery',
  'req.HW-S-07': 'Offline detection and status reflection',
  'part.hardware': 'Hardware',
  'part.ai': 'AI',
  'part.backend': 'Backend',

  // 평면 설명 (DF-1b)
  'plane.business.note': 'MQTT/Kafka business data path',
  'plane.control.note': 'Business data, but under a separate policy needing delivery guarantees, ordering and accountability (AI-C-14)',
  'plane.observability.note': 'OTLP observability path — never mixed with the business broker',
  'plane.media.note': 'Never carried on the business or observability brokers (AI-C-14 · HW-R-07)',

  // 자리표시 카드 본문
  'pending.mark': 'Pending',
  'pending.what': 'What',
  'pending.from': 'From',
  'pending.ours': 'Our slot',
  'pending.path': 'Path',
  'pending.oursWhy': 'Ready to draw it the moment it arrives. This is not unbuilt — it is unreceived',
  'pending.noCounterpart': 'No counterpart — a meeting item',
  'pending.agenda': 'a meeting item',
  'pending.summary.from': 'From: {value}',
  'pending.summary.fromNone': 'From: no counterpart — {reason}',
  'pending.summary.what': 'What: {value}',
  'pending.summary.ours': 'Our slot: {value}',
  'pending.summary.path': 'Path: {label} — {note}',
  'pending.badge.mock': 'Mock — not real data',
  'pending.badge.script': 'Script — synthetic data',
  'pending.notInScript': 'Not applicable to this script',
  'pending.noScriptDrives': 'No script drives this axis — steady-state data ({parts}) belongs here.',
  'pending.partsUndecided': 'counterpart undecided',
  'pending.seenIn': 'Visible in {scripts}.',
  'pending.sizeKept': 'The slot keeps its size — switch scripts or return to normal mode and it drops right back in.',
};
