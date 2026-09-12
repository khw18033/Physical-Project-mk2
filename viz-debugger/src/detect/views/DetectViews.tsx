/**
 * src/detect/views/DetectViews.tsx (260912 신설)
 *
 * **탐지가 채우는 세 자리** — 영상 · 근거 · 2D 맵.
 *
 * 셋 다 지금까지 자리표시(`video-stream` · `detections` · `zone-map`)로 비어 있던 곳이다.
 * 값을 줄 데가 없어서 비워 둔 것이었고, 이제 생겼다.
 *
 * ## 자리표시로 감싸지 않는다
 *
 * 다른 뷰 노드는 `PendingSource` 로 감싼다 — 남이 줄 데이터라 일반 모드에서는 「누가 줄
 * 값인지」를 그려야 하기 때문이다. **이 셋의 값은 실제로 온다.** 아직 안 왔으면 감추는
 * 것이 아니라 **안 왔다고 적는다.** 로봇 노드와 같은 규칙이다.
 *
 * ## 점수를 퍼센트로 안 쓴다
 *
 * `final_score` 는 특징 여덟 중 최고값이지 확률이 아니다. 0.27 을 「27%」로 적으면 보는
 * 사람은 「거의 못 찾았다」로 읽는데, 실제로는 관문 넷을 다 통과한 판정이다.
 * 이름을 `특징 최고값` 으로 적는 것만으로 그 오독이 사라진다 (`parse.ts` 의 `SCORE_LABEL`).
 */

import { frameImageUrl, mapImageUrl, pathImageUrl, sourceOf } from '../DetectClient.ts';
import { chosenFrame, gateWords, indexOfRotation, SCORE_LABEL, usableDistanceCm } from '../parse.ts';
import { sweepDone } from '../detectBridge.ts';
import { useDetect } from '../store.ts';
import type { DetectFrame } from '../types.ts';

/** 아직 아무것도 안 왔을 때. **감추지 않고 적는다.** */
function Waiting({ what }: { what: string }) {
  return <p className="detect-wait">
    {what}
    <small>연결 관리에서 주소를 넣거나 「테스트」를 켜면 들어옵니다</small>
  </p>;
}

/** 지금 고른 각도. 없으면 마지막으로 본 각도 — 도는 동안 화면이 따라가야 한다. */
function focusFrame(frames: readonly DetectFrame[], score: (f: DetectFrame) => number): DetectFrame | null {
  return chosenFrame(frames, score) ?? frames.at(-1) ?? null;
}

// ── 영상 ─────────────────────────────────────────────────────────────────────

/**
 * **탐지가 본 그림.** 고른 각도의 상자 입힌 프레임이다.
 *
 * 스캔이 도는 동안에는 **마지막으로 본 각도**를 보여 준다 — 그래야 「지금 어디를 보고
 * 있나」가 화면에 남는다. 다 돌고 나면 고른 각도에 머문다.
 */
export function DetectCam({ zoom = false }: { zoom?: boolean }) {
  const state = useDetect();
  const source = sourceOf(state.testMode);
  const score = (f: DetectFrame) => state.evidence[f.frame]?.final_score ?? 0;
  const frame = focusFrame(state.frames, score);
  if (frame === null) return <Waiting what="탐지 영상이 아직 없습니다" />;

  // 찾은 각도는 상자 입힌 것을, 못 찾은 각도는 원본을 — 없는 상자를 그린 척하지 않는다.
  const kind = frame.found ? 'target_overlay' : 'original';
  return <div className={`detect-cam${zoom ? ' detect-cam--zoom' : ''}`}>
    <img src={frameImageUrl(source, frame.frame, kind)} alt={`${frame.rotation_deg}도 프레임`} />
    <span className="detect-cam__at">
      {frame.rotation_deg}도 · {frame.found ? '문 있음' : '문 없음'}
      {state.testMode && <em className="detect-temp">테스트 자료</em>}
    </span>
    {zoom && <div className="detect-strip">
      {state.frames.map((item) => <figure key={item.frame} className={item.found ? 'is-found' : ''}>
        <img src={frameImageUrl(source, item.frame, item.found ? 'target_overlay' : 'original')} alt={`${item.rotation_deg}도`} />
        <figcaption>{item.rotation_deg}도</figcaption>
      </figure>)}
    </div>}
  </div>;
}

