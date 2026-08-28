/**
 * src/views/UtterancePanel.tsx
 *
 * 발화 패널 (VZ-L-01 / REQ-1301~1305 / REQ-305).
 *
 * 1단계에서 이 패널은 전부 껍데기였다 — 파형은 고정 문자열, 인용문은 시나리오 JSON의
 * 목 문장, 진행 막대는 다섯 칸 전부 체크 하드코딩. 이제 **앞 셋은 실제**다.
 *
 * **뒤 세 칸(의도 분석·마일스톤 분리·태스크 생성)은 여전히 목이다.** VZ-G-01·VZ-G-02
 * 이고 로컬 LLM이 필요하다. 감추지 않고 `목` 배지를 붙인 채 남긴다 — 다섯 칸을 한 번에
 * 채우면 "인식이 나쁜 건지 해석이 나쁜 건지"를 가를 수 없다.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { issueCommand } from '../shared/commandEgress.ts';
import { CommandAuditError } from '../shared/voiceAudit.ts';
import { capabilities, type SttStatus } from '../stt/availability.ts';
import { decide, PROVISIONAL_NOTE, VERDICT_LABEL, type ConfidenceDecision } from '../stt/confidence.ts';
import { probe, STT_BASE_URL, transcribe } from '../stt/SttClient.ts';
import { SttUnavailableError, type SttResult } from '../stt/types.ts';

const LEVEL_BARS = 22;
/** 레벨 갱신 주기. 60fps로 setState 하면 이 작은 패널이 렌더 예산을 먹는다. */
const LEVEL_INTERVAL_MS = 60;
const PREFERRED_MIME = 'audio/webm;codecs=opus';

type StepState = 'idle' | 'active' | 'done' | 'failed';
type Phase = 'idle' | 'recording' | 'transcribing' | 'reviewing' | 'failed';

function mediaRecorderSupported(): boolean {
  return typeof window !== 'undefined' && typeof window.MediaRecorder !== 'undefined';
}

function pickMimeType(): string | undefined {
  if (!mediaRecorderSupported()) return undefined;
  return MediaRecorder.isTypeSupported(PREFERRED_MIME) ? PREFERRED_MIME : undefined;
}

/** 앞 두 칸만 실제 상태를 따라간다. 뒤 세 칸은 목이다. */
function realSteps(phase: Phase, hasAudio: boolean, hasResult: boolean): Array<{ label: string; state: StepState }> {
  const capture: StepState = phase === 'recording' ? 'active' : phase === 'failed' && !hasAudio ? 'failed' : hasAudio ? 'done' : 'idle';
  const stt: StepState = phase === 'transcribing' ? 'active' : phase === 'failed' && hasAudio && !hasResult ? 'failed' : hasResult ? 'done' : 'idle';
  return [
    { label: '음성 수신', state: capture },
    { label: 'STT 변환', state: stt },
  ];
}

const STEP_MARK: Record<StepState, string> = { idle: '·', active: '…', done: '✓', failed: '✕' };
const MOCK_STEPS = ['의도 분석', '마일스톤 분리', '태스크 생성'];

function LevelMeter({ levels, live }: { levels: number[]; live: boolean }) {
  return (
    <div className={live ? 'waveform live' : 'waveform'} aria-label="입력 레벨">
      {levels.map((level, index) => (
        <i key={index} style={{ height: `${Math.max(3, Math.round(level * 100))}%` }} />
      ))}
    </div>
  );
}

function Numbers({ result, decision }: { result: SttResult; decision: ConfidenceDecision }) {
  const show = (value: number | null, digits = 3) => (value === null ? '—' : value.toFixed(digits));
  return (
    <details className="stt-numbers">
      <summary>원본 수치 세 개 · 판정 근거</summary>
      <dl>
        <dt>avg_logprob</dt>
        <dd>{show(result.avg_logprob)} <small>세그먼트 중 최소</small></dd>
        <dt>no_speech_prob</dt>
        <dd>{show(result.no_speech_prob, 4)} <small>세그먼트 중 최대</small></dd>
        <dt>평균 단어 확률</dt>
        <dd>{show(result.mean_word_prob)} <small>단어 {result.word_count}개 · 최소 {show(result.min_word_prob)}</small></dd>
      </dl>
      <p className="hint">셋을 하나의 점수로 합치지 않습니다. 합치면 임계값을 실측할 근거가 사라집니다.</p>
      <ul>
        {decision.reasons.map((reason) => <li key={reason}>{reason}</li>)}
      </ul>
      <p className="hint">
        {result.device}/{result.compute_type} · 추론 {result.elapsed_sec.toFixed(2)}s · 로드 {result.load_sec.toFixed(2)}s · RTF {result.rtf.toFixed(2)}
      </p>
    </details>
  );
}

