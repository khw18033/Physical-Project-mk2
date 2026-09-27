/**
 * src/media/views/DeviceCamera.tsx (260927 신설 — 카메라 뷰 노드)
 *
 * **고른 장치의 카메라.** 노드는 한 종류이고, 「첫 번째 장치 카메라」와 「두 번째 장치 카메라」는
 * 그 노드 두 장이 서로 다른 장치를 고른 것이다. 장치마다 버튼을 늘리지 않는다(260927 지시).
 *
 * 고르는 자리는 **확대(더블클릭)** 다. 목록은 지금 연결이 유지되는 장치 — 하드웨어 카드에 뜨는 것과
 * 같은 목록이다(`shared/connectedDevices.ts`). 안 붙은 장치를 고를 수 있게 두면 그 카메라는 영원히
 * 「기다립니다」로 남고, 왜인지 알 수 없다.
 *
 * 고르지 않았으면 **연결한 태스크의 장치**를 쓴다 — 단 그 장치가 지금 붙어 있을 때만이다. 자리 이름
 * (`device-1`)이 그대로 오면(아직 배정 전) 카메라 키를 지어 붙이지 않는다.
 *
 * ## 접힘은 한 장, 실시간은 확대
 *
 * 옛 영상 노드와 같은 규칙이다(`VZ-I-06`). 카드마다 소켓을 열어 두면 카드 수만큼 스트림이 돈다.
 * 접힘은 **한 장을 그리면 곧바로 끊는다.**
 *
 * 영상 소켓의 전역 수(`media/store.ts`)는 건드리지 않는다 — 그 수는 대상 상태 오버레이의 진단 칸이
 * 세는 것이고, 카메라 노드 둘이 같이 올리면 무엇의 수인지 알 수 없게 된다.
 */

import { useEffect, useRef, useState } from 'react';
import { t } from '../../i18n/dict.ts';
import { useLang } from '../../shared/language.ts';
import { useConnections } from '../../shared/connections.ts';
import { useConnectedDevices } from '../../shared/connectedDevices.ts';
import { useReplayTarget } from '../../record/replayMode.ts';
import { createDecoder } from '../decode.ts';
import { mediaBaseUrl, openMedia } from '../MediaClient.ts';
import { isNewSession, type MediaFrameRef } from '../parse.ts';
import { CAMERA_POSITIONS, cameraKeyOf, setCameraChoice, useCameraChoice, type CameraPosition } from '../cameraChoice.ts';

/** 접힘이 한 장을 기다리는 한도. 넘기면 「안 온다」고 적고 끊는다. */
const STILL_TIMEOUT_MS = 8000;
const clock = (ms: number) => new Date(ms).toTimeString().slice(0, 8);

type Feed = {
  phase: 'waiting' | 'painted' | 'timeout' | 'failed';
  received: number;
  decoded: number;
  paintedAtMs: number | null;
  error: string | null;
};

const START: Feed = { phase: 'waiting', received: 0, decoded: 0, paintedAtMs: null, error: null };

/** 카메라 키 하나를 그린다. `live` 가 아니면 한 장을 그리고 끊는다. */
function CameraCanvas({ cameraKey, live, nonce }: { cameraKey: string; live: boolean; nonce: number }) {
  useLang();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [feed, setFeed] = useState<Feed>(START);
  // 주소·토큰이 바뀌면 다시 붙는다 — 연결 설정의 규칙 그대로다.
  const connections = useConnections();

  useEffect(() => {
    setFeed(START);
    const decoder = createDecoder();
    let lastRef: MediaFrameRef | null = null;
    let received = 0;
    let done = false;
    const socket = openMedia({
      onOpen: () => undefined,
      onFrame: (frame) => {
        if (isNewSession(lastRef, frame.header.frameRef)) decoder.reset();
        lastRef = frame.header.frameRef;
        received += 1;
        decoder.push(frame);
      },
      onParseError: () => { received += 1; },
      onTextMessage: () => undefined,
      onClose: (code, retrying) => {
        if (!retrying) setFeed((f) => ({ ...f, phase: 'failed', error: t('dcam.closed', { code }) }));
      },
      onError: (reason) => setFeed((f) => ({ ...f, phase: 'failed', error: reason })),
    }, undefined, cameraKey);

    const halt = () => {
      if (done) return;
      done = true;
      socket.close();
    };
    const startedAt = Date.now();
    // 수는 1초에 한 번만 올린다 — 그림은 매 틱 그리되 React 는 매 틱 다시 그리지 않는다(`VZ-I-06`).
    let shownAt = 0;
    let painting = false;
    // rAF 가 아니라 주기로 가져간다 — 탭이 뒤로 가도 마지막 그림이 올라가고(MediaSection 과 같은 사정),
    // 접힘은 어차피 한 장이다.
    const timer = window.setInterval(() => {
      const painted = decoder.latest();
      const canvas = canvasRef.current;
      if (painted !== null && canvas !== null) {
        if (canvas.width !== painted.width) canvas.width = painted.width;
        if (canvas.height !== painted.height) canvas.height = painted.height;
        canvas.getContext('2d')?.drawImage(painted.bitmap as CanvasImageSource, 0, 0);
        if (!painting || Date.now() - shownAt >= 1000) {
          painting = true;
          shownAt = Date.now();
          setFeed((f) => ({ ...f, phase: 'painted', received, decoded: decoder.stats().decoded, paintedAtMs: f.paintedAtMs ?? Date.now() }));
        }
        if (!live) { window.clearInterval(timer); halt(); }
        return;
      }
      if (Date.now() - shownAt >= 1000) {
        shownAt = Date.now();
        setFeed((f) => ({ ...f, received, decoded: decoder.stats().decoded }));
      }
      if (!live && Date.now() - startedAt > STILL_TIMEOUT_MS) {
        window.clearInterval(timer);
        halt();
        setFeed((f) => (f.phase === 'failed' ? f : { ...f, phase: 'timeout' }));
      }
    }, live ? 100 : 250);

    return () => {
      window.clearInterval(timer);
      halt();
      decoder.close();
    };
  }, [cameraKey, live, nonce, connections]);

  return <div className={`device-cam__stage${live ? ' device-cam__stage--live' : ''}`}>
    <canvas ref={canvasRef} className="device-cam__canvas" />
    <p className="device-cam__meta">
      {feed.phase === 'failed'
        ? <b className="vn-warn">{t('dcam.error', { reason: feed.error ?? '' })}</b>
        : feed.phase === 'timeout'
          ? <b className="vn-warn">{t('dcam.noFrame', { sec: STILL_TIMEOUT_MS / 1000, key: cameraKey })}</b>
          : feed.phase === 'waiting'
            ? t('dcam.waiting', { key: cameraKey })
            : live
              ? t('dcam.liveMeta', { key: cameraKey, received: feed.received, decoded: feed.decoded })
              : t('dcam.stillMeta', { key: cameraKey, clock: clock(feed.paintedAtMs ?? Date.now()) })}
    </p>
  </div>;
}

