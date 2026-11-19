/**
 * src/record/historyUpload.ts (261119 신설 — 임무 이력 서버 2차)
 *
 * **대피 판을 서버로 올린다.** 서버가 끊기거나 불안정한 동안 이 PC 에 쓴 판(`evacuations.ts`)을, 서버가
 * 다시 `연결됨` 이 되면 통째로 올린다. 사람이 누르지 않는다 — 버튼으로 두면 잊는다(계획서 결정 2).
 *
 * - **아직 쓰고 있는 판은 안 올린다.** 판이 끝난 뒤에 올린다(계획서 결정 1). 기록기가 알려 준다.
 * - 순서는 `progress.json` → 그림 → `mission.json`. 서버 목록은 `mission.json` 이 있는 판만 보이므로
 *   도중에 끊겨도 반쯤 올라간 판이 목록에 안 뜬다(`history:push` 와 같은 순서).
 * - 서버에 같은 판이 있으면(서버로 쓰다 대피한 판) 덮어쓴다. 이 PC 에 없는 그림은 서버 것이 그대로 남는다.
 * - **이 PC 파일은 지우지 않는다** — 이력은 지우지 않는다(팀 규칙). 목록에서만 뺀다.
 * - 올리다 서버가 또 흔들리면 멈춘다. 다음에 붙으면 그 판을 처음부터(덮어쓰기라 다시 해도 안전하다).
 */

import { useSyncExternalStore } from 'react';
import {
  activeRecordFolders, clearEvacuated, evacuatedRuns, markEvacuatedRejected, subscribeEvacuated,
} from './evacuations.ts';
import { historyServerConnected, subscribeHistoryServer } from './historyServer.ts';
import { listLocalRunFiles, readLocalRecordFile, uploadRecordFile } from './recordClient.ts';

/** 다시 볼 간격 — 끝난 판이 생겼는지 · 서버가 돌아왔는지. */
const RETRY_MS = 15_000;

export type UploadStatus = {
  uploading: boolean;
  /** 올리는 판 `날짜/판` · 몇 번째 / 몇 개. */
  current: string | null;
  index: number;
  total: number;
  lastUploadedAtIso: string | null;
  lastError: string | null;
};

let status: UploadStatus = { uploading: false, current: null, index: 0, total: 0, lastUploadedAtIso: null, lastError: null };
const listeners = new Set<() => void>();

function setStatus(patch: Partial<UploadStatus>): void {
  status = { ...status, ...patch };
  for (const listener of listeners) listener();
}

export function uploadStatus(): UploadStatus {
  return status;
}

export function useUploadStatus(): UploadStatus {
  return useSyncExternalStore(
    (listener) => { listeners.add(listener); return () => listeners.delete(listener); },
    uploadStatus, uploadStatus,
  );
}

/** 올릴 판 — 거절당하지 않았고, 지금 쓰고 있지 않은 것. */
export function uploadableRuns() {
  const active = activeRecordFolders();
  return evacuatedRuns().filter((item) => item.rejected === null && !active.has(`${item.date}/${item.run}`));
}

/** 판 파일을 올릴 순서로 — JSON 진행 · 그림 · 요약. */
function uploadOrder(files: readonly string[]): string[] {
  const images = files.filter((f) => f.startsWith('images/'));
  return [
    ...(files.includes('progress.json') ? ['progress.json'] : []),
    ...images,
    ...(files.includes('mission.json') ? ['mission.json'] : []),
  ];
}

let running: Promise<void> | null = null;

/** 한 바퀴 올린다. 이미 도는 중이면 그것을 기다린다. 서버가 `연결됨` 이 아니면 아무것도 안 한다. */
export function uploadEvacuatedRuns(): Promise<void> {
  if (running !== null) return running;
  if (!historyServerConnected()) return Promise.resolve();
  const todo = uploadableRuns();
  if (todo.length === 0) return Promise.resolve();
  running = (async () => {
    setStatus({ uploading: true, total: todo.length, index: 0, lastError: null });
    try {
      for (const [index, item] of todo.entries()) {
        if (!historyServerConnected()) return;
        const key = `${item.date}/${item.run}`;
        setStatus({ current: key, index: index + 1 });
        const startedAtMs = Date.now();
        const files = await listLocalRunFiles(item.date, item.run);
        if (files === null || !files.includes('mission.json')) {
          // 이 PC 에 그 판이 없다(창구 없음 · 다른 폴더). 지울 수는 없으니 남기고 사유만 적는다.
          setStatus({ lastError: `${key}: local files not readable` });
          continue;
        }
        let outcome: 'ok' | 'rejected' | 'failed' = 'ok';
        for (const path of uploadOrder(files)) {
          const body = await readLocalRecordFile(item.date, item.run, path);
          if (body === null) continue;   // 그 사이 사라진 그림 — 나머지는 올린다
          outcome = await uploadRecordFile(item.date, item.run, path, body);
          if (outcome !== 'ok') {
            setStatus({ lastError: `${key}/${path}: ${outcome}` });
            break;
          }
        }
        if (outcome === 'failed') return;   // 서버가 흔들린다 — 멈추고 다음 연결 때
        if (outcome === 'rejected') { markEvacuatedRejected(item.date, item.run, status.lastError ?? 'rejected'); continue; }
        clearEvacuated(item.date, item.run, startedAtMs);
        setStatus({ lastUploadedAtIso: new Date().toISOString() });
      }
    } finally {
      setStatus({ uploading: false, current: null });
      running = null;
    }
  })();
  return running;
}

/**
 * 켠다 — 서버가 `연결됨` 이 되는 순간과 몇 초마다(끝난 판이 생겼는지) 올린다. `main.tsx` 가 건다.
 */
export function startEvacuationUpload(): () => void {
  let wasConnected = historyServerConnected();
  const kick = () => { void uploadEvacuatedRuns(); };
  const offServer = subscribeHistoryServer(() => {
    const now = historyServerConnected();
    if (now && !wasConnected) kick();
    wasConnected = now;
  });
  const offList = subscribeEvacuated(() => { if (historyServerConnected()) setTimeout(kick, 0); });
  const timer = setInterval(kick, RETRY_MS);
  kick();
  return () => { offServer(); offList(); clearInterval(timer); };
}

/** 검사용. */
export async function settleUpload(): Promise<void> {
  while (running !== null) await running;
}
