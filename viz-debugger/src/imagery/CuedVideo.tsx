/**
 * src/imagery/CuedVideo.tsx (260929 신설 — 이상 탐지 편 · 붙인 동영상을 정해진 때 재생)
 *
 * **연결 관리에 붙인 동영상을, 대본이 정한 노드가 시작될 때 재생한다.**
 *
 *   탐지 영상      `params.media_cues['autodrive-ai']` — 이상 탐지 편은 「첫 번째 장치 이동」
 *   3D 가상환경   `params.media_cues['virtual-3d']`   — 이상 탐지 편은 「두 번째 장치 이동」
 *
 * 규칙 셋 (260929 결정).
 *  - **대본이 시점을 적은 편에서만** 튼다(2-A). 다른 임무는 지금처럼 실시간 화면이다.
 *  - 시점 전에는 **첫 장면에서 멈춰 둔다**(1-A).
 *  - 재생 위치는 **판의 시간**을 따른다 — 「시작된 뒤 몇 초」가 영상의 몇 초다. 일시정지 · 정지면 멈추고, 되감으면
 *    같이 되감긴다. 영상이 판보다 짧으면 마지막 장면에서 선다.
 *
 * 이 파일은 어느 노드인지 모른다 — 노드가 키(`imageStore` 의 칸)와 시점 태스크를 넘긴다.
 */

import { useEffect, useRef, useState } from 'react';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { displayMission, useMission } from '../data/scenario.ts';
import { useStoredImages } from '../shared/imageStore.ts';
import { cuePosition, cuesOf, type Cue } from './cue.ts';

/** 대본이 이 대상에 적은 재생 시점들. 없으면 빈 목록 — 그 편에서는 동영상을 안 쓴다. */
export function useMediaCues(target: 'autodrive-ai' | 'virtual-3d', defaultKey: string): Cue[] {
  const mission = useMission();
  const cues = mission.current.params.media_cues as Record<string, unknown> | undefined;
  return cuesOf(cues?.[target], defaultKey);
}

/**
 * 붙인 동영상이 있고 이 편에 시점이 있으면 그 영상을, 아니면 `children`(지금까지의 화면)을 그린다.
 *
 * **노드에는 영상만 보인다** (260929 지시). 언제 재생하는지 · 몇 초째인지 · 어느 파일인지를 적지 않는다 — 그것은
 * 연결 관리의 칸 이름과 대본에만 있다. 영상을 못 열 때의 안내만 남긴다(고칠 수 있게).
 */
export function CuedVideo({ target, storageKey, zoom = false, children }: {
  target: 'autodrive-ai' | 'virtual-3d';
  /** 대본이 칸을 따로 적지 않은 시점이 쓰는 칸. */
  storageKey: string;
  zoom?: boolean;
  children: React.ReactNode;
}) {
  useLang();
  useMission();
  const cues = useMediaCues(target, storageKey);
  const stored = useStoredImages(cues.map((cue) => cue.key));
  const { trace, headSec, phase } = displayMission();
  const position = cuePosition(trace, cues, headSec, phase === 'playing', (key) => stored[key] != null);
  if (position.cue === null) return <>{children}</>;
  const src = stored[position.cue.key]!.url;
  // 영상이 바뀌면(다음 시점) 새 요소로 — 앞 영상의 위치 · 상태를 끌고 가지 않는다.
  return <CueBody key={src} src={src} at={position.at} playing={position.playing} zoom={zoom} />;
}

function CueBody({ src, at, playing, zoom }: { src: string; at: number; playing: boolean; zoom: boolean }) {
  useLang();
  const ref = useRef<HTMLVideoElement>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    const video = ref.current;
    if (video === null) return;
    const end = Number.isFinite(video.duration) ? video.duration : Infinity;
    const want = Math.min(at, end);
    /**
     * **옮기는 것을 최소로 한다** (260929 실측 — Bandicam 녹화가 회색 블록으로 깨졌다). 키프레임 간격이 긴 영상은
     * 키프레임이 아닌 자리로 옮기면 다음 키프레임까지 회색으로 깨진다. 그래서 재생을 막 시작할 때 0.2초 같은 작은
     * 차이는 맞추지 않고 처음부터 튼다 — 판 시간과 1.5초 안쪽이면 그대로 둔다. 되감기처럼 크게 벌어졌을 때만 옮기고,
     * 그때는 가능하면 가까운 키프레임으로 옮긴다(`fastSeek`).
     */
    const seek = (to: number) => {
      try {
        const fast = (video as HTMLVideoElement & { fastSeek?: (time: number) => void }).fastSeek;
        if (typeof fast === 'function') fast.call(video, to);
        else video.currentTime = to;
      } catch { /* 메타데이터 전이면 다음 걸음에 */ }
    };
    if (!playing) {
      // 멈춰 있으면 판 시간에 맞춘다 — 시작 전(0) · 일시정지 · 되감기. 1.5초 안쪽은 그대로 둔다.
      video.pause();
      if (Math.abs(video.currentTime - want) > 1.5) seek(want);
    } else {
      // 재생 중에는 되감기 · 건너뛰기로 크게(3초 넘게) 벌어졌을 때만 옮긴다. 나머지는 영상이 제 속도로 간다.
      if (Math.abs(video.currentTime - want) > 3) seek(want);
      if (video.paused && want < end) void video.play().catch(() => undefined);
    }
  }, [at, playing]);

  return <div className={`cued-video${zoom ? ' cued-video--zoom' : ''}`}>
    <video
      ref={ref}
      src={src}
      muted
      playsInline
      preload="auto"
      onLoadedData={(event) => {
        // **그림 없이 소리만 풀린 영상** — 이 브라우저가 영상 코덱(예: HEVC/H.265)을 못 연다. 화면은 검게 남는다.
        setProblem(event.currentTarget.videoWidth === 0 ? t('cue.noPicture') : null);
      }}
      onError={(event) => setProblem(t('cue.cannotOpen', { code: event.currentTarget.error?.code ?? '?' }))}
    />
    {problem !== null && <p className="vn-line vn-warn">{problem}</p>}
  </div>;
}
