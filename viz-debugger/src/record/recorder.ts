/**
 * src/record/recorder.ts (260914 신설 — 「새로고침하면 임무 이력이 다 날아간다」)
 *
 * **판마다 파일로 남긴다.** 리허설 기록이 디버깅에 쓰이는데, 지금까지는 새로고침 한 번에 전부
 * 사라졌다. DB 가 붙기 전까지 저장소 루트 `mission-history/<날짜>/<시각_임무>/` 에 쓴다
 * (창구 `scripts/mission-records.mjs`).
 *
 * ## 무엇을 남기나
 *
 *   mission.json    어떤 임무였나 — 임무 정의 전체(`view`) · 시작/끝 시각 · 결과 · 노드 셈 · 경로 요약
 *   progress.json   어떻게 진행됐나 — 기록 열 · 뷰포인트 프레임 · 로봇 명령과 응답 로그 · 탐지 결과와
 *                   근거 · 탐지 로그 · 준비 단계 값 · 알림 · 로봇 촬영 목록
 *   images/detect   탐지가 내준 그림 — 각도 원본 · 상자 입힌 것 · 잘라낸 것 · 경로 그림 · 도면
 *                   (스캔 탐지 data_stream 편은 `scan_rot_<각도>_<종류>.jpg` — 261124)
 *   images/robot    로봇이 찍어 보낸 원본 (각도별)
 *
 * 다시보기(`loadRecord.ts`)가 이 둘을 도로 채워 **같은 화면**으로 그린다. 그래서 여기서 쓰는 모양이
 * 곧 저장소의 모양이다 — 따로 번역하지 않는다.
 *
 * ## 언제 쓰나
 *
 * - **바뀌었을 때마다** (1.5초 주기로 보고, 달라진 파일만). 끝 표시 없이 새로고침·충돌로 끊겨도
 *   거기까지는 남는다 — 리허설에서 알고 싶은 것이 바로 그런 판이다.
 * - **판이 끝났을 때 곧바로** (완료·실패·정지).
 * - **새 판이 서기 직전** (`sealRun`) — 새 임무·처음부터·초기화는 저장소를 비운다. 비우기 전에 뜬다.
 *
 * 폴더는 **무언가 일어난 뒤에야** 만든다 — 승인만 하고 끝낸 판까지 폴더가 생기면 목록이 빈 판으로 찬다.
 *
 * ## 그림
 *
 * 탐지 그림은 **탐지 창구가 새 판을 시작할 때 지운다.** 받은 즉시 떠 둔다. 아직 안 만들어진 그림(404)은
 * 다음 주기에 다시 시도하고, 여러 번 실패하면 그만둔다 — 기록에는 어느 그림이 비었는지 남는다.
 * 탐지가 판을 다시 시작하면(`imageRound`) 같은 이름의 그림을 새로 떠서 덮는다.
 *
 * 다시보기 중에는 아무것도 안 쓴다. 창구가 없으면(단독 빌드 등) 조용히 멈춘다.
 *
 * ## 판마다 저장처 하나 (261119 — 임무 이력 서버 2차)
 *
 * 폴더를 정할 때 저장처도 정한다(`chooseSink` — 서버가 `연결됨` 이면 서버, 아니면 이 PC). 서버로 쓰던 판이
 * 실패하면 **그 판은 끝까지 이 PC** 로 옮기고(대피), 서버에 이미 보낸 그림을 원본에서 다시 떠 이 PC 에도 쓴다
 * — 판 하나가 두 곳에 나뉘면 어디서 열어도 깨진다. 대피한 판은 끝난 뒤 `historyUpload.ts` 가 통째로 올린다.
 * 서버 주소가 있는데 쓸 곳이 하나도 없으면(이 PC 창구 없는 화면 + 서버 끊김) 멈추지 않고 다음 주기에 다시 고른다.
 */

