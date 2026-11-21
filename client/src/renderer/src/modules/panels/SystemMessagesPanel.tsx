import { useEffect, useState, type ReactNode } from 'react';
import { EmptyState, fmtTime } from '@/components/common';
import { useMessages, type MessageLevel } from '@/state/messages';

const LEVEL: Record<MessageLevel, { label: string; cls: string }> = {
  info: { label: 'Info', cls: 'info' },
  success: { label: 'OK', cls: 'ok' },
  warning: { label: 'Warnung', cls: 'warn' },
  error: { label: 'Fehler', cls: 'danger' },
};

export function SystemMessagesPanel(): ReactNode {
  const { messages, markRead, clear } = useMessages();
  const [filter, setFilter] = useState<MessageLevel | 'all'>('all');
  useEffect(() => markRead(), [messages.length, markRead]);
  const shown = filter === 'all' ? messages : messages.filter((m) => m.level === filter);

  return (
    <div className="panel">
      <div className="panel-toolbar">
        <div className="chips">
          {(['all', 'error', 'warning', 'info', 'success'] as const).map((l) => (
            <button key={l} className={`chip ${filter === l ? 'on' : ''}`} onClick={() => setFilter(l)}>
              {l === 'all' ? 'Alle' : LEVEL[l].label}
            </button>
          ))}
        </div>
        <div className="spacer" />
        <button className="btn sm ghost" onClick={clear} disabled={!messages.length}>Leeren</button>
      </div>
      <div className="panel-body">
        {shown.length === 0 ? (
          <EmptyState title="Keine Systemmeldungen" />
        ) : (
          <table className="data">
            <thead><tr><th style={{ width: 80 }}>Zeit</th><th style={{ width: 80 }}>Stufe</th><th style={{ width: 130 }}>Quelle</th><th>Meldung</th></tr></thead>
            <tbody>
              {shown.map((m) => (
                <tr key={m.id}>
                  <td className="tabular">{fmtTime(m.ts)}</td>
                  <td><span className={`badge ${LEVEL[m.level].cls}`}>{LEVEL[m.level].label}</span></td>
                  <td className="muted">{m.source}</td>
                  <td className="selectable" title={m.text}>{m.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
