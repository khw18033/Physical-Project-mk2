import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { getTransport, type ConnectionState } from './transport/index.ts';
import './style.css';

function App() {
  const [state, setState] = useState<ConnectionState>('closed');
  useEffect(() => {
    const transport = getTransport();
    const unsubscribeStatus = transport.onStatus((status) => setState(status.state));
    const unsubscribeData = transport.subscribe(
      { entity: '*', node: '*', channel: '*' },
      () => undefined,
    );
    return () => { unsubscribeData(); unsubscribeStatus(); };
  }, []);
  return <main><div className={`banner banner--${state}`}>목 게이트웨이 연결: {state}</div></main>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
