/**
 * src/media/views/MediaSection.tsx (260921 신설 — `/media` 수신 경로)
 *
 * **관문 B 를 판정하는 칸.** 성공 조건이 「canvas 에 그림이 한 장이라도 뜬다」이므로
 * 여기 그림이 뜨면 닫힌 것이다.
 *
 * ## 왜 대상 상태 오버레이 안인가 (260921 — 자리 수정)
 *
 * 처음에는 마일스톤 오른쪽 기둥에 **상설 판**으로 뒀는데 과했다. 영상은 늘 보는 값이
 * 아니라 **한 장비의 카메라에 딸린 것**이고, 기둥을 셋으로 나누면 하드웨어·기능 둘이
 * 그만큼 좁아진다.
 *
 * 이 오버레이가 제자리인 근거가 두 개 있다:
 *
 *   1. **원래 여기 있던 칸이다.** 이 파일 머리말이 *"카메라 연결 상태는 여전히 MQTT 로
 *      안 나온다 … 그 칸도 자리표시 대신 없앴다"* 라고 적어 뒀다 — 줄 값이 없어서 뺀
 *      자리이고, 이제 값이 생겼다.
 *   2. 백엔드도 같게 봤다 — `vz-media-interface.md` §8 이 카메라 상태를
 *      **「VZ-D-07 대상 상태 조회의 한 칸」**이라고 적었다.
 *
 * 뷰 노드는 축이 다르다. 뷰 노드는 **태스크**에 붙어 범위가 정해지는데(`VZ-N-02`)
 * 영상은 태스크가 아니라 카메라에 붙는다.
 *
 * ## 장비와 카메라의 대응표가 아직 없다
 *
 * 레지스트리가 그 표를 줄 것이고 그건 Phase 5/6 다(`vz-media-interface.md` §4).
 * 그래서 **지금은 연결 관리에 넣은 카메라 키 하나로 붙고**, 이 칸은 그 사실을 적는다 —
 * 장비마다 다른 카메라가 뜨는 척하지 않는다. 키가 이 장비 것으로 보이면 그렇다고 적고,
 * 아니면 아니라고 적는다. 어느 쪽이든 **화면이 아는 만큼만 말한다.**
 *
 * ## 안 뜰 때 **왜** 안 뜨는지가 이 판의 절반이다
 *
 * 이 경로의 가장 나쁜 실패는 「연결됨인데 영상만 안 옴」이고, 그 상태를 가르는 수가 넷이다:
 *
 *   받음 0        소켓은 열렸는데 프레임이 안 온다 — 엣지가 아직 안 붙었을 수 있다(정상)
 *   받음 > 뜯음   형식이 안 맞는다 — 사유별로 센 수가 어느 단계인지 말한다
 *   뜯음 > 그림   디코드가 안 된다 — 모르는 코덱이거나 디코더가 실패했다
 *   문자열 메시지 `/media` 에 원래 없다 — 엉뚱한 경로에 붙었다는 뜻일 수 있다
 *
 * 그래서 canvas 옆에 그 넷을 늘 적는다. 숫자가 없으면 어디가 막혔는지 알 수가 없다.
 *
 * ## 매 프레임 상태를 바꾸지 않는다
 *
 * rAF 루프는 **canvas 만 건드린다.** 디코드된 그림은 `decode.ts` 가 들고 있고 여기서
 * 가져간다 — 프레임마다 `setState` 하면 30Hz 리렌더가 되어 병합의 의미가 사라진다
 * (`VideoOverlayView` 머리말과 같은 규칙). 숫자 줄은 저장소 구독으로 따로 그려진다.
 *
 * ## 탭이 뒤로 가면 rAF 가 멈춘다
 *
 * HW 가 실기에서 겪은 것이다. 보조 타이머를 같이 돌려 멈춘 동안에도 마지막 그림이
 * 올라가게 한다.
 */

