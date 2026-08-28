# viz-debugger

임무 실행 기록을 되짚는 디버깅 도구의 HCI 프로토타입이다. **이 폴더는 `web-dashboard`를 대체하지 않는다.** 현재 게이트웨이와 데이터는 목이며, 화면 상단에도 그 사실을 표시한다.

```bash
npm install
npm run dev
```

브라우저는 `http://127.0.0.1:5174`, 목 WebSocket 게이트웨이는 `ws://127.0.0.1:8790`, STT 서비스는 `http://127.0.0.1:8801`을 사용하므로 기존 대시보드(5173/8787~8788)나 `stt-lab`(8799)과 동시에 실행할 수 있다.

화면은 마일스톤과 노드를 클릭해 다음 계층으로 이동한다. 마일스톤 카드 배정, 그래프 노드 자유 배치, DAG/트리 전환, 노드 더블클릭, 임무 이력 리플레이, 실패 파라미터 수정이 동작한다. 정적 전달본과 논의 항목은 [HANDOFF.md](./HANDOFF.md)에 정리했다.

## 음성 인식 (`VZ-L-01`)

발화 패널의 녹음·인식은 **실제로 동작한다.** 파형은 마이크 입력 레벨이고, 인용문은 인식 결과이며, 진행 막대의 앞 두 칸(`음성 수신`·`STT 변환`)은 실제 상태를 따라간다. **뒤 세 칸(`의도 분석`·`마일스톤 분리`·`태스크 생성`)은 아직 목이고 화면에 `목` 배지가 붙어 있다** — `VZ-G-01`·`VZ-G-02`이고 로컬 LLM이 필요하다.

인식 결과는 **고칠 수 있고, 원문과 수정본을 둘 다 보관한다**(`REQ-1303`). 원문만 남기면 오인식을 놓치고 수정본만 남기면 STT 성능을 평가할 수 없다.

### 파이썬 환경

STT는 별도 파이썬 프로세스다(faster-whisper는 CTranslate2 런타임이라 브라우저에서 돌지 않는다). **Python 3.10 이상**이 필요하다.

```powershell
cd viz-debugger\stt
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

이 `.venv`가 있으면 `npm run dev`가 STT 서비스도 함께 띄운다. 자세한 것은 [stt/README.md](./stt/README.md).

**모델 최초 다운로드는 오래 걸린다.** 기본 모델 `large-v3-turbo`를 첫 요청에서 1.5 GB 안팎 내려받으므로, 첫 인식이 몇 분 걸려도 실패가 아니다. 두 번째부터는 캐시된다.

### STT 서비스를 안 띄웠을 때

**화면은 그대로 뜬다.** 음성 기능만 꺼지고, 무엇이 왜 꺼졌는지 패널에 문구가 남으며, **문장을 직접 넣는 경로는 열려 있다**(`VZ-C-02`·`VZ-G-01`). 화면 전체가 죽거나 무한 로딩에 걸리지 않는다. `npm run verify:no-stt`가 이걸 검사한다.

## 검증

```
npm run typecheck
npm run verify:scenario      npm run verify:layout        npm run verify:hierarchy
npm run verify:adapter-swap  npm run verify:transport     npm run verify:single-egress
npm run verify:standalone    npm run verify:stt-port      npm run verify:voice-audit
npm run verify:no-stt        npm run build
```

STT 관련 세 가지가 무엇을 잡는지:

| 스크립트 | 무엇을 잡는가 |
|---|---|
| `verify:stt-port` | 이식한 `stt/engines/*.py`가 `stt-lab` 원본과 **바이트 동일한가** (출처 주석 제외). 두 벌이 조용히 갈라지는 것을 막는다 |
| `verify:voice-audit` | `input_modality: 'voice'`인데 `voice` 감사 필드가 빠진 명령이 **실제로 거부되는가** (`REQ-1305`) |
| `verify:no-stt` | STT가 전부 실패하는 상태에서 화면이 뜨고 수동 입력이 살아 있는가 |

셋 다 **음성 대조군**을 포함한다 — 검사를 무력화한 사본이 반드시 실패로 잡히는지까지 확인한다. 검사가 아무것도 못 잡은 채 통과하던 일이 실제로 있었다(`reports/2026-08-28_1036_통합구현_검토.md` B항).
