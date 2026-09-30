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

import { useLang } from '../../shared/language.ts';
import { Rich } from '../../i18n/RichText.tsx';
import { t } from '../../i18n/dict.ts';
import { useEffect, useState } from 'react';
import { aiBase, aiBases, aiControlUrl, aiFrameUrl, aiStreamUrl, AI_CAMERA } from '../aiClient.ts';
import { holdObstaclePollingAt, obstacleFrozen, useObstacleAt, type ObstacleDetection, type ObstacleSnapshot, obstacleLineText } from '../obstacle.ts';
import { setObstacleSource, useObstacleSource } from '../sourceChoice.ts';
import { useConnections } from '../../shared/connections.ts';
import { CuedVideo } from '../../imagery/CuedVideo.tsx';
import { useReplayTarget } from '../../record/replayMode.ts';

const clock = (ms: number) => new Date(ms).toTimeString().slice(0, 8);
const cm = (value: number | null) => (value === null ? '—' : `${value.toFixed(1)} cm`);

/** 접힌 카드가 새 한 장을 받는 주기. */
export const CAM_STILL_MS = 2000;

/**
 * **이 노드가 볼 주소** (260929 — 장애물 탐지 주소 둘 이상). 노드가 고른 주소, 없으면 연결 관리 목록의 첫 줄.
 * `nodeId` 가 없으면(액션 아이템 · 판단 근거) 언제나 첫 줄이다 — 자율주행 편의 판정이 보는 열이다.
 */
function useAiSource(nodeId: string | undefined): { base: string; chosen: string | null } {
  useConnections();
  const chosen = useObstacleSource(nodeId ?? '');
  const picked = nodeId === undefined ? null : chosen;
  return { base: picked ?? aiBase(), chosen: picked };
}

/**
 * **주소 고르기** — 확대에서만 그린다. 카드는 끌기가 먼저라 고르는 칸을 두지 않는다(카메라 노드와 같다).
 * 목록에서 빠진 주소를 골라 두었으면 그 주소를 그대로 보이고 「목록에 없음」을 붙인다 — 말없이 첫 줄로 바꾸지 않는다.
 */
export function AiSourcePicker({ nodeId }: { nodeId: string }) {
  useLang();
  useConnections();
  const chosen = useObstacleSource(nodeId);
  const bases = aiBases();
  const missing = chosen !== null && !bases.includes(chosen);
  return <label className="ai-source">
    <span>{t('adv.sourcePick')}</span>
    <select value={chosen ?? ''} onChange={(event) => setObstacleSource(nodeId, event.target.value === '' ? null : event.target.value)}>
      <option value="">{t('adv.sourceFirst', { url: bases[0] ?? t('adv.sourceNone') })}</option>
      {bases.slice(1).map((base) => <option key={base} value={base}>{base}</option>)}
      {missing && <option value={chosen}>{t('adv.sourceMissing', { url: chosen })}</option>}
    </select>
    {bases.length <= 1 && <small>{t('adv.sourceOnlyOne')}</small>}
  </label>;
}

/**
 * **탐지 영상 노드** (260929). 고른 주소에 동영상을 붙였고 이 편이 재생 시점을 적었으면(이상 탐지 편 「첫 번째 장치
 * 이동」) 그 영상을, 아니면 실시간 영상을 그린다. 동영상은 **주소마다 따로**다 — 키가 `autodrive-ai.video@<주소>`.
 */
export function AiCuedCam({ zoom = false, nodeId }: { zoom?: boolean; nodeId: string }) {
  const { base } = useAiSource(nodeId);
  return <>
    {zoom && <AiSourcePicker nodeId={nodeId} />}
    <CuedVideo target="autodrive-ai" storageKey={`autodrive-ai.video@${base}`} zoom={zoom}>
      <AutodriveCam zoom={zoom} nodeId={nodeId} hidePicker />
    </CuedVideo>
  </>;
}

