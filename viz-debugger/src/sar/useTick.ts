/**
 * src/sar/useTick.ts (261002) — 「몇 초 전」·연결 상태처럼 **시간이 지나면 바뀌는 것**을 다시 그리게 한다.
 */

import { useEffect, useState } from 'react';

export function useTick(ms: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}