import { t } from '../i18n/dict.ts';
import { foldStatuses } from '../data/fold.ts';
import {
  currentRunSerial, missionHistory, onRunSeal, subscribeMissionHistory, type MissionHistoryEntry,
} from '../data/missionHistory.ts';
import { currentMission, getMissionState, NO_MISSION, traceEvents } from '../data/scenario.ts';
import { frameImageUrl, mapImageUrl, pathImageUrl, roundedImageUrl, sourceOf } from '../detect/DetectClient.ts';
import { detectLog } from '../detect/detectLog.ts';
import { frameImageKinds } from '../detect/frameImage.ts';
import { detectState, recordableDetect } from '../detect/store.ts';
import { prepState } from '../physical/prepStage.ts';
import { recordableRobotSession, robotDrives, robotSession } from '../physical/robotSession.ts';
import type { ScanFeedMessage } from '../physical/scanFeed.ts';
import { connectionAddress } from '../shared/connections.ts';
import { notificationsNow } from '../shared/notifications.ts';
import { arrivedFrames } from '../viewpoint/store.ts';
import { recordableNavFeed } from '../physical/navFeed.ts';
import { navRun } from '../physical/navRun.ts';
import { recordableObstacle } from '../autodrive/obstacle.ts';
import { scanClient } from '../detect/scan/ScanClient.ts';
import { frameResultAt, recordableScanRun, scanRunState } from '../detect/scan/scanStore.ts';
import { recordableScanApproach } from '../physical/scanApproachRun.ts';
import { detectTargetOf, relayDriven } from '../scenarios/library.ts';
import { useSyncExternalStore } from 'react';
import {
  chooseSink, detectImagePath, nextSink, postRecordImage, putRecordJson, robotImagePath, runFolderOf, scanImagePath,
  type RecordMissionSummary, type RecordSink,
} from './recordClient.ts';
import { registerActiveRecordFolders } from './evacuations.ts';
import { isReplayingRecord } from './replayMode.ts';

/**
 * 기록의 모양 번호.
 *
 * **`/2` (260919 · 5단계)** — 로그 줄이 **그려진 글자 대신 키와 값**을 담는다(`say`).
 * 그래서 한국어로 기록한 판을 영문 화면에서 다시 봐도 문장이 영어로 그려진다.
 *
 * **`/1` 판은 그대로 열린다.** 그 판들은 `text`·`detail` 만 들고 있고, 그리는 자리가
 * `say` 가 없으면 그 글자를 쓴다(`detectLog.lineText`). 260914~260916 의 45판이 여기
 * 해당하고, 그 글자는 **기록한 순간의 언어 그대로** 남는다 — 다시 그릴 재료가 없다.
 * 그것이 맞다: 기록은 기록이다.
 */
export const RECORD_SCHEMA = 'mission-record/2';
const TICK_MS = 1500;
/** 그림 하나를 몇 번까지 다시 떠 보나. 주기가 1.5초라 대략 30초. */
const IMAGE_ATTEMPTS = 20;

/** 로봇 촬영 한 건 — 그림은 파일로, 값은 여기로. */
export type RecordedRobotFrame = {
  receivedAtIso: string;
  rotationDeg: number;
  seq: number | null;
  bytes: number | null;
  sha1: string | null;
  duplicateOfPrev: boolean;
  timestamp: string | null;
  file: string | null;
};

