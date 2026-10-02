/**
 * src/media/presets.ts (260921 신설 — `/media` 수신 경로)
 *
 * **영상 소켓 주소의 네트워크 환경 프리셋.** 기능 상태(`src/capability/presets.ts`)·
 * 객체 탐지와 같은 모양이고, 연결 관리가 같은 칸으로 그린다.
 *
 * ## 주소를 미리 적을 수 없다
 *
 * 서버는 tailnet 안에 있고 그 주소는 **방화벽에 우리 기기가 등록된 뒤에** 받는다.
 * 그래서 프리셋의 `url` 이 **비어 있다.** 빈 값은 「아직 없다」는 뜻이고 화면이 고를 수
 * 없게 막는다(`mediaPresetReady`) — 없는 주소를 그럴싸하게 적어 두면 무대에서
 * 「왜 안 붙지」가 되고, 그 원인이 방화벽이라 토큰·코드를 먼저 뒤지게 된다.
 *
 * **여기 밖에서 영상 소켓 주소를 만들지 않는다** — 그 서비스를 아는 면은 `src/media/`
 * 하나다(`verify:media-port`).
 */

export type MediaPreset = {
  id: string;
  labelKey: string;
  /** 빈 문자열이면 **아직 값이 없다는 뜻**이다. 화면이 고를 수 없게 막는다. */
  url: string;
  whyKey: string;
};

export const MEDIA_PRESETS: readonly MediaPreset[] = [
  // **실측 서버.** 주소는 tailnet 값이라 커밋하지 않는다 — 연결 관리에 손으로 넣는다.
  { id: 'server', labelKey: 'preset.media.server', url: '', whyKey: 'preset.media.server.why' },
  { id: 'manual', labelKey: 'preset.manual', url: '', whyKey: 'preset.manual.why' },
];

/** 고를 수 있는 프리셋인가. 값이 빈 것은 아직 없는 것이다. */
export function mediaPresetReady(preset: MediaPreset): boolean {
  return preset.id === 'manual' || preset.url.trim() !== '';
}