/**
 * 카메라 노드의 본문. `taskDeviceId` 는 연결한 태스크의 대상(자리를 푼 값)이다.
 */
export function DeviceCamera({ nodeId, taskDeviceId, zoom = false }: { nodeId: string; taskDeviceId: string | null; zoom?: boolean }) {
  useLang();
  const choice = useCameraChoice(nodeId);
  const connected = useConnectedDevices();
  const replaying = useReplayTarget();
  const [nonce, setNonce] = useState(0);
  useConnections();

  const connectedIds = connected.map((device) => device.entityId);
  // 태스크의 장치는 **지금 붙어 있을 때만** 대신 쓴다. 자리 이름이 그대로 오면 붙은 장치가 아니다.
  const fallback = taskDeviceId !== null && connectedIds.includes(taskDeviceId) ? taskDeviceId : null;
  const deviceId = choice.deviceId ?? fallback;
  const cameraKey = cameraKeyOf(choice, fallback);
  const chosenOffline = choice.deviceId !== null && !connectedIds.includes(choice.deviceId);

  const picker = zoom && <div className="device-cam__pick" onPointerDown={(event) => event.stopPropagation()}>
    <label>{t('dcam.device')}
      <select value={choice.deviceId ?? ''} onChange={(event) => setCameraChoice(nodeId, { deviceId: event.target.value === '' ? null : event.target.value })}>
        <option value="">{fallback === null ? t('dcam.none') : t('dcam.fromTask', { device: fallback })}</option>
        {/* 고른 장치가 지금 목록에 없어도 칸에서는 보이게 둔다 — 사라지면 무엇을 골랐는지 모른다. */}
        {choice.deviceId !== null && !connectedIds.includes(choice.deviceId) && <option value={choice.deviceId}>{choice.deviceId}</option>}
        {connectedIds.map((id) => <option key={id} value={id}>{id}</option>)}
      </select>
    </label>
    <label title={t('dcam.keyTitle')}>{t('dcam.position')}
      <select value={choice.position} onChange={(event) => setCameraChoice(nodeId, { position: event.target.value as CameraPosition })}>
        {CAMERA_POSITIONS.map((position) => <option key={position} value={position}>{position}</option>)}
      </select>
    </label>
    {connectedIds.length === 0 && <p className="vn-line vn-dim">{t('dcam.noConnected')}</p>}
  </div>;

  let body;
  if (replaying !== null) {
    // 영상은 기록하지 않는다 — 지금 영상을 지난 판 자리에 띄우면 그때 본 것으로 읽힌다(자율주행 편과 같은 규칙).
    body = <p className="vn-line vn-dim">{t('dcam.replay')}</p>;
  } else if (deviceId === null || cameraKey === null) {
    body = <p className="vn-line vn-dim">{t(zoom ? 'dcam.pickAbove' : 'dcam.pickDevice')}</p>;
  } else if (mediaBaseUrl() === '') {
    body = <p className="vn-line vn-dim">{t('dcam.noAddress')}</p>;
  } else {
    body = <>
      {chosenOffline && <p className="vn-line vn-warn">{t('dcam.notConnectedNow', { device: deviceId })}</p>}
      <CameraCanvas cameraKey={cameraKey} live={zoom} nonce={nonce} />
      {!zoom && <p className="vn-line vn-dim">
        <button type="button" className="vn-refresh" onPointerDown={(event) => event.stopPropagation()} onClick={() => setNonce((value) => value + 1)}>{t('dcam.fetchAgain')}</button>
      </p>}
    </>;
  }

  return <div className={`device-cam${zoom ? ' device-cam--zoom' : ''}`}>
    {!zoom && <p className="vn-line"><b>{deviceId ?? '—'}</b>{cameraKey === null ? null : <small> · {choice.position}</small>}</p>}
    {picker}
    {body}
  </div>;
}
