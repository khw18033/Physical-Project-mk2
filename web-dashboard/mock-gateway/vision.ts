/**
 * mock-gateway/vision.ts
 *
 * 합성 영상 + 지연된 탐지 결과 (VZ-I-06 · VZ-I-07 · VZ-I-09).
 *
 * **왜 합성 영상인가** — 실제 스트림 변환 지점(RTSP→WebRTC/HLS)이 아직 안 정해졌다.
 * 그걸 기다리면 "프레임 참조가 없으면 박스가 어긋난다"를 끝내 실측하지 못한다.
 * 그래서 프레임 번호가 찍힌 도형 몇 개를 15fps로 내려보내고, 브라우저가 canvas에 그린다.
 * 영상 픽셀을 보내는 것이 아니라 **그릴 재료(도형 위치)와 프레임 번호**를 보낸다 —
 * 이 검증에 필요한 것은 화질이 아니라 "몇 번째 프레임인가"이기 때문이다.
 *
 * **왜 탐지를 늦게 보내는가** — 온디바이스 추론이 0.2초 걸리고 영상이 15fps면,
 * 결과가 돌아왔을 때 화면은 이미 약 3프레임 앞서 있다. 그 어긋남을 재현해야
 * 프레임 참조값이 왜 필요한지가 숫자로 나온다.
 */

import { INTERVALS, VISION } from './config.ts';
import type { Hub } from './hub.ts';

/** 화면에 움직이는 대상 하나. 좌표는 **추론 해상도 기준 픽셀**이다. */
export type VisionObject = {
  track_id: string;
  label: string;
  /** 분류 신뢰도. 낮은 것은 화면에서 시각적으로 구분되어야 한다 (VZ-I-09). */
  confidence: number;
  shape: 'person' | 'robot';
  /** 중심 좌표(추론 해상도 기준). */
  cx: number;
  cy: number;
  w: number;
  h: number;
};

export type VideoFrame = {
  /** 프레임 번호. 탐지 결과가 이 값을 그대로 돌려준다. */
  frame_seq: number;
  /** 서버가 이 프레임을 만든 시각. */
  captured_at: string;
  fps: number;
  /** 표시 해상도 — 브라우저 canvas 크기. */
  display: { width: number; height: number };
  /**
   * 이 프레임의 도형 좌표가 어느 해상도 기준인가.
   * 탐지의 bbox_space.reference와 **같은 값을 공유해야** 둘을 같은 화면에 겹칠 수 있다.
   * 프레임과 탐지가 좌표 선언을 따로 가지면 정합 자체가 성립하지 않는다.
   */
  reference: { width: number; height: number };
  /** 이 프레임의 도형들. 브라우저는 이걸 그린다. */
  objects: VisionObject[];
};

/**
 * bbox 좌표계 선언 (VZ-I-07).
 * 이게 없으면 추론 해상도와 표시 해상도가 다를 때 환산 기준이 없다.
 */
export type BboxSpace = {
  /** normalized(0~1) 인가 absolute(픽셀) 인가. */
  format: 'normalized' | 'absolute';
  /** 원점. */
  origin: 'top-left';
  /** absolute일 때의 기준 해상도. normalized일 때도 참고용으로 함께 보낸다. */
  reference: { width: number; height: number };
};

export type Detection = {
  track_id: string;
  label: string;
  confidence: number;
  /** [x, y, w, h] — bbox_space가 정하는 좌표계. */
  bbox: [number, number, number, number];
  /** 이 대상의 최근 궤적 (VZ-I-09). bbox와 같은 좌표계. */
  trail: Array<[number, number]>;
};

export type DetectionResult = {
  /**
   * **되돌아온 프레임 참조값.** 이 값이 가리키는 프레임에 박스를 맞춰야 한다.
   * ※ 미결: AI와 하드웨어의 프레임 참조 형식이 다르다. 통일되지 않으면 이 기능 자체가
   *   성립하지 않는다 — 여기서는 정수 frame_seq로 가정한다.
   */
  frame_ref: number;
  /** 결과를 만들어 내보낸 시각. frame_ref 프레임보다 inference_delay_ms 늦다. */
  emitted_at: string;
  inference_delay_ms: number;
  bbox_space: BboxSpace;
  detections: Detection[];
};

const TAU = Math.PI * 2;

export class VisionEmitter {
  private readonly hub: Hub;
  readonly entity: string;

  private frameSeq = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  /** 열린 패널이 없으면 발행하지 않는다 (VZ-I-06 — 열린 패널만 받는다). */
  private openCount = 0;

  /** 궤적 보관 — 대상별 최근 좌표. */
  private readonly trails = new Map<string, Array<[number, number]>>();

  /** 설정값. 시나리오로 바꿔가며 확인한다. */
  // 타입을 넓혀 둔다 — VISION이 as const라 그대로 두면 리터럴 타입이 되어 못 바꾼다.
  inferenceDelayMs: number = VISION.INFERENCE_DELAY_MS;
  inferenceWidth: number = VISION.INFERENCE_WIDTH;
  inferenceHeight: number = VISION.INFERENCE_HEIGHT;
  bboxFormat: BboxSpace['format'] = VISION.BBOX_FORMAT;