type Run = {
  serial: number;
  missionId: string;
  createdAtMs: number;
  folder: { date: string; run: string } | null;
  startedAtIso: string | null;
  /** 마지막으로 쓴 본문 — 같으면 안 쓴다. */
  written: { mission: string; progress: string };
  /** 이 판에서 지금까지 쓴 기록 열의 최대 길이 — 열이 이보다 짧아지면 안 쓴다(`recordTick`). */
  traceHigh: number;
  robotFrames: RecordedRobotFrame[];
  /** 저장한 그림: 경로 → 서명(판 번호 등). 서명이 바뀌면 다시 뜬다. */
  images: Map<string, string>;
  /** 저장이 어떻게 됐나 — 기록에 같이 남긴다. */
  imageLog: Record<string, { source: string; savedAtIso: string | null; attempts: number; error: string | null }>;
  /** 자율주행 편 — 이 판에서 중계 판을 연 시각. 안 열었으면 null. */
  navStartedAtMs: number | null;
  /** 저장처 (261119). 폴더를 정할 때 고른다. null 이면 아직 쓸 곳이 없다 — 다음 주기에 다시 고른다. */
  sink: RecordSink | null;
  /** 서버로 보낸 그림 — 대피하면 이것을 원본에서 다시 떠 이 PC 에 쓴다. */
  serverImages: Map<string, { signature: string; source: string | Uint8Array }>;
};

type ImageJob = {
  folder: { date: string; run: string };
  run: Run;
  path: string;
  signature: string;
  source: string | Uint8Array;
  attempts: number;
};

export type RecorderStatus = {
  state: 'idle' | 'waiting' | 'recording' | 'unavailable';
  folder: string | null;
  /** 지금 판의 저장처 (261119). 판이 없거나 아직 못 골랐으면 null. */
  sink: RecordSink | null;
  lastSavedAtIso: string | null;
  lastError: string | null;
};

let run: Run | null = null;
let status: RecorderStatus = { state: 'idle', folder: null, sink: null, lastSavedAtIso: null, lastError: null };
const statusListeners = new Set<() => void>();
const jobs = new Map<string, ImageJob>();
let writing: Promise<void> = Promise.resolve();
let jobsRunning = false;

function setStatus(next: Partial<RecorderStatus>): void {
  const merged = { ...status, ...next };
  if (merged.state === status.state && merged.folder === status.folder && merged.sink === status.sink
    && merged.lastSavedAtIso === status.lastSavedAtIso && merged.lastError === status.lastError) return;
  status = merged;
  for (const listener of statusListeners) listener();
}

export function recorderStatus(): RecorderStatus {
  return status;
}

export function useRecorderStatus(): RecorderStatus {
  return useSyncExternalStore(
    (listener) => { statusListeners.add(listener); return () => statusListeners.delete(listener); },
    recorderStatus, recorderStatus,
  );
}

// ── 판 ───────────────────────────────────────────────────────────────────────

function currentRun(): Run | null {
  const mission = getMissionState();
  if (mission.current.missionId === NO_MISSION || mission.activatedBy !== 'approval') return null;
  if (run === null || run.serial !== currentRunSerial() || run.missionId !== mission.current.missionId) {
    run = {
      serial: currentRunSerial(),
      missionId: mission.current.missionId,
      createdAtMs: Date.now(),
      folder: null,
      startedAtIso: null,
      written: { mission: '', progress: '' },
      traceHigh: 0,
      robotFrames: [],
      images: new Map(),
      imageLog: {},
      navStartedAtMs: null,
      sink: null,
      serverImages: new Map(),
    };
  }
  return run;
}

/** 이 판이 끝났으면 그 줄. 이 판이 서기 전에 적힌 줄은 남의 것이다. */
function endOf(target: Run): MissionHistoryEntry | null {
  const entry = missionHistory()[0];
  if (entry === undefined || entry.missionId !== target.missionId) return null;
  return Date.parse(entry.endedAtIso) >= target.createdAtMs - 1000 ? entry : null;
}

/**
 * 폴더를 만들 만큼 무언가 일어났나 — 시작을 눌렀거나, 사람 밖의 사건이 왔거나, 끝났거나.
 *
 * **계획의 생성 사건(`created`)은 일어난 일이 아니다** (261025). 승인하는 순간 대본의 `created` 가 들어오는데
 * (`seedPlan`) 그 주체가 `backend` 라, 그것을 세면 승인만 한 판마다 폴더가 생긴다 — 목록이 빈 판으로 찬다.
 */
