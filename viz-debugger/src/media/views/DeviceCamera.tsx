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
import { RecordFrame } from '../../record/RecordFrame.tsx';

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
function CameraCanvas({ cameraKey, live, nonce, recordLabel }: {
  cameraKey: string; live: boolean; nonce: number;
  /** 261007 — 있으면 실시간 영상 위에 녹화 버튼을 얹는다(파일 이름). */
  recordLabel?: string;
}) {
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
    {live && recordLabel !== undefined
      ? <RecordFrame label={recordLabel}><canvas ref={canvasRef} className="device-cam__canvas" /></RecordFrame>
      : <canvas ref={canvasRef} className="device-cam__canvas" />}
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
 * 장비에서 바로 받는 길 (260928). `stream` 은 끝나지 않는 MJPEG(Go1 뷰어), `frames` 는 한 번에 한 장(드론 영상 말단 —
 * 화면이 이어서 당긴다). 주소를 만드는 쪽(`physical/cameraView.ts`)과 **모양으로만** 맞춘다 — 이 폴더가 로봇 면을 import 하지 않게.
 */
export type DirectSource = { url: string; kind: 'stream' | 'frames' };

/** 한 장씩 받는 길에서 다음 장을 청하기까지 쉬는 시간. 말단 카메라가 8 fps 라 그보다 빨리 당겨도 같은 장이다. */
const FRAME_GAP_MS = 100;
/** 한 장씩 받는 길이 실패했을 때 다시 청하기까지. 매 틱 두드리면 말단이 꺼졌을 때 요청만 쌓인다. */
const FRAME_RETRY_MS = 2000;

/**
 * **장비에서 바로 받는 영상** (260928 — pi7 실측). 주소는 `src/physical/cameraView.ts` 가 만들어 넘긴다.
 *
 * MJPEG 라 `<img>` 로 받는다. 접힘은 **한 장을 그리고 곧바로 끊는다** — `<img>` 의 주소를 비우면 연결이 닫힌다.
 * 다른 출처라 캔버스에서 픽셀을 읽을 수는 없지만 그리는 것은 된다.
 */
export function DirectCamera({ url, live, nonce = 0, compact = false, frames = false, recordLabel }: {
  url: string; live: boolean; nonce?: number;
  /** 261007 — 있으면 실시간 영상 위에 녹화 버튼을 얹는다(파일 이름). 노드 카드처럼 끌어 옮기는 자리는 안 준다. */
  recordLabel?: string;
  /** 카드 — 설명 줄을 짧게, 주소는 툴팁으로. */
  compact?: boolean;
  /** 한 번에 한 장 주는 길(드론 말단). 실시간이면 그림이 도착할 때마다 다음 장을 청한다. */
  frames?: boolean;
}) {
  useLang();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [phase, setPhase] = useState<'waiting' | 'painted' | 'timeout' | 'failed'>('waiting');
  const [paintedAt, setPaintedAt] = useState<number | null>(null);
  /**
   * 한 장씩 받는 길의 차례 번호 (260928 — 드론). 주소 뒤에 붙여 매번 새 요청이 되게 한다. **앞 장이 도착한 뒤에**
   * 올린다 — 타이머로 올리면 느린 망에서 요청이 겹쳐 쌓이고, 그림이 뒤죽박죽 순서로 도착한다.
   */
  const [frameNo, setFrameNo] = useState(0);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (retryRef.current !== null) clearTimeout(retryRef.current); }, []);
  const nextFrame = (delayMs: number) => {
    if (!frames || !live) return;
    if (retryRef.current !== null) clearTimeout(retryRef.current);
    retryRef.current = setTimeout(() => setFrameNo((value) => value + 1), delayMs);
  };
  const liveSrc = frames ? `${url}${url.includes('?') ? '&' : '?'}n=${frameNo}` : url;

  useEffect(() => {
    if (live) return undefined;
    setPhase('waiting');
    const image = new Image();
    let done = false;
    // 주소를 비우면 연결이 닫히는데, 그때 브라우저가 `error` 를 낸다. 그것을 실패로 적으면 **잘 받은 뒤에**
    // 「못 붙었습니다」가 뜬다(260928 — 실제로 그랬다). 닫기 전에 귀를 뗀다.
    const close = () => { if (!done) { done = true; image.onerror = null; image.src = ''; } };
    image.onerror = () => { close(); setPhase('failed'); };
    image.src = url;
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      const canvas = canvasRef.current;
      if (image.naturalWidth > 0 && canvas !== null) {
        canvas.width = image.naturalWidth;
        canvas.height = image.naturalHeight;
        canvas.getContext('2d')?.drawImage(image, 0, 0);
        window.clearInterval(timer);
        close();
        setPaintedAt(Date.now());
        setPhase('painted');
        return;
      }
      if (Date.now() - startedAt > STILL_TIMEOUT_MS) { window.clearInterval(timer); close(); setPhase('timeout'); }
    }, 200);
    return () => { window.clearInterval(timer); close(); };
  }, [url, live, nonce]);

  const liveImg = <img className="device-cam__canvas" src={liveSrc} alt={url}
    onError={() => { setPhase('failed'); nextFrame(FRAME_RETRY_MS); }}
    onLoad={() => { setPhase('painted'); nextFrame(FRAME_GAP_MS); }} />;
  return <div className={`device-cam__stage${live ? ' device-cam__stage--live' : ''}`}>
    {live
      ? recordLabel !== undefined
        ? <RecordFrame label={recordLabel}>{liveImg}</RecordFrame>
        : liveImg
      : <canvas ref={canvasRef} className="device-cam__canvas" />}
    <p className="device-cam__meta" title={url}>
      {phase === 'failed'
        ? <b className="vn-warn">{t('dcam.directFailed', { url })}</b>
        : compact && live
          ? t('dcam.directLiveShort')
        : phase === 'timeout'
          ? <b className="vn-warn">{t('dcam.directTimeout', { sec: STILL_TIMEOUT_MS / 1000, url })}</b>
          : live
            ? t('dcam.directLive', { url })
            : paintedAt === null ? t('dcam.directWaiting', { url }) : t('dcam.directStill', { url, clock: clock(paintedAt) })}
    </p>
  </div>;
}

