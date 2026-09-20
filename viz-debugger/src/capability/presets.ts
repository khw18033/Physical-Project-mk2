/**
 * src/capability/presets.ts (260920 신설 — 기능 상태 패널 이식)
 *
 * **기능 상태 서비스 주소의 네트워크 환경 프리셋.** 로봇(`src/physical/presets.ts`)·객체 탐지
 * (`src/detect/presets.ts`)와 같은 모양이고, 연결 관리가 같은 칸으로 그린다.
 *
 * ## 실제 배치는 k3s 안이다
 *
 * 검토용으로는 `python3 tools/status_ui/serve.py --control local --port 8765` 한 줄이면 노트북에
 * 서지만, **실제로는 그 서비스가 k3s 안에 선다**(전달본 「배치 모드와 한계」). 그때 주소는
 * 클러스터가 정하므로 **우리가 미리 적을 수 없다** — 연결 관리에 손으로 넣는다.
 *
 * 그래서 k3s 프리셋의 `url` 이 **비어 있다.** 빈 값은 「아직 없다」는 뜻이고 화면이 고를 수
 * 없게 막는다(`capabilityPresetReady`) — 없는 주소를 그럴싸하게 적어 두면 무대에서
 * 「왜 안 붙지」가 된다.
 *
 * **여기 밖에서 기능 상태 주소 문자열을 만들지 않는다** — 그 서비스를 아는 면은
 * `src/capability/` 하나다(`verify:capability-source`).
 */

/**
 * `label`·`why` 는 **사전 키**다. 글자가 아니다 — 이 목록은 모듈 최상위 상수라 `import` 때
 * 한 번 평가되고, 여기서 `t()` 를 부르면 그 순간의 언어로 굳는다(영문화 1단계 §3 ①).
 */
export type CapabilityPreset = {
  id: string;
  labelKey: string;
  /** 빈 문자열이면 **아직 값이 없다는 뜻**이다. 화면이 고를 수 없게 막는다. */
  url: string;
  whyKey: string;
};

export const CAPABILITY_PRESETS: readonly CapabilityPreset[] = [
  // 검토용 기본값 — 전달본의 실행 방법 그대로다.
  { id: 'local', labelKey: 'preset.capability.local', url: 'http://127.0.0.1:8765', whyKey: 'preset.capability.local.why' },
  // **실제 배치.** 주소를 클러스터가 정하므로 비워 둔다 — 정해지면 이 한 줄만 채운다.
  { id: 'k3s', labelKey: 'preset.capability.k3s', url: '', whyKey: 'preset.capability.k3s.why' },
  { id: 'manual', labelKey: 'preset.manual', url: '', whyKey: 'preset.manual.why' },
];

/** 고를 수 있는 프리셋인가. 값이 빈 것은 아직 없는 것이다. */
export function capabilityPresetReady(preset: CapabilityPreset): boolean {
  return preset.id === 'manual' || preset.url.trim() !== '';
}