function somethingHappened(target: Run): boolean {
  if (robotSession().started || endOf(target) !== null) return true;
  return traceEvents().some((event) => event.producedBy !== 'human' && event.producedBy !== 'ai' && event.kind !== 'created');
}

// ── 본문 ─────────────────────────────────────────────────────────────────────

function buildBodies(target: Run): { mission: string; progress: string } {
  const mission = getMissionState();
  const view = mission.current;
  const trace = traceEvents();
  const folded = foldStatuses(mission.headSec, view, trace);
  const done = view.tasks.filter((task) => folded.tasks[task.id]?.status === 'done').length;
  const failed = view.tasks.find((task) => folded.tasks[task.id]?.status === 'failed') ?? null;
  const end = endOf(target);
  const detect = recordableDetect();
  const session = recordableRobotSession();
  const now = new Date().toISOString();

  const summary: RecordMissionSummary & { schema: string; folder: string; view: typeof view; connections: Record<string, string> } = {
    schema: RECORD_SCHEMA,
    folder: target.folder === null ? '' : `${target.folder.date}/${target.folder.run}`,
    missionId: view.missionId,
    label: view.label,
    startedAtIso: target.startedAtIso ?? now,
    updatedAtIso: now,
    endedAtIso: end?.endedAtIso ?? null,
    outcome: end?.outcome ?? null,
    done: end?.done ?? done,
    of: end?.of ?? view.tasks.length,
    failedTaskId: end?.failedTaskId ?? failed?.id ?? null,
    reason: end?.reason ?? '',
    headSec: mission.headSec,
    robotDriven: robotDrives(),
    testMode: detect.testMode,
    imageCount: target.images.size,
    path: detect.path === null ? null : {
      mode: detect.path.path_mode ?? null,
      turnInstruction: detect.path.turn_instruction,
      forwardM: detect.path.forward_distance_cm / 100,
    },
    pathFailure: detect.pathFailure,
    connections: {
      robot: connectionAddress('physical', 'ws'),
      detect: connectionAddress('detect', 'base'),
      // 자율주행 편 (260915) — pi1 중계와 AI 서버. 문 찾기 편에서도 적히지만 그 판에서는 쓰이지 않는다.
      autodrive: connectionAddress('autodrive', 'ws'),
      autodriveAi: connectionAddress('autodrive-ai', 'base'),
    },
    view,
  };

  const progress = {
    schema: RECORD_SCHEMA,
    missionId: view.missionId,
    updatedAtIso: now,
    headSec: mission.headSec,
    trace,
    viewpointFrames: arrivedFrames(),
    robot: session,
    robotFrames: target.robotFrames,
    detect,
    detectLog: detectLog(),
    prep: prepState(),
    notifications: notificationsNow(),
    images: target.imageLog,
    // 자율주행 편 (260915) — pi1 중계가 준 상태·사건과 AI 서버의 장애물 기록. 판이 안 열렸으면 사건은 비어 있다.
    // 중계 판의 임무에서만 싣는다 — 문 찾기 편 기록에 남의 판 값이 섞이면 안 된다.
    // 스캔 탐지 편 (261124) — data_stream 판의 상태와 이동 계획. 이 임무의 판일 때만 싣는다.
    ...(scanRunState()?.missionId === view.missionId ? {
      scan: recordableScanRun(),
      scanApproach: recordableScanApproach()?.missionId === view.missionId ? recordableScanApproach() : null,
    } : {}),
    ...(relayDriven(view.missionId) ? {
      nav: recordableNavFeed(navRun()?.startedAtMs ?? target.navStartedAtMs),
      obstacle: recordableObstacle(),
    } : {}),
  };
  return { mission: JSON.stringify(summary, null, 2), progress: JSON.stringify(progress) };
}

