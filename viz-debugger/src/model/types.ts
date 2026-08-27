export type TaskStatus = 'pending' | 'running' | 'done' | 'failed' | 'skipped' | 'awaiting_evaluation' | 'not_executed' | 'rerunning';
export type Connection = 'online' | 'offline' | 'maintenance';
export type Hardware = { id: string; kind: string; connection: Connection; battery: number; rssi: number; latency: number; ip: string; firmware: string; temperature: number; heartbeat: string };
export type ActionItem = { id: string; label: string; params: Record<string, string | number>; status: TaskStatus };
export type Task = { id: string; title: string; deps: string[]; target: string; actionItems: ActionItem[] };
export type Milestone = { id: string; title: string; status: TaskStatus; assignedTargets: string[] };
export type ScenarioEvent = { seq: number; atSec: number; nodeId: string; status: TaskStatus; kind: string; producedBy: 'ai' | 'backend' | 'human'; attempt?: number };
export type Scenario = { missionId: string; utterance: { text: string; engine: string; confidence: number; audioRef: string }; durationSec: number; milestones: Milestone[]; hardware: Hardware[]; tasks: Task[]; events: ScenarioEvent[] };
