/**
 * src/autodrive/views/AutodriveViews.tsx (260915 신설 — 자율주행 편 · 로봇 영상 · 장애물 탐지)
 *
 * 세 자리.
 *
 *   AutodriveCam      로봇 영상 뷰 노드 — 접힘은 **2초마다 한 장**, 확대는 AI 서버 스트림을 **그대로**
 *   ObstacleFacts     「장애물 탐지」 액션 아이템 — 받은 JSON 그대로 · 탐지 표 · 바뀐 줄
 *   ObstacleEvidence  「장애물 탐지」 판단 근거 — AI 서버의 `has_near_obstacle` 과 가까운 것들
 *
 * **문 찾기 시연(`src/detect/views/`)과 섞지 않는다.** 클래스 이름 몇 개(`detect-cam` 모양)만 빌리고
 * 코드는 import 하지 않는다.
 *
 * 접힘을 한 장으로 두는 이유는 옛 영상 노드와 같다(`VZ-I-06`) — 스트림은 끝나지 않는 응답이라 카드마다
 * 걸어 두면 카드 수만큼 연결이 열린다. 실시간은 확대에서만 연다.
 */

import { useEffect, useState } from 'react';
import { aiBase, aiControlUrl, aiFrameUrl, aiStreamUrl, AI_CAMERA } from '../aiClient.ts';
import { holdObstaclePolling, obstacleFrozen, useObstacle, type ObstacleDetection, type ObstacleSnapshot } from '../obstacle.ts';
import { useReplayTarget } from '../../record/replayMode.ts';

const clock = (ms: number) => new Date(ms).toTimeString().slice(0, 8);
const cm = (value: number | null) => (value === null ? '—' : `${value.toFixed(1)} cm`);

/** 접힌 카드가 새 한 장을 받는 주기. */
export const CAM_STILL_MS = 2000;

export function AutodriveCam({ zoom = false }: { zoom?: boolean }) {
  const [nonce, setNonce] = useState(0);
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const replaying = useReplayTarget();

  // 접힘은 한 장씩 — 받는 대로 다음 것을 기다린다. 확대는 스트림 하나라 타이머가 없다.
  useEffect(() => {
    if (zoom || replaying !== null) return;
    const timer = setInterval(() => setNonce((value) => value + 1), CAM_STILL_MS);
    return () => clearInterval(timer);
  }, [zoom, replaying]);

  // **다시보기에서는 영상을 띄우지 않는다** (260915) — 영상은 기록하지 않았고, 지금 영상을 그 판 자리에 띄우면
  // 지난 판을 보는 사람이 그때 로봇이 본 것으로 읽는다. 장애물 판정은 액션 아이템에 기록이 남아 있다.
  if (replaying !== null) {
    return <p className="vn-line vn-dim">다시보기 중 — 영상은 기록하지 않습니다. 그 판의 장애물 판정은 「장애물 탐지」 노드의 액션 아이템에 있습니다</p>;
  }
  if (aiBase() === '') {
    return <p className="vn-line vn-dim">AI 서버 주소가 비어 있습니다 — 연결 관리의 「자율주행 영상 · 장애물 탐지」에 넣으세요</p>;
  }
  const src = zoom ? aiStreamUrl() : aiFrameUrl(nonce);
  return <div className={`detect-cam autodrive-cam${zoom ? ' detect-cam--zoom' : ''}`}>
    <img
      // 확대는 주소가 안 바뀌어야 스트림이 안 끊긴다. 접힘은 한 장마다 새 요소가 아니라 새 주소다.
      src={src}
      alt={`${AI_CAMERA} AI 영상`}
      onLoad={() => { setLoadedAt(Date.now()); setFailed(null); }}
      onError={() => setFailed(zoom
        ? `스트림을 못 열었습니다 — ${aiStreamUrl()}`
        : '한 장을 못 받았습니다 — 스트림이 멎었거나 개발 서버 창구가 없습니다(확대하면 직접 엽니다)')}
    />
    <p className="detect-cam__at">
      {failed !== null
        ? <b className="vn-warn">{failed}</b>
        : zoom
          ? <>실시간 · <code>{aiStreamUrl()}</code></>
          : loadedAt === null ? '첫 장을 받는 중…' : `${clock(loadedAt)} 한 장 · ${CAM_STILL_MS / 1000}초마다 · 실시간은 확대`}
    </p>
  </div>;
}

/** 탐지 한 줄. 받은 칸만 적는다. */
function DetectionRow({ d }: { d: ObstacleDetection }) {
  return <tr className={d.riskLevel === 'near' ? 'is-near' : undefined}>
    <td>{d.id ?? '—'}</td>
    <td><b>{d.name}</b>{d.group === null ? null : <small> {d.group}</small>}</td>
    <td>{cm(d.distanceCm)}<small> 원본 {cm(d.distanceCmRaw)}</small></td>
    <td>{d.relDepth === null ? '—' : d.relDepth.toFixed(3)}</td>
    <td>{d.riskLevel ?? '—'}</td>
    <td><code>{d.bbox === null ? '—' : d.bbox.join(', ')}</code></td>
  </tr>;
}