export function AutodriveCam({ zoom = false, nodeId, hidePicker = false }: { zoom?: boolean; nodeId?: string; hidePicker?: boolean }) {
  useLang();
  const { base } = useAiSource(nodeId);
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
    return <p className="vn-line vn-dim">{t('adv.1')}</p>;
  }
  if (base === '') {
    return <p className="vn-line vn-dim">{t('adv.2')}</p>;
  }
  const src = zoom ? aiStreamUrl(base) : aiFrameUrl(nonce, base);
  return <div className={`detect-cam autodrive-cam${zoom ? ' detect-cam--zoom' : ''}`}>
    {zoom && nodeId !== undefined && !hidePicker && <AiSourcePicker nodeId={nodeId} />}
    <img
      // 확대는 주소가 안 바뀌어야 스트림이 안 끊긴다. 접힘은 한 장마다 새 요소가 아니라 새 주소다.
      src={src}
      alt={t('adv.camAlt', { cam: AI_CAMERA })}
      onLoad={() => { setLoadedAt(Date.now()); setFailed(null); }}
      onError={() => setFailed(zoom
        ? t('adv.streamFailed', { url: aiStreamUrl(base) })
        : t('adv.3'))}
    />
    <p className="detect-cam__at">
      {failed !== null
        ? <b className="vn-warn">{failed}</b>
        : zoom
          ? <>{t('adv.4')} <code>{aiStreamUrl(base)}</code></>
          : <>{loadedAt === null ? t('adv.firstFrame') : t('adv.stillMeta', { clock: clock(loadedAt), sec: CAM_STILL_MS / 1000 })}
              {aiBases().length > 1 && <small className="ai-source__at"> · {base}</small>}</>}
    </p>
  </div>;
}

/** 탐지 한 줄. 받은 칸만 적는다. */
function DetectionRow({ d }: { d: ObstacleDetection }) {
  useLang();
  return <tr className={d.riskLevel === 'near' ? 'is-near' : undefined}>
    <td>{d.id ?? '—'}</td>
    <td><b>{d.name}</b>{d.group === null ? null : <small> {d.group}</small>}</td>
    <td>{cm(d.distanceCm)}<small> {t('adv.raw', { value: cm(d.distanceCmRaw) })}</small></td>
    <td>{d.relDepth === null ? '—' : d.relDepth.toFixed(3)}</td>
    <td>{d.riskLevel ?? '—'}</td>
    <td><code>{d.bbox === null ? '—' : d.bbox.join(', ')}</code></td>
  </tr>;
}

function Freshness({ snap, error, frozen, replaying, base }: { snap: ObstacleSnapshot | null; error: string | null; frozen: boolean; replaying: boolean; base: string }) {
  useLang();
  return <dl className="device-facts">
    <div><dt>{t('adv.5')}</dt><dd><code>{aiControlUrl(base)}</code></dd></div>
    {/* 다시보기에서는 「몇 초 전」을 안 적는다 — 지난 판의 값이라 지금과의 차이는 뜻이 없다. */}
    {snap !== null && <div><dt>{t(replaying ? 'adv.recordedLast' : 'adv.lastReceived')}</dt><dd>{clock(snap.receivedAtMs)}{replaying ? '' : t('adv.secondsAgo', { sec: Math.round((Date.now() - snap.receivedAtMs) / 1000) })}{snap.timestampSec === null ? '' : t('adv.serverClock', { sec: snap.timestampSec.toFixed(3) })}{frozen && !replaying ? t('adv.frozen5s') : ''}</dd></div>}
    {error !== null && <div><dt>{t('adv.6')}</dt><dd className="vn-warn">{t('adv.notReceiving', { reason: error })}</dd></div>}
  </dl>;
}

/**
 * **「장애물 탐지」 액션 아이템.** 여는 동안 폴링을 붙잡는다 — 판이 안 열려 있어도(제안 중) 지금 값이 보인다.
 */
export function ObstacleFacts({ nodeId }: { nodeId?: string } = {}) {
  useLang();
  const { base, chosen } = useAiSource(nodeId);
  useEffect(() => holdObstaclePollingAt(chosen), [chosen]);
  const obstacle = useObstacleAt(chosen);
  const snap = obstacle.latest;
  const frozen = obstacleFrozen(obstacle);
  const replaying = useReplayTarget() !== null;
  return <div className="obstacle-facts">
    {nodeId !== undefined && <AiSourcePicker nodeId={nodeId} />}
    <Freshness snap={snap} error={obstacle.error} frozen={frozen} replaying={replaying} base={base} />
    {snap === null
      ? <p className="robot-log__empty">{obstacle.error === null ? t('adv.7') : t('adv.8')}</p>
      : <>
          <p className="vn-line"><Rich id="adv.snapLine" vars={{ n: snap.detections.length, near: String(snap.hasNearObstacle), change: String(snap.stateChange) }} />{snap.cameraId === null ? '' : ` · ${snap.cameraId}`}</p>
          {snap.detections.length > 0 && <table className="obstacle-table">
            <thead><tr><th>id</th><th>{t('adv.9')}</th><th>{t('adv.10')}</th><th>rel_depth</th><th>risk</th><th>bbox_xyxy</th></tr></thead>
            <tbody>{snap.detections.map((d, index) => <DetectionRow key={`${d.id ?? 'x'}-${index}`} d={d} />)}</tbody>
          </table>}
          <details className="obstacle-raw">
            <summary>{t('adv.11')}</summary>
            <pre>{JSON.stringify(snap.raw, null, 2)}</pre>
          </details>
        </>}
    <h4>{t('adv.12')}</h4>
    {obstacle.log.length === 0
      ? <p className="robot-log__empty">{t('adv.13')}</p>
      : <ol className="robot-log__lines">
          {obstacle.log.map((line, index) => <li key={`${line.atMs}-${index}`} className={line.level === 'warn' ? 'is-result' : 'is-status'}>
            <time>{clock(line.atMs)}</time><span>{obstacleLineText(line)}</span>
          </li>)}
        </ol>}
  </div>;
}