/**
 * **저장처를 다시 정한다** (261119). 서버로 쓰던 판이 실패하면 이 PC 로 옮긴다(대피). 두 JSON 은 다음 주기에 통째로
 * 다시 쓰이고(`written` 을 비운다), 서버로 보낸 그림은 원본에서 다시 떠 이 PC 에 쓴다. 원본이 이미 없으면(탐지가 새 판)
 * 그 그림은 서버에만 남는다. 서버 주소 없이 이 PC 창구가 없으면(404) 예전처럼 멈춘다.
 */
function moveSink(target: Run, from: RecordSink | null, error: unknown): void {
  if (target.sink !== from) return;   // 이미 옮겼다 (그림 · JSON 이 같이 실패한 경우)
  const next = nextSink(from, error);
  if (next.stop) { setStatus({ state: 'unavailable', lastError: t('rec.1') }); return; }
  target.sink = next.sink;
  target.written = { mission: '', progress: '' };
  if (next.sink === 'local' && from === 'server') {
    for (const [path, image] of target.serverImages) {
      target.images.delete(path);
      want(target, path, image.signature, image.source);
    }
    target.serverImages.clear();
  }
  setStatus({ sink: target.sink, lastError: error instanceof Error ? error.message : String(error) });
}

function write(target: Run, bodies: { mission: string; progress: string }): void {
  const folder = target.folder;
  if (folder === null) return;
  const sink = target.sink;
  if (sink === null) return;
  const missionChanged = bodies.mission.replace(/"updatedAtIso": "[^"]*"/, '') !== target.written.mission.replace(/"updatedAtIso": "[^"]*"/, '');
  const progressChanged = bodies.progress.replace(/"updatedAtIso":"[^"]*"/, '') !== target.written.progress.replace(/"updatedAtIso":"[^"]*"/, '');
  if (!missionChanged && !progressChanged) return;
  target.written = bodies;
  // 차례로 쓴다 — 같은 파일을 두 요청이 겹쳐 쓰면 늦게 출발한 것이 먼저 끝날 수 있다.
  writing = writing.then(async () => {
    // 앞 쓰기가 실패해 저장처가 바뀌었으면 이 본문은 안 보낸다 — 다음 주기가 새 저장처에 통째로 쓴다.
    if (target.sink !== sink) return;
    try {
      if (progressChanged) await putRecordJson(folder.date, folder.run, 'progress.json', bodies.progress, sink);
      await putRecordJson(folder.date, folder.run, 'mission.json', bodies.mission, sink);
      setStatus({ state: 'recording', folder: `${folder.date}/${folder.run}`, sink, lastSavedAtIso: new Date().toISOString(), lastError: null });
    } catch (error) {
      // 창구가 아예 없으면(404 · 서버 주소 없음) 멈춘다 — 매 주기 실패를 쌓지 않는다. 서버 실패면 이 PC 로 대피.
      target.written = { mission: '', progress: '' };   // 다음 주기에 다시 쓴다
      moveSink(target, sink, error);
    }
  });
}

// ── 그림 ─────────────────────────────────────────────────────────────────────

function want(target: Run, path: string, signature: string, source: string | Uint8Array): void {
  if (target.folder === null) return;
  if (target.images.get(path) === signature) return;
  const key = `${target.folder.date}/${target.folder.run}/${path}`;
  const existing = jobs.get(key);
  if (existing !== undefined && existing.signature === signature) return;
  jobs.set(key, { folder: target.folder, run: target, path, signature, source, attempts: 0 });
  target.imageLog[path] = { source: typeof source === 'string' ? source : 'robot/frame (MQTT)', savedAtIso: null, attempts: 0, error: null };
}

