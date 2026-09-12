/**
 * src/detect/DetectClient.ts (260912 신설)
 *
 * **탐지를 아는 면 하나.** 주소·경로·시료 위치가 여기 밖으로 나가지 않는다 —
 * `src/physical/` 이 브로커·토픽·장비 id 를 가두는 것과 같은 규칙이고 같은 이유다
 * (`verify:detect-port`).
 *
 * ## 우리가 받아 간다
 *
 * 관제 웹은 브라우저 페이지라 남이 보내는 요청을 못 받는다. 그래서 **밀어 주지 말고 열어만
 * 달라**고 했고, 우리가 주기적으로 물어본다(`문서/탐지_명령규약_260910.md` §2).
 *
 * ## 테스트 모드 (260912 지시)
 *
 * 연결 관리의 「테스트」를 켜면 같은 자리에서 **받아 둔 실제 산출물**(`door_example/`)을
 * 읽는다. 목을 지어내는 것이 아니라 **탐지 담당이 준 진짜 값**이다 — 그래서 화면이
 * 「테스트 자료」라고 적되 값 자체는 손대지 않는다.
 *
 * 시료는 개발 서버와 빌드가 `/detect-sample/` 로 내준다(`vite.config.ts`) — 저장소에 사본을
 * 만들지 않는다.
 */

import { connectionAddress } from '../shared/connections.ts';
import type { DetectFeatures, DetectFrameEvidence, DetectPath, DetectSummary } from './types.ts';

/** 탐지 서비스 주소. **이 함수 밖에서 주소 문자열을 만들지 않는다.** */
export function detectBaseUrl(): string {
  return connectionAddress('detect', 'base');
}

/** 받아 둔 실제 산출물이 서 있는 자리. 경로는 여기 한 줄이다. */
const SAMPLE_BASE = '/detect-sample';

/** 시료의 클래스 폴더. 문이 목표이고 받침대는 자세를 역산하는 기준점이다. */
export type DetectClass = 'door' | 'pedestal';

export type DetectSource = { kind: 'live'; base: string } | { kind: 'sample' };

/** 지금 어디서 읽는가. 테스트가 켜져 있으면 시료, 아니면 실제 서비스. */
export function sourceOf(testMode: boolean): DetectSource {
  return testMode ? { kind: 'sample' } : { kind: 'live', base: detectBaseUrl() };
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return await response.json() as T;
}

/**
 * **테스트 자료도 한 각도씩 내놓는다** (260912 지시).
 *
 * 파일에는 여덟 각도가 다 들어 있다. 그걸 그대로 돌려주면 **시작하자마자 정답이 이미
 * 정해진 채로** 화면이 뜬다 — 실제 서비스는 그렇게 안 온다. 한 각도 스캔이 끝날 때마다
 * 하나씩 온다.
 *
 * 그래서 시료도 같은 박자로 내놓는다. 기준 시계는 **승인 뒤 몇 초째**(`elapsedSec`)다 —
 * 로봇이 같이 돌고 있으면 그 회전과 같은 시계를 쓰게 된다.
 */
const SAMPLE_STEP_SEC = 4;

/** 지금까지 몇 각도를 봤는가. 승인 전(0초)이면 아무것도 안 봤다. */
export function sampleRevealed(elapsedSec: number, total: number): number {
  if (!(elapsedSec > 0)) return 0;
  return Math.max(0, Math.min(total, Math.floor(elapsedSec / SAMPLE_STEP_SEC)));
}

/** 각도별 결과 — 한 각도 스캔이 끝날 때마다 늘어난다 (260912 확인). */
export async function fetchSummary(
  source: DetectSource, target: DetectClass = 'door', elapsedSec = Infinity,
): Promise<DetectSummary> {
  if (source.kind !== 'sample') return getJson<DetectSummary>(`${source.base}/detect/results?target=${target}`);
  const all = await getJson<DetectSummary>(`${SAMPLE_BASE}/${target}/target_summary.json`);
  const frames = all.frames ?? [];
  return { ...all, frames: frames.slice(0, sampleRevealed(elapsedSec, frames.length)) };
}

