/**
 * src/vision/presets.ts (261001 신설 — 객체 탐지 추론 스트림)
 *
 * **스트림 서버의 주소와 포트 넷.** 서버(`server_stream_multi_source.py`)는 포트 하나가 소스 하나다 —
 * 10001 cam360 · 10002 drone · 10003 robot1 · 10004 robot2. 어느 장비가 어느 소스인지는 **여기서 정하지 않는다**
 * (`binding.ts` — 서버가 알려 주는 파이 주소와 장비의 브로커 주소를 맞대 본다).
 *
 * **주소와 포트를 칸으로 가른다** (261001 지시). 현장에서는 서버 IP 만 바뀌고 포트는 그대로인 일이 생긴다 —
 * 그때 IP 칸 하나만 고치면 포트 넷이 다 따라간다. 포트 칸에는 번호만 적는다.
 *
 * 주소는 서버(sysai-server2)의 테일넷 주소다. 공인 주소는 적지 않는다 — 같은 기기의 다른 서버(장애물 탐지 AI)가
 * 그 주소를 쓰고, 그 주소는 `src/autodrive/` 경계 밖에 적지 않는다(`verify:autodrive-ai`).
 */

export type VisionPreset = {
  id: string;
  labelKey: string;
  url: string;
  whyKey: string;
};

/** 스트림 서버 호스트 (261001 사용자가 준 테일넷 주소). */
export const VISION_STREAM_HOST = 'http://100.102.8.102';

/** 서버가 여는 포트 — 순서가 서버의 `SOURCES` 순서다. */
export const VISION_STREAM_PORTS: readonly { port: number; source: string }[] = [
  { port: 10001, source: 'cam360' },
  { port: 10002, source: 'drone' },
  { port: 10003, source: 'robot1' },
  { port: 10004, source: 'robot2' },
];

export const VISION_DEFAULT_PORTS: readonly string[] = VISION_STREAM_PORTS.map(({ port }) => String(port));

/** IP 칸에서 고르는 것. */
export const VISION_HOST_PRESETS: readonly VisionPreset[] = [
  { id: 'tailnet', labelKey: 'preset.vision.hostTailnet', url: VISION_STREAM_HOST, whyKey: 'preset.vision.why' },
  { id: 'manual', labelKey: 'preset.manual', url: '', whyKey: 'preset.manual.why' },
];

/** 포트 줄마다 고르는 것 — 값이 번호뿐이다. */
export const VISION_PORT_PRESETS: readonly VisionPreset[] = [
  ...VISION_STREAM_PORTS.map(({ port, source }) => ({
    id: source,
    labelKey: `preset.vision.${source}`,
    url: String(port),
    whyKey: 'preset.vision.portWhy',
  })),
  { id: 'manual', labelKey: 'preset.manual', url: '', whyKey: 'preset.manual.why' },
];

export function visionPresetReady(preset: VisionPreset): boolean {
  return preset.id === 'manual' || preset.url.trim() !== '';
}
