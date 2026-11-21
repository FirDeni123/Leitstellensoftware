import { useEffect, useState, type ReactNode } from 'react';
import { useSession } from '@/state/session';

const time = new Intl.DateTimeFormat('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const date = new Intl.DateTimeFormat('de-DE', { weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric' });

/** Clock synchronised to the server time (all timestamps in the system are server time). */
export function Clock(): ReactNode {
  const offset = useSession((s) => s.serverTimeOffsetMs);
  const [now, setNow] = useState(() => new Date(Date.now() + offset));
  useEffect(() => {
    const id = setInterval(() => setNow(new Date(Date.now() + offset)), 250);
    return () => clearInterval(id);
  }, [offset]);
  return (
    <div className="clock" title="Serverzeit">
      <span className="clock-time tabular">{time.format(now)}</span>
      <span className="clock-date">{date.format(now)}</span>
    </div>
  );
}