function Freshness({ snap, error, frozen, replaying }: { snap: ObstacleSnapshot | null; error: string | null; frozen: boolean; replaying: boolean }) {
  return <dl className="device-facts">
    <div><dt>주소</dt><dd><code>{aiControlUrl()}</code></dd></div>
    {/* 다시보기에서는 「몇 초 전」을 안 적는다 — 지난 판의 값이라 지금과의 차이는 뜻이 없다. */}
    {snap !== null && <div><dt>{replaying ? '기록된 마지막 값' : '마지막 수신'}</dt><dd>{clock(snap.receivedAtMs)}{replaying ? '' : ` · ${Math.round((Date.now() - snap.receivedAtMs) / 1000)}초 전`}{snap.timestampSec === null ? '' : ` · 서버 시각 ${snap.timestampSec.toFixed(3)}`}{frozen && !replaying ? ' · ⚠ 서버 값이 5초 넘게 안 바뀝니다' : ''}</dd></div>}
    {error !== null && <div><dt>지금</dt><dd className="vn-warn">못 받고 있습니다 — {error}</dd></div>}
  </dl>;
}

/**
 * **「장애물 탐지」 액션 아이템.** 여는 동안 폴링을 붙잡는다 — 판이 안 열려 있어도(제안 중) 지금 값이 보인다.
 */
export function ObstacleFacts() {
  useEffect(() => holdObstaclePolling(), []);
  const obstacle = useObstacle();
  const snap = obstacle.latest;
  const frozen = obstacleFrozen(obstacle);
  const replaying = useReplayTarget() !== null;
  return <div className="obstacle-facts">
    <Freshness snap={snap} error={obstacle.error} frozen={frozen} replaying={replaying} />
    {snap === null
      ? <p className="robot-log__empty">{obstacle.error === null ? '첫 값을 받는 중입니다…' : '아직 한 건도 못 받았습니다 — 위 사유를 보세요'}</p>
      : <>
          <p className="vn-line">탐지 <b>{snap.detections.length}</b>건 · has_near_obstacle <b>{String(snap.hasNearObstacle)}</b> · state_change <b>{String(snap.stateChange)}</b>{snap.cameraId === null ? '' : ` · ${snap.cameraId}`}</p>
          {snap.detections.length > 0 && <table className="obstacle-table">
            <thead><tr><th>id</th><th>대상</th><th>거리</th><th>rel_depth</th><th>risk</th><th>bbox_xyxy</th></tr></thead>
            <tbody>{snap.detections.map((d, index) => <DetectionRow key={`${d.id ?? 'x'}-${index}`} d={d} />)}</tbody>
          </table>}
          <details className="obstacle-raw">
            <summary>받은 JSON 그대로</summary>
            <pre>{JSON.stringify(snap.raw, null, 2)}</pre>
          </details>
        </>}
    <h4>바뀐 것 · 이 판</h4>
    {obstacle.log.length === 0
      ? <p className="robot-log__empty">아직 바뀐 것이 없습니다 — 가까운 장애물이 생기거나 사라지면 여기에 쌓입니다</p>
      : <ol className="robot-log__lines">
          {obstacle.log.map((line, index) => <li key={`${line.atMs}-${index}`} className={line.level === 'warn' ? 'is-result' : 'is-status'}>
            <time>{clock(line.atMs)}</time><span>{line.text}</span>
          </li>)}
        </ol>}
  </div>;
}

/**
 * **판단 근거.** 판정은 AI 서버의 `has_near_obstacle` 이다 — 화면이 거리로 다시 판정하지 않는다.
 * 근거로 그 판정에 걸린 것(`risk_level: near`)과 나머지를 거리순으로 적는다.
 */
export function ObstacleEvidence() {
  const obstacle = useObstacle();
  const snap = obstacle.latest;
  if (snap === null) {
    return <p className="evidence-image__empty">장애물 판정이 아직 안 왔습니다 — {obstacle.polling ? '받는 중입니다' : '자율주행 판을 열거나 액션 아이템을 열면 받습니다'}</p>;
  }
  const near = snap.detections.filter((d) => d.riskLevel === 'near');
  const byDistance = [...snap.detections].sort((a, b) => (a.distanceCm ?? Infinity) - (b.distanceCm ?? Infinity));
  const verdict = snap.hasNearObstacle === null
    ? '판정 값(has_near_obstacle)이 없습니다'
    : snap.hasNearObstacle
      ? `가까운 장애물 있음 — ${near.length === 0 ? 'near 로 표시된 대상은 없습니다' : near.map((d) => `${d.name}(${d.group ?? '분류 없음'}) ${cm(d.distanceCm)}`).join(', ')}`
      : '가까운 장애물 없음';
  return <>
    <p className={`evidence-reason${snap.hasNearObstacle ? ' evidence-reason--warn' : ''}`}>{verdict}</p>
    <p className="vn-line vn-dim">AI 서버 판정 · {clock(snap.receivedAtMs)} 수신{obstacleFrozen(obstacle) ? ' · ⚠ 서버 값이 멈춰 있습니다' : ''}{obstacle.error === null ? '' : ` · 지금 못 받음(${obstacle.error})`}</p>
    {byDistance.length > 0 && <ul className="obstacle-evidence">
      {byDistance.map((d, index) => <li key={`${d.id ?? 'x'}-${index}`} className={d.riskLevel === 'near' ? 'is-near' : undefined}>
        <b>{d.name}</b> {cm(d.distanceCm)} · {d.riskLevel ?? '—'}{d.group === null ? '' : ` · ${d.group}`}
      </li>)}
    </ul>}
  </>;
}