import { useEffect, useRef, useState } from 'react';
import { t } from '../../i18n/dict.ts';
import { useLang } from '../../shared/language.ts';
import { useConnections } from '../../shared/connections.ts';
import { createDecoder, EMPTY_DECODE_STATS, type DecodeStats } from '../decode.ts';
import { mediaBaseUrl, mediaSourceId, openMedia } from '../MediaClient.ts';
import { isNewSession, type MediaFrameRef } from '../parse.ts';
import {
  mediaClosed, mediaConnecting, mediaError, mediaFrame, mediaOpened, mediaParseError,
  mediaTextMessage, resetMedia, useMedia,
} from '../store.ts';

/** 탭이 뒤로 갔을 때의 보조 주기. rAF 가 멈춰도 마지막 그림은 올라간다. */
const FALLBACK_DRAW_MS = 500;

/**
 * 설정된 카메라 키가 이 장비 것으로 보이는가.
 *
 * 규약은 `<개체 키>_<위치>` 다(`vz-media-interface.md` §12 — 개체 키와 카메라 키는
 * **같은 체계의 다른 값**이다). 다만 그 규약은 HW 에 **요청한** 것이라 확정이 아니므로,
 * 여기서 판정을 근거로 무언가를 막지 않는다 — 화면에 한 줄 적는 데만 쓴다.
 */
function looksLikeThisDevice(cameraKey: string, deviceId: string): boolean {
  return cameraKey === deviceId || cameraKey.startsWith(`${deviceId}_`);
}