/** 한 각도의 근거. 못 찾은 각도에는 없다 — 없는 것이 정상이라 null 로 돌려준다. */
export async function fetchFrameEvidence(
  source: DetectSource, frame: string, target: DetectClass = 'door',
): Promise<DetectFrameEvidence | null> {
  const dir = frame.replace(/\.jpg$/, '');
  const url = source.kind === 'sample'
    ? `${SAMPLE_BASE}/${target}/${dir}/evidence.json`
    : `${source.base}/detect/evidence?target=${target}&frame=${encodeURIComponent(frame)}`;
  try {
    return await getJson<DetectFrameEvidence>(url);
  } catch {
    return null;
  }
}

/** 경로 산출. 스캔이 끝나야 나온다 — 그 전에는 없다. */
export async function fetchPath(
  source: DetectSource, target: DetectClass = 'door', complete = true,
): Promise<DetectPath | null> {
  // **스캔이 끝나야 나온다.** 시료도 그 순서를 지킨다 — 여덟을 다 보기 전에 경로가 뜨면
  // 「아직 안 돌았는데 갈 곳이 정해져 있다」가 된다.
  if (!complete) return null;
  const url = source.kind === 'sample'
    ? `${SAMPLE_BASE}/${target}/evidence.json`
    : `${source.base}/detect/path?target=${target}`;
  try {
    return await getJson<DetectPath>(url);
  } catch {
    return null;
  }
}

/** 무엇을 그 클래스라고 물었나. 근거 가시화가 쓴다. */
export async function fetchFeatures(source: DetectSource, target: DetectClass = 'door'): Promise<DetectFeatures | null> {
  const url = source.kind === 'sample'
    ? `${SAMPLE_BASE}/${target}/features_sent.json`
    : `${source.base}/detect/features?target=${target}`;
  try {
    return await getJson<DetectFeatures>(url);
  } catch {
    return null;
  }
}

/**
 * 그 각도의 그림 주소. **경로 문자열을 화면이 만들지 않는다.**
 *
 * 시료의 `evidence.json` 에는 탐지 기계의 로컬 절대경로가 들어 있다
 * (`/home/jin24/…/original.jpg`). 브라우저는 그걸 못 연다 — 그 값을 화면에 넘기면
 * 깨진 그림이 뜬다. 여기서 **우리가 열 수 있는 주소**로 바꾼다.
 */
export function frameImageUrl(
  source: DetectSource, frame: string, kind: 'original' | 'rpn_overlay' | 'target_overlay' | 'target_crop',
  target: DetectClass = 'door',
): string {
  const dir = frame.replace(/\.jpg$/, '');
  if (source.kind === 'sample') return `${SAMPLE_BASE}/${target}/${dir}/${kind}.jpg`;
  return `${source.base}/detect/frame?target=${target}&frame=${encodeURIComponent(frame)}&kind=${kind}`;
}

/** 도면 위에 경로를 그린 그림. 스캔이 끝나야 나온다. */
export function pathImageUrl(source: DetectSource, target: DetectClass = 'door'): string {
  if (source.kind === 'sample') return `${SAMPLE_BASE}/${target}/path_overlay.jpg`;
  return `${source.base}/detect/path_overlay?target=${target}`;
}

/**
 * 살아 있는가. 발표 직전에 눌러 볼 버튼용이라 가벼워야 한다.
 *
 * 테스트 모드에서는 시료를 실제로 한 번 읽어 본다 — 「켰는데 파일이 없다」를 그때 잡는다.
 */
export async function probeDetect(source: DetectSource): Promise<{ alive: boolean; reason: string }> {
  try {
    if (source.kind === 'sample') {
      const summary = await fetchSummary(source);
      return { alive: true, reason: `테스트 자료 · 각도 ${summary.frames.length}개` };
    }
    if (source.base.trim() === '') return { alive: false, reason: '주소가 비어 있습니다' };
    const response = await fetch(`${source.base}/health`);
    return response.ok
      ? { alive: true, reason: `${response.status}` }
      : { alive: false, reason: `${response.status} ${response.statusText}` };
  } catch (error) {
    return { alive: false, reason: error instanceof Error ? error.message : String(error) };
  }
}
