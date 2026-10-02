/**
 * src/physical/cameraView.ts (260928 신설 — 카메라 노드 · Go1 카메라 직접 보기)
 *
 * **로봇 노드(pi7)의 Go1 카메라 뷰어에서 바로 받는 주소.**
 *
 * 카메라 노드는 백엔드 `/media` 로 영상을 받는다. 그런데 실물 Go1 영상이 그 길로 오려면 누군가 `stream_start` 를
 * 보내고 → 엣지가 받아 → 서버에 올려야 하는데, 그 배선이 백엔드의 Phase 6 이라 **실물 영상이 그 길로 온 적이 없다**
 * (260928 pi7 실측 — 명령·상태는 되는데 카메라만 안 왔다).
 *
 * 그 사이 영상은 pi7 에 이미 있다 — HW 의 `go1-camview`(`bench/go1_cam_view.py`, 8090)가 Go1 안 카메라 5대를
 * 중계하고, `/stream/<번호>` 가 `<img>` 로 바로 받는 MJPEG 다(실측 약 30 fps). 그래서 **장비가 붙어 있는 브로커의
 * 호스트**에서 그 주소를 만든다. 주소를 아는 면은 이 폴더 하나라(`verify:physical-port`) 여기서 만든다.
 *
 * 이 뷰어는 HW 가 「운영 구성요소가 아니다 — 말단에서 영상이 나오는가를 사람이 보는 도구」라고 적은 것이다.
 * `/media` 경로가 열리면 그쪽이 본선이고, 이것은 그때까지의 길이다. 화면은 어느 길로 보는지 적는다.
 */

import { clientForDevice } from './robotClient.ts';
import { deviceIdentityFor } from './deviceIdentity.ts';

/** HW `go1-camview.service` 의 포트. 바뀌면 여기 한 곳만 고친다. */
export const GO1_CAMVIEW_PORT = 8090;

/**
 * pi3 **영상 말단**(`drone_rpi` · `drone-agent.service`)의 포트 (260928). 엣지가 당겨 가는 창구이고, 한 번에
 * 메타 + JPEG 한 장을 multipart 로 준다. 브라우저가 그 형식도 CORS 도 못 넘으므로 개발 서버 중계
 * (`scripts/drone-cam-relay.mjs`)를 거친다.
 */
export const DRONE_AGENT_PORT = 8890;

/**
 * 받는 방식. Go1 뷰어는 끝나지 않는 MJPEG(`stream`)이고, 드론 말단은 한 번에 한 장(`frames`)이라 화면이 이어서 당긴다.
 * 모양은 `media/views/DeviceCamera.tsx` 의 `DirectSource` 와 같다 — 그쪽이 이 파일을 import 하지 않게 모양으로만 맞춘다.
 */
export type DirectCameraSource = { url: string; kind: 'stream' | 'frames' };

/** 카메라 위치 → 뷰어의 카메라 번호 (`robot/go1_camera.py` 의 `CAMS`). */
const GO1_CAMERA_INDEX: Readonly<Record<string, number>> = { front: 1, chin: 2, left: 3, right: 4, belly: 5 };

/**
 * 그 장비의 그 카메라를 직접 보는 주소. **못 만들면 null** — 그러면 카메라 노드는 `/media` 로 간다.
 *
 * 어느 길인지는 장비가 밝힌 것으로 가른다 — Go1(`go1_robot`)은 pi7 의 Go1 뷰어, 드론(`drone`)은 pi3 의 영상 말단.
 * 둘 다 아니면 null 이고, 그 장비는 `/media` 로 간다. 주소를 지어 붙이면 「영상이 안 온다」의 원인을 엉뚱한 데서 찾게 된다.
 */
export function directCameraUrl(deviceId: string, position: string): DirectCameraSource | null {
  const client = clientForDevice(deviceId);
  if (client === null) return null;
  const identity = deviceIdentityFor(client.address());
  let host: string;
  try {
    host = new URL(client.address()).hostname;
  } catch {
    return null;
  }
  if (host === '') return null;
  if (identity?.deviceType === 'go1_robot') {
    const index = GO1_CAMERA_INDEX[position];
    return index === undefined ? null : { url: `http://${host}:${GO1_CAMVIEW_PORT}/stream/${index}`, kind: 'stream' };
  }
  /**
   * **드론은 기체에 실린 pi3 의 카메라 모듈이다** (260928 지시 — 「pi3 의 카메라 말단 노드를 활용」). 카메라가 한 대라
   * 위치 칸은 뜻이 없다 — 어느 위치를 골라도 0번 한 대다. 말단은 브로커와 같은 호스트에 있다.
   */
  if (identity?.kind === 'drone') {
    const base = encodeURIComponent(`http://${host}:${DRONE_AGENT_PORT}`);
    return { url: `/drone-cam/frame?base=${base}&cam=0`, kind: 'frames' };
  }
  return null;
}