export function UtterancePanel({ fallbackText }: { fallbackText: string }) {
  const [status, setStatus] = useState<SttStatus>('probing');
  const [phase, setPhase] = useState<Phase>('idle');
  const [levels, setLevels] = useState<number[]>(() => new Array(LEVEL_BARS).fill(0));
  const [result, setResult] = useState<SttResult | null>(null);
  const [decision, setDecision] = useState<ConfidenceDecision | null>(null);
  const [edited, setEdited] = useState('');
  const [manual, setManual] = useState('');
  const [useHotwords, setUseHotwords] = useState(true);
  const [error, setError] = useState<{ message: string; detail?: string } | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [issued, setIssued] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const frameRef = useRef<number | null>(null);

  const able = capabilities(status, mediaRecorderSupported());

  useEffect(() => {
    const controller = new AbortController();
    void probe(controller.signal).then((alive) => setStatus(alive ? 'ready' : 'unavailable'));
    return () => controller.abort();
  }, []);

  const stopMeter = useCallback(() => {
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    frameRef.current = null;
    void audioContextRef.current?.close();
    audioContextRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => stopMeter, [stopMeter]);

  /** 진짜 입력 레벨. AnalyserNode 하나면 되고 오디오 라이브러리를 넣지 않는다. */
  const startMeter = useCallback((stream: MediaStream) => {
    const context = new AudioContext();
    audioContextRef.current = context;
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    context.createMediaStreamSource(stream).connect(analyser);
    const buffer = new Float32Array(analyser.fftSize);
    let last = 0;
    const tick = (now: number) => {
      frameRef.current = requestAnimationFrame(tick);
      if (now - last < LEVEL_INTERVAL_MS) return;
      last = now;
      analyser.getFloatTimeDomainData(buffer);
      let sum = 0;
      for (const sample of buffer) sum += sample * sample;
      const rms = Math.sqrt(sum / buffer.length);
      // 목소리 대부분이 0.02~0.3 RMS 구간에 들어와서, 선형으로 그리면 막대가 거의 안 움직인다.
      const level = Math.min(1, Math.sqrt(rms) * 2.2);
      setLevels((current) => [...current.slice(1), level]);
    };
    frameRef.current = requestAnimationFrame(tick);
  }, []);

  const send = useCallback(async (blob: Blob) => {
    setPhase('transcribing');
    setError(null);
    try {
      const next = await transcribe(blob, { useHotwords });
      setResult(next);
      setDecision(decide(next));
      setEdited(next.text);
      setConfirmed(false);
      setIssued(null);
      setPhase('reviewing');
    } catch (caught) {
      const unavailable = caught instanceof SttUnavailableError;
      setError({ message: unavailable ? caught.message : String(caught), detail: unavailable ? caught.detail : undefined });
      // 서비스가 죽은 것이면 기능만 끄고 수동 입력을 남긴다. 화면은 계속 뜬다.
      if (unavailable && caught.kind === 'offline') setStatus('unavailable');
      setPhase('failed');
    }
  }, [useHotwords]);

  const startRecording = useCallback(async () => {
    setError(null);
    setResult(null);
    setDecision(null);
    setIssued(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mime = pickMimeType();
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      const chunks: BlobPart[] = [];
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = () => {
        stopMeter();
        void send(new Blob(chunks, { type: mime ?? 'audio/webm' }));
      };
      recorderRef.current = recorder;
      recorder.start();
      startMeter(stream);
      setPhase('recording');
    } catch (caught) {
      stopMeter();
      setError({ message: `마이크를 열 수 없습니다: ${String(caught)}` });
      setPhase('failed');
    }
  }, [send, startMeter, stopMeter]);

  const stopRecording = useCallback(() => {
    recorderRef.current?.stop();
    recorderRef.current = null;
  }, []);

  const submitVoice = useCallback(async () => {
    if (!result || !decision) return;
    try {
      // 임계 미만이면 여기 오지 못한다. 조용히 통과시키지 않는다.
      await issueCommand({
        action: 'mission_from_utterance',
        params: { text: edited.trim(), verdict: decision.verdict, threshold_status: PROVISIONAL_NOTE },
        inputModality: 'voice',
        voice: {
          transcript: result.text,
          transcript_edited: edited.trim(),
          avg_logprob: result.avg_logprob,
          no_speech_prob: result.no_speech_prob,
          mean_word_prob: result.mean_word_prob,
          engine: result.engine,
          model: result.model,
          audio_ref: result.audio_ref,
        },
      });
      setIssued(`음성 발화로 발행했습니다 · audio_ref=${result.audio_ref}`);
    } catch (caught) {
      setError({ message: caught instanceof CommandAuditError ? caught.message : String(caught) });
    }
  }, [decision, edited, result]);

  const submitManual = useCallback(async () => {
    if (!manual.trim()) return;
    try {
      await issueCommand({ action: 'mission_from_utterance', params: { text: manual.trim(), source: 'manual_text' }, inputModality: 'pointer' });
      setIssued('직접 입력한 문장으로 발행했습니다 (음성 아님)');
    } catch (caught) {
      setError({ message: String(caught) });
    }
  }, [manual]);

  const hasAudio = phase === 'transcribing' || phase === 'reviewing' || Boolean(result);
  const steps = realSteps(phase, hasAudio, Boolean(result));
  const blocked = decision?.verdict === 'reject' || (decision?.verdict === 'confirm' && !confirmed);
  const appliedHotwords = Number(result?.applied_options?.hotword_count ?? 0);

  return (
    <aside className="utterance-panel">
      <h2>발화 · Utterance</h2>

      <LevelMeter levels={levels} live={phase === 'recording'} />

      <div className="stt-controls">
        {phase === 'recording'
          ? <button className="rec-stop" onClick={stopRecording}>■ 녹음 정지</button>
          : <button disabled={!able.canRecord || phase === 'transcribing'} onClick={() => void startRecording()}>● 녹음</button>}
        <label className="file-fallback">
          파일
          <input type="file" accept="audio/*" disabled={!able.canTranscribe || phase === 'transcribing'}
            onChange={(event) => { const file = event.target.files?.[0]; if (file) void send(file); }} />
        </label>
        <label className="hotword-toggle" title="끄면 레지스트리 어휘 편향 없이 인식합니다. VZ-L-03 임계 실측의 대조군입니다.">
          <input type="checkbox" checked={useHotwords} onChange={(event) => setUseHotwords(event.target.checked)} />
          호칭 사전
        </label>
      </div>

      {able.note && <p className="stt-note">{able.note}</p>}
      {phase === 'transcribing' && <p className="stt-note">인식 중입니다. 모델을 처음 읽는 경우 오래 걸립니다.</p>}
      {error && <p className="stt-error">{error.message}{error.detail ? <small>{error.detail}</small> : null}</p>}

      <div className="progress-steps">
        {steps.map((step) => <span key={step.label} className={`step-${step.state}`}>{STEP_MARK[step.state]} {step.label}</span>)}
        {MOCK_STEPS.map((label) => (
          <span key={label} className="step-mock" title="아직 목입니다 — VZ-G-01·VZ-G-02, 로컬 LLM 필요">
            <b>목</b> {label}
          </span>
        ))}
      </div>

      {result && decision ? (
        <>
          <label className="transcript-edit">
            <span>인식 결과 — 고칠 수 있습니다 (1차 확인 · REQ-1303)</span>
            <textarea value={edited} rows={2} onChange={(event) => { setEdited(event.target.value); setConfirmed(false); }} />
          </label>
          {edited.trim() !== result.text && (
            <p className="transcript-original">원문: “{result.text}” <small>원문과 수정본을 둘 다 보관합니다</small></p>
          )}
          <dl>
            <dt>엔진</dt><dd>{result.engine} · {result.model}</dd>
            <dt>판정</dt>
            <dd className={`verdict-${decision.verdict}`}>
              {VERDICT_LABEL[decision.verdict]} <small>{PROVISIONAL_NOTE}</small>
            </dd>
            <dt>호칭 사전</dt>
            <dd>
              {useHotwords ? `${appliedHotwords}개 적용` : '끔 (대조군)'}
              {useHotwords && appliedHotwords === 0 ? <small>요청했으나 적용되지 않음</small> : null}
            </dd>
            <dt>생성 주체</dt><dd>produced_by=human · input_modality=voice</dd>
          </dl>
          <Numbers result={result} decision={decision} />
          {decision.verdict === 'confirm' && (
            <label className="reconfirm">
              <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
              위 문장이 맞는지 확인했습니다
            </label>
          )}
          {decision.verdict === 'reject' && <p className="stt-error">임계 미만입니다. 다시 녹음하거나 아래에 문장을 직접 넣으세요.</p>}
          <button className="submit-utterance" disabled={blocked || !edited.trim()} onClick={() => void submitVoice()}>
            이 발화로 임무 생성 요청
          </button>
        </>
      ) : (
        <blockquote>“{fallbackText}”<small>시나리오 목 문장 — 녹음하면 실제 인식 결과로 바뀝니다</small></blockquote>
      )}

      <details className="manual-input" open={status === 'unavailable'}>
        <summary>문장을 직접 넣기</summary>
        <p className="hint">STT 서비스({STT_BASE_URL})가 없어도 이 경로는 항상 열려 있습니다.</p>
        <textarea value={manual} rows={2} placeholder="예: 503 구역 로봇을 5층 복도로 이동시켜"
          onChange={(event) => setManual(event.target.value)} />
        <button disabled={!manual.trim()} onClick={() => void submitManual()}>직접 입력으로 요청</button>
      </details>

      {issued && <p className="stt-issued">{issued}</p>}
    </aside>
  );
}
