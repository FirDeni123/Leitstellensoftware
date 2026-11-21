import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useLayoutActions } from '@/layout/DockArea';
import type { Workstation, WorkstationKey } from '@/layout/workstations';
import { canOpenPanel, PANELS } from '@/modules/registry';
import { useSession } from '@/state/session';
import { Clock } from './Clock';

function useOutsideClose(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && close();
    window.addEventListener('mousedown', onDown);
    return () => window.removeEventListener('mousedown', onDown);
  }, [open, close]);
  return ref;
}

export function TopBar(props: {
  workstations: Workstation[];
  current: WorkstationKey | undefined;
  onChangePassword: () => void;
}): ReactNode {
  const me = useSession((s) => s.me)!;
  const setWorkstation = useSession((s) => s.setWorkstation);
  const logout = useSession((s) => s.logout);
  const { openPanel, resetLayout } = useLayoutActions();
  const [menu, setMenu] = useState<'windows' | 'user' | null>(null);
  const close = () => setMenu(null);
  const ref = useOutsideClose(menu !== null, close);

  const cc = me.control_centers[0];

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark sm" aria-hidden>ILS</span>
        <div className="brand-text">
          <span className="brand-title">ILS-Sim</span>
          <span className="brand-sub">{cc ? cc.name : me.all_control_centers ? 'Alle Leitstellen' : 'Keine Leitstelle zugeordnet'}</span>
        </div>
      </div>

      <nav className="ws-tabs" aria-label="Arbeitsplätze">
        {props.workstations.map((w) => (
          <button key={w.key} className={`ws-tab ${w.key === props.current ? 'active' : ''}`} onClick={() => setWorkstation(w.key)} title={`${w.title} (${w.shortcut})`}>
            {w.title}
            <span className="kbd">{w.shortcut}</span>
          </button>
        ))}
      </nav>

      <div className="topbar-spacer" />

      <div className="topbar-actions" ref={ref}>
        <div className="menu-anchor">
          <button className="btn ghost sm" onClick={() => setMenu(menu === 'windows' ? null : 'windows')} aria-haspopup="menu">Fenster ▾</button>
          {menu === 'windows' && (
            <div className="menu" role="menu">
              {PANELS.filter((p) => canOpenPanel(p, me.permissions)).map((p) => (
                <button key={p.id} role="menuitem" className="menu-item" onClick={() => { openPanel(p.id); close(); }}>
                  <span>{p.title}</span>
                  {!p.implemented && <span className="badge">Phase {p.phase}</span>}
                </button>
              ))}
              <div className="menu-sep" />
              <button role="menuitem" className="menu-item" onClick={() => { resetLayout(); close(); }}>Layout zurücksetzen</button>
            </div>
          )}
        </div>

        <Clock />

        <div className="menu-anchor">
          <button className="user-button" onClick={() => setMenu(menu === 'user' ? null : 'user')} aria-haspopup="menu">
            <span className="avatar">{me.display_name.slice(0, 1).toUpperCase()}</span>
            <span className="user-name">{me.display_name}</span>
          </button>
          {menu === 'user' && (
            <div className="menu right" role="menu">
              <div className="menu-head">
                <div style={{ fontWeight: 600 }}>{me.display_name}</div>
                <div className="muted mono" style={{ fontSize: 'var(--fs-xs)' }}>{me.username} · {me.roles.join(', ')}</div>
              </div>
              <button role="menuitem" className="menu-item" onClick={() => { props.onChangePassword(); close(); }}>Passwort ändern</button>
              <button role="menuitem" className="menu-item" onClick={() => void logout()}>Abmelden</button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