/** 지금 저장소에 있는 탐지 그림을 떠 둘 목록에 올린다. */
function wantDetectImages(target: Run): void {
  const detect = detectState();
  const source = sourceOf(detect.testMode);
  const round = String(detect.imageRound);
  // 뷰 노드가 그린 것과 같은 주소여야 같은 그림이 떠진다 — 대상(문 · 박스)도 같은 원천에서 읽는다.
  const detectTarget = detectTargetOf(currentMission().missionId);
  for (const frame of detect.frames) {
    // 박스 편은 못 찾은 각도도 버린 후보를 그린 그림이 화면에 뜬다(`detect/frameImage.ts`) — 그것도 떠 둔다.
    // 지난 판이라 없으면(404) 그 한 장만 실패로 적히고, 다시보기는 원본으로 넘어간다.
    const kinds = frame.found
      ? ['original', 'target_overlay', 'target_crop'] as const
      : frameImageKinds(frame, detectTarget).includes('target_overlay') ? ['original', 'target_overlay'] as const : ['original'] as const;
    for (const kind of kinds) {
      want(target, detectImagePath({ frame: frame.frame, kind }), round,
        roundedImageUrl(frameImageUrl(source, frame.frame, kind, detectTarget), detect.imageRound));
    }
  }
  if (detect.path !== null && detect.path.path_overlay_available !== false) {
    want(target, detectImagePath('path_overlay'), `${round}:${detect.path.turn_instruction}`,
      roundedImageUrl(pathImageUrl(source, detectTarget), detect.imageRound));
  }
  const map = prepState().map;
  if (map.url !== null && !map.bundled) {
    want(target, detectImagePath('map'), `${prepState().runKey ?? ''}:${map.url}`, roundedImageUrl(mapImageUrl(source), detect.imageRound));
  }
}

/**
 * **스캔 탐지(data_stream) 각도 그림을 떠 둔다** (261124). 화면은 창구(`/scan/frame`)에서 그때그때 받아 그리는데, 창구는 끝난 판을
 * 최근 몇 개만 들고 다른 PC 에서는 닿지도 않는다. 그래서 받은 각도마다 원본을, 결과가 오면 찾은 각도의 상자 그림과 대상의
 * 잘라낸 그림을 이 판 폴더에 둔다. 다시보기의 각도 칸 · 근거 카드가 화면에 뜬 것과 같은 그림을 여기서 읽는다.
 */
function wantScanImages(target: Run): void {
  const run = scanRunState();
  if (run === null || run.recorded !== null || run.missionId !== target.missionId || run.base === '') return;
  const client = scanClient(run.base);
  for (const angle of run.angles) {
    if (angle.captured !== true) continue;
    want(target, scanImagePath(angle.deg, 'original'), run.scanId, client.frameUrl(run.scanId, angle.deg, 'original'));
    if (frameResultAt(run, angle.deg)?.found === true) {
      want(target, scanImagePath(angle.deg, 'overlay'), run.scanId, client.frameUrl(run.scanId, angle.deg, 'overlay'));
    }
  }
  const best = run.result?.best ?? null;
  if (best !== null) want(target, scanImagePath(best.rotation_deg, 'crop'), run.scanId, client.frameUrl(run.scanId, best.rotation_deg, 'crop'));
}

async function runJobs(): Promise<void> {
  if (jobsRunning) return;
  jobsRunning = true;
  try {
    for (const [key, job] of [...jobs]) {
      // 저장처가 아직 없다 — 셈을 안 늘리고 다음 주기에.
      const sink = job.run.sink;
      if (sink === null) continue;
      job.attempts += 1;
      const log = job.run.imageLog[job.path];
      try {
        const bytes = typeof job.source === 'string'
          ? await fetchImage(job.source)
          : job.source;
        try {
          await postRecordImage(job.folder.date, job.folder.run, job.path, bytes, sink);
        } catch (error) {
          // 저장 쪽 실패 — 원본 탓이 아니므로 셈을 되돌리고 저장처를 다시 정한다. 그림은 줄에 남아 새 저장처로 간다.
          job.attempts -= 1;
          moveSink(job.run, sink, error);
          if (status.state === 'unavailable') throw error;
          continue;
        }
        if (sink === 'server') job.run.serverImages.set(job.path, { signature: job.signature, source: job.source });
        job.run.images.set(job.path, job.signature);
        if (log !== undefined) Object.assign(log, { savedAtIso: new Date().toISOString(), attempts: job.attempts, error: null });
        if (jobs.get(key) === job) jobs.delete(key);
      } catch (error) {
        const why = error instanceof Error ? error.message : String(error);
        if (log !== undefined) Object.assign(log, { attempts: job.attempts, error: why });
        if (job.attempts >= IMAGE_ATTEMPTS && jobs.get(key) === job) jobs.delete(key);
      }
    }
  } finally {
    jobsRunning = false;
  }
}