export function MediaSection({ deviceId }: { deviceId: string }) {
  useLang();
  const media = useMedia();
  // 주소·카메라·토큰 중 하나라도 바뀌면 다시 붙는다 — 연결 설정의 규칙 그대로다.
  const connections = useConnections();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [stats, setStats] = useState<DecodeStats>(EMPTY_DECODE_STATS);
  const [on, setOn] = useState(false);

  const base = mediaBaseUrl();
  const source = mediaSourceId();

  useEffect(() => {
    if (!on) return undefined;

    const decoder = createDecoder();
    // **판정을 한 자리에서 한다.** 순번 역전은 `parse.isNewSession` 만 본다.
    let lastRef: MediaFrameRef | null = null;

    resetMedia();
    mediaConnecting();
    const socket = openMedia({
      onOpen: () => mediaOpened(),
      onFrame: (frame) => {
        const fresh = isNewSession(lastRef, frame.header.frameRef);
        if (fresh) decoder.reset();
        lastRef = frame.header.frameRef;
        mediaFrame(frame.header, fresh);
        decoder.push(frame);
      },
      onParseError: (reason) => mediaParseError(reason),
      onTextMessage: () => mediaTextMessage(),
      onClose: (code, retrying) => mediaClosed(code, retrying),
      onError: (reason) => mediaError(reason),
    });

    let raf = 0;
    const draw = (): void => {
      const canvas = canvasRef.current;
      const painted = decoder.latest();
      if (canvas !== null && painted !== null) {
        if (canvas.width !== painted.width) canvas.width = painted.width;
        if (canvas.height !== painted.height) canvas.height = painted.height;
        const ctx = canvas.getContext('2d');
        // `desynchronized` 를 쓰지 않는다 — vsync 한 주기를 아끼려다 찢김이 생긴다(HW 실기).
        if (ctx !== null) ctx.drawImage(painted.bitmap as CanvasImageSource, 0, 0);
      }
      setStats(decoder.stats());
    };
    const loop = (): void => { draw(); raf = requestAnimationFrame(loop); };
    raf = requestAnimationFrame(loop);
    const fallback = window.setInterval(draw, FALLBACK_DRAW_MS);

    return () => {
      cancelAnimationFrame(raf);
      window.clearInterval(fallback);
      socket.close();
      decoder.close();
      resetMedia();
    };
    // 주소 묶음이 바뀌면 붙던 것을 끊고 새로 붙는다.
  }, [on, connections]);

  const header = media.lastHeader;
  const parseFailed = Object.values(media.parseErrors).reduce((a, b) => a + b, 0);
  const ready = base !== '' && source !== '';

  return <section className="media-section">
    <header className="media-section__head">
      <h3>{t('media.title')}</h3>
      <div className="media-section__badges">
        {/* **끌 수 없다.** 이 판의 그림은 서버가 내보낸 바이트를 우리가 디코드한 것이고,
            숫자는 우리 쪽에서 센 것이다 — 서버가 잰 값이 아니다. */}
        <em className="cap-chip cap-chip--plain" title={t('media.badge.localTitle')}>{t('media.badge.local')}</em>
        <em className={`cap-chip cap-chip--${media.phase === 'open' ? 'ok' : media.phase === 'failed' ? 'bad' : 'unknown'}`}>
          {t(`media.phase.${media.phase}`)}
        </em>
      </div>
    </header>

    <p className="media-section__hint">{t('media.hint')}</p>

    {/* **대응표가 없다는 사실을 적는다.** 장비마다 다른 카메라가 뜨는 척하지 않는다. */}
    {ready && <p className="media-section__note">
      {looksLikeThisDevice(source, deviceId)
        ? t('media.cameraOfThis', { source })
        : t('media.cameraUnmapped', { source })}
    </p>}

    {!ready && <p className="media-section__note">{t('media.needAddress')}</p>}

    <div className="media-section__stage">
      <canvas ref={canvasRef} className="media-canvas" />
      {media.parsed === 0 && <p className="media-canvas__empty">
        {on ? t('media.waiting') : t('media.off')}
      </p>}
    </div>

    <dl className="media-section__counts">
      <div><dt>{t('media.count.received')}</dt><dd>{media.received}</dd></div>
      <div><dt>{t('media.count.parsed')}</dt><dd>{media.parsed}</dd></div>
      <div><dt>{t('media.count.decoded')}</dt><dd>{stats.decoded}</dd></div>
      <div><dt>{t('media.count.droppedBusy')}</dt><dd>{stats.droppedBusy}</dd></div>
      <div><dt>{t('media.count.sessions')}</dt><dd>{media.sessions}</dd></div>
    </dl>

    {/* 갈래마다 **왜** 안 나오는지. 0 이면 안 적는다 — 0 줄이 늘어서면 진짜가 안 보인다. */}
    {parseFailed > 0 && <p className="media-section__error">
      {t('media.parseFailed', {
        n: parseFailed,
        detail: Object.entries(media.parseErrors).filter(([, n]) => n > 0)
          .map(([reason, n]) => `${reason} ${n}`).join(' · '),
      })}
    </p>}
    {media.textMessages > 0 && <p className="media-section__error">{t('media.textMessages', { n: media.textMessages })}</p>}
    {stats.unsupported.length > 0 && <p className="media-section__error">{t('media.unsupported', { list: stats.unsupported.join(' · ') })}</p>}
    {stats.waitingKeyframe > 0 && stats.decoded === 0 && <p className="media-section__note">{t('media.waitingKeyframe', { n: stats.waitingKeyframe })}</p>}
    {stats.errors > 0 && <p className="media-section__error">{t('media.decodeErrors', { n: stats.errors })}</p>}
    {media.error !== null && <p className="media-section__error">{t('media.error', { reason: media.error })}</p>}
    {media.closeCode !== null && media.phase === 'failed' && <p className="media-section__error">{t('media.closed', { code: media.closeCode })}</p>}

    {header !== null && <dl className="media-section__facts">
      <dt>source_id</dt><dd>{header.frameRef.sourceId}</dd>
      <dt>sequence_id</dt><dd>{header.frameRef.sequenceId}</dd>
      <dt>capture_timestamp</dt><dd>{header.frameRef.captureTimestamp}</dd>
      <dt>encoding</dt><dd>{header.encoding}{header.keyframe ? ' · keyframe' : ''}</dd>
      <dt>codec</dt><dd>{header.codec ?? '—'}</dd>
      <dt>size</dt><dd>{header.width}×{header.height}</dd>
    </dl>}

    <footer className="media-section__foot">
      <span>{ready ? t('media.source', { base, source }) : t('media.noAddressShort')}</span>
      <button type="button" disabled={!ready} onClick={() => setOn(!on)}>
        {on ? t('media.stop') : t('media.start')}
      </button>
    </footer>
  </section>;
}