// ── 근거 ─────────────────────────────────────────────────────────────────────

/**
 * **왜 문이라고 했나.** 관문 넷과 특징 여덟 점수, 그리고 잘라낸 그림.
 *
 * 찾았다는 판정은 **점수가 아니라 관문이 정한다.** 그래서 관문을 먼저, 점수를 뒤에 적는다.
 */
export function DetectReason({ zoom = false, count = 8 }: { zoom?: boolean; count?: number }) {
  const state = useDetect();
  const source = sourceOf(state.testMode);
  const score = (f: DetectFrame) => state.evidence[f.frame]?.final_score ?? 0;
  /**
   * **근거는 판정 뒤에 나온다** (260912 지시). 도는 동안에는 아직 고른 것이 없다 —
   * 세 각도만 보고 근거를 띄우면 다섯째에서 답이 바뀌었을 때 근거도 같이 바뀐다.
   */
  if (!sweepDone(count)) {
    return state.frames.length === 0
      ? <Waiting what="판단 근거가 아직 없습니다" />
      : <p className="detect-wait">탐색 중입니다 — {state.frames.length}/{count} 각도
        <small>여덟을 다 본 뒤에 판정과 근거가 나옵니다</small></p>;
  }
  const frame = chosenFrame(state.frames, score);
  if (frame === null) {
    return <p className="detect-wait">여덟 각도에서 문을 못 찾았습니다<small>임의로 한 방향을 고르지 않습니다</small></p>;
  }
  const evidence = state.evidence[frame.frame] ?? null;
  const gates = Object.entries(evidence?.mandatory_gates ?? {});

  return <div className="detect-reason">
    <div className="detect-reason__head">
      <b>{frame.rotation_deg}도</b>
      {evidence !== null && <span className="detect-score">{SCORE_LABEL} {evidence.final_score.toFixed(3)}</span>}
      {state.testMode && <em className="detect-temp">테스트 자료</em>}
    </div>
    <ul className="detect-gates">
      {gates.map(([name, gate]) => <li key={name} className={gate.passed ? 'is-pass' : 'is-fail'}>
        {gate.passed ? '✓' : '✕'} {gateWords(name, gate)}
      </li>)}
      {gates.length === 0 && <li>관문 근거 미수신</li>}
    </ul>
    {zoom && <>
      {evidence !== null && <img className="detect-crop"
        src={frameImageUrl(source, frame.frame, 'target_crop')} alt="잘라낸 목표" />}
      {/* 특징 여덟 — 무엇을 문이라고 물었고 각각 얼마나 닮았나. */}
      {evidence !== null && <table className="detect-features">
        <tbody>
          {Object.entries(evidence.feature_similarities)
            .sort((a, b) => b[1] - a[1])
            .map(([feature, value]) => <tr key={feature}>
              <th>{feature}</th><td>{value.toFixed(4)}</td>
            </tr>)}
        </tbody>
      </table>}
      {/* 도면 기준 **실제 방위**는 여기에만 적는다 — 화면이 가리키는 각도는 스캔 시작 기준이다. */}
      {frame.absolute_bearing_deg !== undefined && <p className="detect-note">
        도면 기준 방위 {frame.absolute_bearing_deg}도 · 화면의 {frame.rotation_deg}도는 스캔 시작 기준입니다
      </p>}
      {usableDistanceCm(frame) === null && frame.distance_cm !== undefined && <p className="detect-note">
        깊이 추정은 보정범위 밖이라 거리로 쓰지 않습니다 — 거리는 도면 좌표로 냅니다
      </p>}
      {state.features !== null && <p className="detect-note">
        물어본 특징 {state.features.features_compared.length}개
        {state.features.is_localization_landmark && ' · 자세 역산 기준점'}
      </p>}
    </>}
  </div>;
}