async function fetchImage(url: string): Promise<Blob> {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) throw new Error(t('rec.imageFailed', { status: response.status }));
  const blob = await response.blob();
  if (blob.size === 0) throw new Error(t('rec.emptyImage'));
  return blob;
}

function base64Bytes(base64: string): Uint8Array {
  const raw = atob(base64.replace(/^data:[^,]*,/, ''));
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

// ── 주기 ─────────────────────────────────────────────────────────────────────

/** 한 번 본다 — 폴더가 필요하면 만들고, 바뀐 것을 쓰고, 그림을 뜬다. 검사가 직접 부른다. */
export function recordTick(): void {
  if (isReplayingRecord() || status.state === 'unavailable') return;
  const target = currentRun();
  if (target === null) { setStatus({ state: 'idle', folder: null }); return; }
  // 중계 판이 열린 시각을 붙들어 둔다 — 정지 해제로 판이 닫힌 뒤에 뜨는 마지막 기록도 이 판의 사건만 싣는다.
  const nav = navRun();
  if (nav !== null && nav.missionId === target.missionId) target.navStartedAtMs = nav.startedAtMs;
  if (target.folder === null) {
    if (!somethingHappened(target)) { setStatus({ state: 'waiting', folder: null }); return; }
    // 자율주행 편은 로봇 세션을 안 쓴다 — 「▶ 임무 시작」이 연 판의 시각이 시작이다(260915).
    const startedAtMs = robotSession().startedAtMs ?? target.navStartedAtMs ?? target.createdAtMs;
    target.folder = runFolderOf(new Date(startedAtMs), target.missionId);
    target.startedAtIso = new Date(startedAtMs).toISOString();
  }
  // 저장처 (261119) — 판에 한 번. 못 골랐으면(쓸 곳이 없다) 주기마다 다시 고른다.
  if (target.sink === null) {
    target.sink = chooseSink();
    setStatus({ sink: target.sink, ...(target.sink === null ? { lastError: t('hsrv.noSink') } : {}) });
  }
  /**
   * **같은 판 안에서 기록 열이 줄어들면 쓰지 않는다** (261026 — 기록 열 덮어쓰기).
   *
   * 기록은 덧붙이기만 한다(§4-2) — 그래서 같은 판의 열은 줄어들 수 없다. 줄었다면 판이 바뀐 것이 아니라 저장소가
   * 깨진 것이다. 열을 정당하게 비우는 길(새 임무 · 생성 임무 · 미리보기 · 초기화 · 처음부터)은 전부 비우기 **전에**
   * `sealRun()` 을 부르고, 그때 `seal()` 이 이 판을 놓아 새 `Run`(높이 0)과 새 폴더가 선다 — 그 길은 안 막힌다.
   *
   * 261026 03:29 `024124` 판이 이것으로 지워졌다. `src` 를 고치자 핫 리로드가 저장소를 비웠고, 이 기록기는 같은 판을
   * 쥔 채 다음 틱에 빈 열(101 → 0)을 덮어썼다. 빈 열만 막으면 101 → 3 은 못 막는다.
   *
   * 막으면 **그 틱을 통째로 건너뛴다** — `mission.json` 만 쓰면 둘이 어긋난다. 그리고 조용히 넘어가지 않는다.
   */
  const traceLength = traceEvents().length;
  if (traceLength < target.traceHigh) {
    const reason = t('rec.traceShrunk', { before: target.traceHigh, now: traceLength });
    if (status.lastError !== reason) console.warn(`[recorder] ${target.folder.date}/${target.folder.run} — ${reason}`);
    setStatus({ lastError: reason });
    return;
  }
  target.traceHigh = traceLength;
  wantDetectImages(target);
  wantScanImages(target);
  write(target, buildBodies(target));
  void runJobs();
}

/** 새 판이 서기 직전 — 지난 판의 마지막 모습을 지금 뜬다. 저장소가 곧 비워진다. */
function seal(): void {
  if (isReplayingRecord() || status.state === 'unavailable') return;
  recordTick();
  run = null;
}

/**
 * **로봇 촬영이 왔다** (`robotClient` 가 부른다). 그림은 곧바로 흘려보내고 값만 적는다.
 * 폴더가 아직 없으면 값만 들고 있다가 폴더가 서면 그림 없이 남는다 — 촬영은 시작 뒤에만 오므로 드물다.
 */
export function noteRobotFrame(message: ScanFeedMessage): void {
  if (message.kind !== 'frame' || isReplayingRecord() || status.state === 'unavailable') return;
  const target = currentRun();
  if (target === null) return;
  if (target.folder === null && somethingHappened(target)) recordTick();
  const path = robotImagePath(message.rotationDeg);
  const hasImage = message.imageBase64 !== null && target.folder !== null;
  target.robotFrames.push({
    receivedAtIso: new Date().toISOString(),
    rotationDeg: message.rotationDeg,
    seq: message.seq,
    bytes: message.bytes,
    sha1: message.sha1,
    duplicateOfPrev: message.duplicateOfPrev,
    timestamp: message.timestamp,
    file: hasImage ? path : null,
  });
  if (hasImage) {
    try {
      want(target, path, `${message.seq ?? ''}:${message.sha1 ?? target.robotFrames.length}`, base64Bytes(message.imageBase64!));
      void runJobs();
    } catch {
      // base64 가 깨졌으면 값만 남긴다.
    }
  }
}

/** 지금 쓰고 있는 판 — 폴더가 섰고 아직 안 끝난 판 (261119). */
export function activeFolders(): string[] {
  if (run === null || run.folder === null || endOf(run) !== null) return [];
  return [`${run.folder.date}/${run.folder.run}`];
}

let refs = 0;
let stopAll: (() => void) | null = null;

/** 켠다. 되돌려주는 함수를 부르면 끈다. 여러 번 켜도 하나만 돈다. */
export function startMissionRecorder(): () => void {
  refs += 1;
  if (stopAll === null) {
    const timer = setInterval(recordTick, TICK_MS);
    const offSeal = onRunSeal(seal);
    // 끝나면 곧바로 쓴다 — 주기를 기다리는 사이에 「처음부터」를 누르면 끝 표시가 늦는다.
    const offEnd = subscribeMissionHistory(() => recordTick());
    // 대피 판 올리기에 「아직 쓰고 있는 판」을 알린다 — 끝나기 전에는 안 올린다 (261119).
    const offActive = registerActiveRecordFolders(activeFolders);
    stopAll = () => { clearInterval(timer); offSeal(); offEnd(); offActive(); };
  }
  return () => {
    refs -= 1;
    if (refs === 0 && stopAll !== null) { stopAll(); stopAll = null; }
  };
}

/** 검사용 — 기록기를 처음 상태로. */
export function resetRecorderForTest(): void {
  run = null;
  jobs.clear();
  writing = Promise.resolve();
  status = { state: 'idle', folder: null, sink: null, lastSavedAtIso: null, lastError: null };
}

/** 검사용 — 밀린 쓰기와 그림이 끝날 때까지 기다린다. */
export async function settleRecorder(): Promise<void> {
  await writing;
  while (jobsRunning) await new Promise((resolve) => setTimeout(resolve, 5));
  await runJobs();
  await writing;
}
