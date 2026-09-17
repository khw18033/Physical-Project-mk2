/**
 * src/i18n/ko.ts — 한국어 사전 (260916 — 영문화 1단계 §2)
 *
 * **평평한 객체 하나.** 중첩하지 않는다 — 키에 점이 들어 있으니 구조는 이름이 진다.
 * `en.ts` 와 같은 모양이어야 한다.
 *
 * 지금은 **시범 키 다섯**뿐이다. 2단계에서 시연 경로 문구가 여기로 들어온다.
 */

export const ko: Record<string, string> = {
  // ① 단순 라벨 — 우상단 모드 스위치
  'mode.label': '모드',

  // ② 치환이 있는 문장 — 영어는 어순이 반대라 조각을 이어붙이면 옮길 수 없다
  'check.robot.stale': '{sec}초째 소식이 없습니다 — 마지막 값을 현재로 보지 않습니다',

  // ③ 긴 오류 문장 — 좁은 판에서 줄바꿈이 레이아웃을 깨는지 본다
  'conn.storageBlocked': '저장소가 막혀 있습니다 — 바꿔도 이번 세션에만 적용되고 새로고침하면 기본값으로 돌아갑니다.',

  // ④ 열거형 라벨 — PLANE_LABEL (DF-1b)
  'plane.business': '업무 평면',
  'plane.control': '업무 평면 (제어)',
  'plane.observability': '관측 평면',
  'plane.media': '미디어 평면',

  // ⑤ en 을 일부러 비운 키 — fallback 이 실제로 도는지 눈으로 본다
  'mode.mock': '목·개발',

  // ── 2단계 · 시연 경로 ──────────────────────────────────────────────────────
  // **원문 그대로 옮긴다.** 다듬고 싶어도 이번에는 옮기기만 한다 (지시서 §4).

  // 태스크 상태 8종 — `device.status.*` 와 **다른 것**이다 (용어집 §2 ◆)
  'task.state.pending': '대기',
  'task.state.running': '진행',
  'task.state.done': '완료',
  'task.state.failed': '실패',
  'task.state.skipped': '건너뜀',
  'task.state.awaiting_evaluation': '평가 대기',
  'task.state.not_executed': '미수행',
  'task.state.rerunning': '재실행',

  // 그래프 머리줄 — 「트리」라는 말이 들어가면 안 된다
  'shape.dag': '태스크 DAG — {parts}',
  'shape.nodes': '{n}노드',
  'shape.merges': '합류 {n}',
  'shape.loops': '되돌아감 {n}',
  'shape.linear': '일직선',

  // 연결 표시등 — 「모른다」와 「빨갛다」는 다르다
  'lamp.unknown': '연결 미확인 — 누르면 연결 관리',
  'lamp.broken': '{target} {line} 끊김 — 누르면 연결 관리',
  'lamp.partial': '연결 {ok}/{total} · 미확인 {unknown}',
  'lamp.ok': '연결 {ok}/{total} 확인됨',

  // 캔버스 저장 — 실패해도 화면은 돈다. 그 사실을 한 줄로 적는다
  'canvas.readFailed': '저장된 캔버스 구성을 읽지 못해 기본 구성으로 시작합니다.',
  'canvas.shapeChanged': '저장된 캔버스 구성의 모양이 달라 기본 구성으로 시작합니다.',
  'canvas.oldVersion': '저장된 캔버스 구성이 옛 판(v{version})이라 버리고 기본 구성으로 시작합니다.',
  'canvas.lostTasks': '연결했던 태스크 {tasks} 가 지금 대본에 없어 전역 노드로 두었습니다 (지우지 않았습니다).',
  'canvas.notSaved': '이 브라우저에서는 캔버스 구성이 저장되지 않습니다 — 새로고침하면 기본 구성으로 돌아갑니다.',
  'canvas.notSavedShort': '이 브라우저에서는 캔버스 구성이 저장되지 않습니다 — 화면은 그대로 동작합니다.',

  // 확대 오버레이 — 「캔버스를 교체하지 않는다」가 요지다
  'zoom.noTarget': '대상 없음',
  'zoom.globalNode': '전역 노드 · 임무 전체 구간',
  'zoom.close': '닫기 (Esc)',
  'zoom.note': '확대는 캔버스를 교체하지 않습니다 — 뒤에 그대로 있고, 닫으면 같은 자리입니다.',

  // 팔레트
  'palette.title': '뷰 노드',
  'palette.placeGlobal': '전역 노드로 놓입니다',
  'palette.placeLinked': '{task} 에 연결된 채로 놓입니다',
  'palette.resetTitle': '이 마일스톤의 캔버스 구성을 기본으로 되돌립니다',
  'palette.notInScript': '· 이 대본엔 없음',
  'palette.linkTarget': '연결 대상',
  'palette.reset': '기본 구성으로 되돌리기',

  // 뷰 노드 카드
  'viewnode.noRenderer': '이 빌드에는 렌더러가 없어 확대할 것이 없습니다',
  'viewnode.zoomTitle': '확대 (더블클릭도 같습니다) — 캔버스는 뒤에 그대로 있습니다',
  'viewnode.unlink': '연결을 끊고 전역 노드로',
  'viewnode.pickTaskFirst': '연결할 태스크를 먼저 고르세요 (태스크를 한 번 누릅니다)',
  'viewnode.linkTo': '{task} 에 연결',
  'viewnode.remove': '이 뷰 노드를 캔버스에서 지웁니다',
  'viewnode.noTarget': '대상 없음',
  'viewnode.global': '전역',
  'viewnode.rendererMissing': '이 빌드에는 렌더러가 없습니다 — 통합 앱에서 보입니다.',

  // 재시작·초기화
  'zoom.aria': '{label} 확대',
  'zoom.linkedTo': '◂ {task} 에 연결됨',
  'zoom.head': '재생 머리 T+{sec}s',
  'reset.restartTitle': '이 임무를 처음부터 다시 돌립니다 — 발화와 승인을 다시 하지 않아도 됩니다',
  'reset.resetTitle': '임무·진행·여덟 칸을 비웁니다. 브로커 연결은 그대로 남습니다',
  'reset.restart': '↻ 처음부터',
  'reset.reset': '↺ 초기화',
  'reset.confirm': '정말 초기화 — 이 판을 버립니다',
  'reset.cancel': '취소',

  // 팔레트 툴팁 · 뷰 노드 카드 (2차)
  'palette.hintUnused': '{hint} — 이 대본은 이 노드를 쓰지 않습니다 (놓아서 확인할 수 있습니다)',
  'palette.hintGlobal': '{hint} — 전역 노드로 놓입니다',
  'palette.hintLinked': '{hint} — {task} 에 연결된 채로 놓입니다',
  'viewnode.scopeTitle': '이 태스크의 대상·구간이 이 노드의 조회 범위입니다 ({span})',
  'viewnode.globalTitle': '연결하지 않은 전역 노드 — 임무 전체 구간을 봅니다',
  'viewnode.rendererMissingFor': '이 빌드에는 {kind} 렌더러가 없습니다 — 통합 앱에서 보입니다.',

  // 연결 관리 판
  'conn.title': '⇄ 연결 관리',
  'conn.close': '닫기',
  'conn.applied': '적용했습니다 — 게이트웨이 주소가 바뀌었으면 끊고 새 주소로 다시 붙습니다.',
  'conn.appliedSession': '이번 세션에만 적용했습니다 — 저장소가 막혀 있어 새로고침하면 기본값으로 돌아갑니다.',
  'conn.restored': '기본값으로 되돌렸습니다.',
  'conn.pendingBadge': '연결 예정',
  'conn.presetUndecided': ' (미정)',
  'conn.placeholderPending': '상대가 정해지면 열립니다',
  'conn.restore': '기본값 복원',
  'conn.apply': '적용',
  'conn.notChecked': '아직 확인하지 않았습니다',
  'conn.testTitle': '탐지 담당이 준 실제 산출물을 진짜 결과처럼 읽습니다',
  'conn.test': '테스트',
  'conn.checking': '확인 중…',
  'conn.check': '확인',

  // 모드 스위치
  'mode.normal': '일반',
  'mode.scenario': '시나리오 ▾',
  'mode.scenarioOn': '시나리오 · {id} {state} ▾',
  'mode.playing': '재생 중',
  'mode.stopped': '정지',
  'mode.aria': '렌더 모드',
  'mode.scenarioTitle': '대본을 고르면 정지 미리보기로 들어갑니다. 재생은 여전히 승인(VZ-U-07) 뒤입니다',
  'mode.menuNote': '정지 미리보기 — 재생은 승인 뒤 (VZ-U-07)',
  'mode.mockTitle': '남이 줄 데이터 자리에 목을 그립니다. 켜져 있는 동안 붉은 배지가 유지됩니다',

  // 상단 바 · 배너
  'conn.state.open': '게이트웨이 연결됨',
  'conn.state.reconnecting': '재연결 중',
  'conn.state.connecting': '연결 중',
  'conn.state.closed': '연결 종료',
  'conn.attempts': ' ({n}회)',
  'bar.subtitle': '통합 가시화 · 노드 캔버스',
  'bar.history': '◷ 임무 이력',
  'bar.notifications': '알림',
  'bar.connections': '⇄ 연결 관리',
  'banner.mock': '목 렌더 켜짐 — 남의 데이터 자리가 {strong}입니다. 시연 전에 끄세요.',
  'banner.mock.strong': '전부 지어낸 값',
  'banner.legacy': '구판 세계 대본({id}) — 구역 장비와 연결되지 않아 탭②~⑤는 따라 움직이지 않습니다 (7.8 예외)',
  'banner.script': '대본',
  'banner.synthetic': '합성 데이터',
  'banner.castNote': '— cast 밖 장비는 자리표시',
  'banner.now': '지금:',
  'banner.gotoNode': '{label} 노드로',
  'banner.close': '대본 닫기',
  'script.ended': '재생 끝 — 마지막 상태',
  'script.preview': '정지 미리보기',
  'panel.history': '임무 이력',
  'panel.notifications': '통합 알림',
  'panel.close': '닫기',
  'panel.noNotifications': '아직 올라온 알림이 없습니다',

  // 정지·일시정지·시작·접근
  'stop.stopTitle': '로봇을 멈추고 임무를 끝냅니다 — 진행상황이 종결되고 다시 승인해야 합니다',
  'stop.stop': '■ 정지',
  'stop.pauseTitle': '로봇을 멈추되 진행상황은 그대로 둡니다 — 재시작하면 그 단계를 다시 합니다',
  'stop.paused': '⏸ 멈춰 있음',
  'stop.pause': '⏸ 일시정지',
  'stop.resumeNavTitle': '일시정지를 풀고 pi1 중계를 다시 칠합니다 — 로봇에는 아무것도 보내지 않습니다',
  'stop.noApproved': '승인된 임무가 없습니다 — 먼저 승인하세요',
  'stop.startNavTitle': '승인된 자율주행 임무를 지금 시작합니다 — 이때부터 pi1 중계를 노드에 칠합니다(로봇은 유니티가 몹니다)',
  'stop.restartTitle': '멈춰 있던 단계를 다시 냅니다 — 로봇에 이어 하기가 없어 그 단계를 처음부터 합니다',
  'stop.startTitle': '승인된 임무를 지금 시작합니다 — 이 버튼을 누르기 전에는 로봇이 움직이지 않습니다',
  'stop.restart': '▶ 재시작',
  'stop.start': '▶ 임무 시작',
  'stop.nothingToSend': '낼 명령이 없습니다',
  'stop.approachTitle': '경로 산출이 낸 회전과 직진을 차례로 냅니다 — 회전이 끝나야 직진이 나갑니다',
  'stop.busy': '▶ 로봇이 하는 중 — 앞 명령이 끝나기를 기다립니다',
  'stop.approach': '▶ 경로대로 이동',
  'stop.sendFailed': '▶ 못 보냈습니다 — {reason}',
};