  constructor(hub: Hub, entity: string) {
    this.hub = hub;
    this.entity = entity;
  }

  get isOpen(): boolean {
    return this.openCount > 0;
  }

  /** 패널 열기/닫기. 열린 패널만 프레임을 받는다 — 무선 대역과 디코딩을 동시에 아낀다. */
  setOpen(open: boolean): void {
    this.openCount = Math.max(0, this.openCount + (open ? 1 : -1));
    if (this.openCount > 0 && this.timer === null) this.start();
    if (this.openCount === 0 && this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  private start(): void {
    const tick = () => {
      this.emitFrame();
      this.timer = setTimeout(tick, INTERVALS.CAMERA_META_MS);
    };
    this.timer = setTimeout(tick, INTERVALS.CAMERA_META_MS);
  }

  /** 대상 위치는 프레임 번호의 함수다 — 그래야 "몇 번 프레임의 위치"가 결정적으로 정해진다. */
  private objectsAt(seq: number): VisionObject[] {
    const t = seq / VISION.FPS;
    const W = this.inferenceWidth;
    const H = this.inferenceHeight;

    return [
      {
        track_id: 'trk-01',
        label: 'person',
        // 높은 신뢰도.
        confidence: 0.94,
        shape: 'person',
        // 좌우로 왕복. 속도를 충분히 줘야 3프레임 어긋남이 눈에 보인다.
        cx: W * 0.5 + Math.sin(t * VISION.PERSON_SPEED_RAD) * W * 0.3,
        cy: H * 0.55,
        w: W * 0.12,
        h: H * 0.5,
      },
      {
        track_id: 'trk-02',
        label: 'robot',
        // 낮은 신뢰도 — 화면에서 구분되어야 한다.
        confidence: 0.41,
        shape: 'robot',
        cx: W * 0.5 + Math.cos(t * VISION.ROBOT_SPEED_RAD + TAU * 0.25) * W * 0.28,
        cy: H * 0.68,
        w: W * 0.18,
        h: H * 0.22,
      },
    ];
  }

  private emitFrame(): void {
    this.frameSeq += 1;
    const seq = this.frameSeq;
    const objects = this.objectsAt(seq);

    const frame: VideoFrame = {
      frame_seq: seq,
      captured_at: new Date().toISOString(),
      fps: VISION.FPS,
      display: { width: VISION.DISPLAY_WIDTH, height: VISION.DISPLAY_HEIGHT },
      reference: { width: this.inferenceWidth, height: this.inferenceHeight },
      objects,
    };
    this.hub.publish(this.entity, 'video_frame', frame, { fromDevice: true });

    // 궤적 갱신.
    for (const o of objects) {
      const trail = this.trails.get(o.track_id) ?? [];
      trail.push([o.cx, o.cy]);
      if (trail.length > VISION.TRAIL_LENGTH) trail.shift();
      this.trails.set(o.track_id, trail);
    }

    // **추론 지연** — 이 프레임을 보고 만든 결과를 늦게 내보낸다.
    // 결과에는 frame_ref = seq 가 실려 있으므로, 화면이 원하면 맞춰 그릴 수 있다.
    const delay = this.inferenceDelayMs;
    const objectsSnapshot = objects;
    const trailsSnapshot = new Map(
      objects.map((o) => [o.track_id, [...(this.trails.get(o.track_id) ?? [])]] as const),
    );

    setTimeout(() => {
      if (!this.isOpen) return;
      const normalized = this.bboxFormat === 'normalized';
      const sx = normalized ? 1 / this.inferenceWidth : 1;
      const sy = normalized ? 1 / this.inferenceHeight : 1;

      const result: DetectionResult = {
        frame_ref: seq,
        emitted_at: new Date().toISOString(),
        inference_delay_ms: delay,
        bbox_space: {
          format: this.bboxFormat,
          origin: 'top-left',
          reference: { width: this.inferenceWidth, height: this.inferenceHeight },
        },
        detections: objectsSnapshot.map((o) => ({
          track_id: o.track_id,
          label: o.label,
          confidence: o.confidence,
          bbox: [(o.cx - o.w / 2) * sx, (o.cy - o.h / 2) * sy, o.w * sx, o.h * sy],
          trail: (trailsSnapshot.get(o.track_id) ?? []).map(([x, y]) => [x * sx, y * sy] as [number, number]),
        })),
      };
      this.hub.publish(this.entity, 'detections', result, { fromDevice: false });
    }, delay);
  }

  stop(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  describe(): string {
    return (
      '추론 지연 ' + this.inferenceDelayMs + 'ms · 추론 해상도 ' +
      this.inferenceWidth + 'x' + this.inferenceHeight + ' · 표시 ' +
      VISION.DISPLAY_WIDTH + 'x' + VISION.DISPLAY_HEIGHT + ' · bbox ' + this.bboxFormat
    );
  }
}