/**
 * 카메라 노드의 본문. `taskDeviceId` 는 연결한 태스크의 대상(자리를 푼 값)이다.
 *
 * `directUrlOf` 가 주소를 주면 장비에서 **바로** 받고, 안 주면 백엔드 `/media` 로 받는다 (260928).
 * 주소를 만드는 것은 이 파일이 아니다 — 로봇 주소를 아는 면은 `src/physical/` 하나다.
 */
export function DeviceCamera({ nodeId, taskDeviceId, zoom = false, directUrlOf }: {
  nodeId: string;
  taskDeviceId: string | null;
  zoom?: boolean;
  directUrlOf?: (deviceId: string, position: string) => DirectSource | null;
}) {
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
  } else if (directUrlOf?.(deviceId, choice.position) != null) {
    /**
     * **로봇 노드에서 바로 받는 영상은 카드에서도 흐른다** (260928 지시 — 「확대하면 되는데 그래프에서는 안 움직인다」).
     *
     * `/media` 카드는 여전히 한 장이다(`VZ-I-06`). 이쪽은 로봇 노드가 보는 사람 수와 상관없이 상류 연결 하나로
     * 나눠 주고(`go1_cam_view` — 아무도 안 보면 20초 뒤 끊는다), 카드 하나가 여는 것은 MJPEG 한 줄이다.
     * 카드를 지우거나 화면을 떠나면 `<img>` 가 사라지면서 닫힌다.
     */
    body = <>
      {chosenOffline && <p className="vn-line vn-warn">{t('dcam.notConnectedNow', { device: deviceId })}</p>}
      <DirectCamera url={directUrlOf(deviceId, choice.position)!.url} frames={directUrlOf(deviceId, choice.position)!.kind === 'frames'} live nonce={nonce} compact={!zoom}
        recordLabel={zoom ? `${deviceId}_${choice.position}` : undefined} />
    </>;
  } else if (mediaBaseUrl() === '') {
    body = <p className="vn-line vn-dim">{t('dcam.noAddress')}</p>;
  } else {
    body = <>
      {chosenOffline && <p className="vn-line vn-warn">{t('dcam.notConnectedNow', { device: deviceId })}</p>}
      <CameraCanvas cameraKey={cameraKey} live={zoom} nonce={nonce} recordLabel={`${deviceId}_${choice.position}`} />
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