// ── 2D 맵 ────────────────────────────────────────────────────────────────────

/**
 * **도면, 그리고 그 위의 경로.** 그림 한 장이 두 얼굴을 갖는다.
 *
 *   경로 산출 전   아무것도 안 그린 도면 — 임무 내내 있는 것이라 비워 두지 않는다
 *   경로 산출 후   탐지가 그려 준 경로 (`T-B1` 이 완료로 뜨는 바로 그때다)
 *
 * 바뀌는 시점이 `T-B1` 의 완료와 **같은 값에 걸려 있다**(`state.path !== null`). 두 군데서
 * 따로 판단하면 노드는 초록인데 그림은 그대로인 날이 온다.
 *
 * `path_calculation` 은 식과 대입값이 문자열로 들어 있다 — **우리가 다시 계산하지 않는다.**
 * 그대로 늘어놓는 것이 「왜 90도를 돌았나」에 대한 답이 된다.
 */
export function DetectMap({ zoom = false }: { zoom?: boolean }) {
  const state = useDetect();
  const source = sourceOf(state.testMode);
  const path = state.path;

  // **경로가 없어도 도면은 있다.** 전에는 이 자리가 통째로 비어서, 발표 초반 내내
  // 2D 맵 뷰 노드가 빈 상자였다.
  if (path === null) {
    return <div className="detect-map detect-map--plain">
      <img src={mapImageUrl(source)} alt="2D 도면" />
      <div className="detect-map__facts">
        <span>경로는 스캔이 끝난 뒤에 그려집니다</span>
        {state.testMode && <em className="detect-temp">테스트 자료</em>}
      </div>
    </div>;
  }
  const steps = Object.entries(path.path_calculation ?? {});

  return <div className="detect-map">
    <img src={pathImageUrl(source)} alt="도면 위의 경로" />
    <div className="detect-map__facts">
      <span><b>{path.turn_instruction}</b></span>
      <span>직진 {(path.forward_distance_cm / 100).toFixed(2)}m</span>
      <span>정지거리 {(path.standoff_cm / 100).toFixed(2)}m</span>
      {state.testMode && <em className="detect-temp">테스트 자료</em>}
    </div>
    {zoom && <>
      <dl className="detect-map__rows">
        <div><dt>로봇 위치</dt><dd>{path.robot_position_cm.map((n) => n.toFixed(1)).join(', ')} cm</dd></div>
        <div><dt>로봇 방위</dt><dd>{path.current_heading_map_deg}도 (도면 기준)</dd></div>
        <div><dt>목표 위치</dt><dd>{path.target_position_cm.map((n) => n.toFixed(1)).join(', ')} cm · {path.target_resolution.source}</dd></div>
        <div><dt>목표까지</dt><dd>{(path.distance_to_target_cm / 100).toFixed(2)} m</dd></div>
        <div><dt>도착점</dt><dd>{path.goal_cm.map((n) => n.toFixed(1)).join(', ')} cm</dd></div>
      </dl>
      {/* **식과 대입값을 그대로.** 우리가 다시 계산하지 않는다 — 계산이 두 곳에 있으면
          하나만 고쳐지는 날이 온다. */}
      <ol className="detect-steps">
        {steps.map(([name, step]) => <li key={name}>
          <code>{step.formula}</code>
          <small>{step.substituted}</small>
        </li>)}
      </ol>
    </>}
  </div>;
}

/** 지금 탐지가 고른 칸 번호. 태스크 노드가 「몇 번째 방향」을 적을 때 쓴다. */
export function useChosenIndex(stepDeg: number, count: number): number | null {
  const state = useDetect();
  const best = chosenFrame(state.frames, (f) => state.evidence[f.frame]?.final_score ?? 0);
  return best === null ? null : indexOfRotation(best.rotation_deg, stepDeg, count);
}
