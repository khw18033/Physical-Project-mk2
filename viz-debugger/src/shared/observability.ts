export type ClientHealth = { connected: boolean; subscriptions: number; lastError: string | null };

let health: ClientHealth = { connected: false, subscriptions: 0, lastError: null };

export function updateClientHealth(next: Partial<ClientHealth>) {
  health = { ...health, ...next };
}

export function getClientHealth(): ClientHealth {
  return { ...health };
}
