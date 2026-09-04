/**
 * src/views/DeviceStatusOverlay.tsx (260904 — 추가 개선 2)
 *
 * 하드웨어 카드를 **더블클릭하면 그 대상의 상태**를 연다. 새 기능이 아니라
 * `VZ-D-07`(대상 배정과 **대상 상태 조회**)의 미구현분이다 — 카드가 드래그로 배정만 되고
 * 눌러도 아무 일이 없었다.
 *
 * ## 규칙은 `VZ-N-05`(확대) 그대로다
 *
 * | 조건 | 여기서 |
 * |---|---|
 * | 오버레이다 | `ZoomOverlay`·`ActionModal` 과 같은 `.modal-backdrop` 위에 얹는다 |
 * | 뒤를 교체하지 않는다 | 마일스톤 목록·하드웨어 목록은 언마운트되지 않는다. 형제로 얹힐 뿐이다 |
 * | 동시 하나 | 상태가 **문자열 하나**(`statusDeviceId`)다. 배열이면 둘이 열린다 |
 * | 닫는 길이 둘 이상 | 닫기 버튼 · Esc · 배경 누르기 |
 *
 * ## 지어내지 않는다
 *
 * 대본(registry 세계) 장비의 실측값은 **남이 줄 데이터**다(8/31 결정). 그래서 더블클릭하면
 * 뜨는 것은 값이 아니라 **「무엇을 · 누구에게서 기다리는가」 카드**다. 그것이 이 화면의 요지다.
 * 옛 편(`MSN-260826-01`)처럼 시나리오에 `hardware` 목록이 실려 있으면 일곱 칸을 그릴 수는
 * 있지만, 그것도 `PendingSource` 안에 있으므로 기본 모드에서는 자리표시가 이긴다.
 *
 * **카메라 연결 상태는 계약에 아예 없다** — `Hardware` 타입에 필드가 없고
 * (배터리·RSSI·지연·IP·펌웨어·관절 온도·하트비트는 있다) 상대 파트도 미확인이다
 * (요구사항정의서 §7.10 「열림」). 자리만 만들고 **「상대 없음 — 회의 안건」**으로 둔다.
 * 필드를 임의로 늘리지 않는다 — 하드웨어 파트와 맞춘 뒤에 넣는다.
 */

import { useEffect } from 'react';
import type { Hardware } from '../model/types.ts';
import { PendingSource } from '../shared/PendingSource.tsx';
import { DeviceStrip } from './DeviceStrip.tsx';

export function DeviceStatusOverlay({ deviceId, device, source, onClose }: {
  deviceId: string;
  /** 시나리오에 실측 목록이 실려 있을 때만 있다. 대본 세계에서는 없다. */
  device?: Hardware;
  /** 이 목록이 어디서 왔는가. 화면이 목임을 감추지 않는다. */
  source: string;
  onClose(): void;
}) {
  // 여는 길이 둘(더블클릭·앞으로 늘 수 있는 다른 경로)이면 닫는 길도 둘 이상이어야 한다.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="modal device-modal" role="dialog" aria-label={`${deviceId} 대상 상태`}>
      <header>
        <div>
          <h2>{deviceId} · 대상 상태</h2>
          <small>{device ? `${device.kind} · ` : ''}원천 {source} · VZ-D-07 대상 상태 조회</small>
        </div>
        <button onClick={onClose}>닫기 (Esc)</button>
      </header>
      {/* 일곱 칸 — `ActionModal` 과 **같은 부품**이다. 기본 모드에서는 자리표시가 대신 뜬다. */}
      <PendingSource id="robot-status-strip" minHeight={104}>
        {device ? <DeviceStrip device={device} /> : undefined}
      </PendingSource>
      {/* 여덟째 칸이 될 수 없는 것 — 계약에 필드가 없다. 값을 지어내는 대신 자리를 비워 둔다. */}
      <div className="device-modal__camera">
        <PendingSource id="device-camera-link" minHeight={96} />
      </div>
      <footer>
        <span>이 창은 뒤의 목록을 교체하지 않습니다 — 닫으면 같은 자리입니다.</span>
      </footer>
    </section>
  </div>;
}