/**
 * **판단 근거.** 판정은 AI 서버의 `has_near_obstacle` 이다 — 화면이 거리로 다시 판정하지 않는다.
 * 근거로 그 판정에 걸린 것(`risk_level: near`)과 나머지를 거리순으로 적는다.
 */
export function ObstacleEvidence() {
  useLang();
  const obstacle = useObstacleAt(null);
  const snap = obstacle.latest;
  if (snap === null) {
    return <p className="evidence-image__empty">{t('adv.noVerdictYet', { how: obstacle.polling ? t('adv.14') : t('adv.15') })}</p>;
  }
  const near = snap.detections.filter((d) => d.riskLevel === 'near');
  const byDistance = [...snap.detections].sort((a, b) => (a.distanceCm ?? Infinity) - (b.distanceCm ?? Infinity));
  const verdict = snap.hasNearObstacle === null
    ? t('adv.16')
    : snap.hasNearObstacle
      ? t('adv.nearPresent', {
        what: near.length === 0
          ? t('adv.noneMarkedNear')
          : near.map((d) => t('adv.nearItem', { name: d.name, group: d.group ?? t('adv.noGroup'), cm: cm(d.distanceCm) })).join(', '),
      })
      : t('adv.17');
  return <>
    <p className={`evidence-reason${snap.hasNearObstacle ? ' evidence-reason--warn' : ''}`}>{verdict}</p>
    <p className="vn-line vn-dim">{t('adv.verdictMeta', { clock: clock(snap.receivedAtMs) })}{obstacleFrozen(obstacle) ? t('adv.serverFrozen') : ''}{obstacle.error === null ? '' : t('adv.nowFailing', { reason: obstacle.error })}</p>
    {byDistance.length > 0 && <ul className="obstacle-evidence">
      {byDistance.map((d, index) => <li key={`${d.id ?? 'x'}-${index}`} className={d.riskLevel === 'near' ? 'is-near' : undefined}>
        <b>{d.name}</b> {cm(d.distanceCm)} · {d.riskLevel ?? '—'}{d.group === null ? '' : ` · ${d.group}`}
      </li>)}
    </ul>}
  </>;
}

/**
 * **객체 탐지 로그의 접힘 카드** (260927 — 장치 두 대 편).
 *
 * 확대는 「장애물 탐지」 액션 아이템과 **같은 것**(`ObstacleFacts`)을 그대로 쓴다 — 자율주행 편에서 쓰던
 * 것을 그대로 쓰라는 지시다. 카드에는 확대하지 않고도 이상함을 알아챌 값만 둔다: 판정 한 줄과 마지막 줄 셋.
 * 여는 동안 폴링을 붙잡는 것도 같다 — 판이 안 열려 있어도(대본 편) 지금 값이 보인다.
 */
export function ObstacleLogCard({ nodeId }: { nodeId?: string } = {}) {
  useLang();
  const { base, chosen } = useAiSource(nodeId);
  useEffect(() => holdObstaclePollingAt(chosen), [chosen]);
  const obstacle = useObstacleAt(chosen);
  const snap = obstacle.latest;
  const replaying = useReplayTarget() !== null;
  const recent = obstacle.log.slice(-3);
  return <div className="obstacle-facts obstacle-facts--card">
    {snap === null
      ? <p className="vn-line vn-dim">{obstacle.error === null ? t('adv.7') : t('adv.notReceiving', { reason: obstacle.error })}</p>
      : <p className="vn-line"><Rich id="adv.snapLine" vars={{ n: snap.detections.length, near: String(snap.hasNearObstacle), change: String(snap.stateChange) }} />
          <small> · {clock(snap.receivedAtMs)}{obstacleFrozen(obstacle) && !replaying ? t('adv.frozen5s') : ''}{aiBases().length > 1 ? ` · ${base}` : ''}</small></p>}
    {recent.length === 0
      ? <p className="vn-line vn-dim">{t('adv.13')}</p>
      : <ol className="robot-log__lines">
          {recent.map((line, index) => <li key={`${line.atMs}-${index}`} className={line.level === 'warn' ? 'is-result' : 'is-status'}>
            <time>{clock(line.atMs)}</time><span>{obstacleLineText(line)}</span>
          </li>)}
        </ol>}
  </div>;
}
