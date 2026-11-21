import type { ReactNode } from 'react';
import { useMessages } from '@/state/messages';
import { useSession } from '@/state/session';
import { useLayoutActions } from '@/layout/DockArea';

const STATE_TEXT = {
  idle: 'Nicht verbunden',
  connecting: 'Verbinde …',
  online: 'Echtzeit verbunden',
  reconnecting: 'Verbindung unterbrochen',
  closed: 'Getrennt',
} as const;

export function StatusBar(): ReactNode {
  const { rtState, rtDetail, latencyMs, serverUrl, systemInfo, me } = useSession();
  const unread = useMessages((s) => s.unread);
  const lastError = useMessages((s) => s.messages.find((m) => m.level === 'error' || m.level === 'warning'));
  const openPanel = useLayoutActions((s) => s.openPanel);
  const dot = rtState === 'online' ? 'ok' : rtState === 'reconnecting' ? 'danger pulse' : rtState === 'connecting' ? 'warn pulse' : 'idle';

  return (
    <footer className="statusbar" aria-label="Statusleiste">
      <span className="sb-item" title={rtDetail ?? undefined}>
        <span className={`dot ${dot}`} /> {STATE_TEXT[rtState]}
        {rtState === 'online' && latencyMs !== null && <span className="muted tabular"> · {latencyMs} ms</span>}
      </span>
      <span className="sb-item mono muted">{serverUrl}</span>
      {systemInfo && (
        <span className="sb-item muted">
          Server {systemInfo.version} · {systemInfo.environment} · Bus: {systemInfo.realtime_backend}
        </span>
      )}
      <span className="sb-spacer" />
      {rtState === 'reconnecting' && rtDetail && <span className="sb-item" style={{ color: '#ff9da1' }}>{rtDetail}</span>}
      <button className="sb-item sb-button" onClick={() => { openPanel('system-messages'); useMessages.getState().markRead(); }} title={lastError?.text}>
        Systemmeldungen {unread > 0 && <span className="badge accent">{unread}</span>}
      </button>
      <span className="sb-item muted">{me?.username}</span>
    </footer>
  );
}
