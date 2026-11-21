import { useEffect, useState, type ReactNode } from 'react';
import { describeError } from '@/api/http';
import { useSystemInfo } from '@/api/queries';
import { ChangePasswordForm } from '@/auth/ChangePasswordForm';
import { Modal } from '@/components/common';
import { DockArea } from '@/layout/DockArea';
import { PoliceNoticePopup } from '@/modules/alarming/PoliceNoticePopup';
import { installPositionUpdates } from '@/modules/fleet/live';
import { installCallAlert } from '@/modules/operations/callAlert';
import { availableWorkstations } from '@/layout/workstations';
import { sysmsg } from '@/state/messages';
import { onRealtimeEvent, useSession } from '@/state/session';
import { StatusBar } from './StatusBar';
import { TopBar } from './TopBar';

export function Shell(): ReactNode {
  const me = useSession((s) => s.me)!;
  const api = useSession((s) => s.api)!;
  const workstationKey = useSession((s) => s.workstation);
  const setWorkstation = useSession((s) => s.setWorkstation);
  const setSystemInfo = useSession((s) => s.setSystemInfo);
  const [changePassword, setChangePassword] = useState(false);
  const info = useSystemInfo();

  const workstations = availableWorkstations(me.permissions);
  const workstation = workstations.find((w) => w.key === workstationKey) ?? workstations[0];

  useEffect(() => {
    if (info.data) setSystemInfo(info.data);
    if (info.error) sysmsg('error', 'System', describeError(info.error));
  }, [info.data, info.error, setSystemInfo]);

  useEffect(() => installCallAlert(), []);
  useEffect(() => installPositionUpdates(), []);

  useEffect(
    () =>
      onRealtimeEvent((e) => {
        if (e.topic === 'system.mode_changed') {
          sysmsg('warning', 'Betriebsmodus', `Betriebsmodus geändert: ${e.data['mode'] === 'real' ? 'ECHTBETRIEB' : 'Simulation'}`);
        }
      }),
    [],
  );

  // F2–F7 switch workstations (classic control-room key layout).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = workstations.find((w) => w.shortcut === e.key);
      if (target && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        setWorkstation(target.key);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [workstations, setWorkstation]);

  const mode = info.data?.operation_mode ?? 'simulation';

  return (
    <div className={`shell mode-${mode}`}>
      <TopBar workstations={workstations} current={workstation?.key} onChangePassword={() => setChangePassword(true)} />
      {mode === 'simulation' ? (
        <div className="mode-banner sim" role="status">SIMULATIONSBETRIEB · Alle Alarmierungen, Fahrzeuge und Anrufe sind simuliert · Keine realen Schnittstellen aktiv</div>
      ) : (
        <div className="mode-banner real" role="alert">ECHTBETRIEB · Reale Schnittstellen können aktiv sein</div>
      )}
      {workstation ? (
        <DockArea key={workstation.key} workstation={workstation} />
      ) : (
        <div className="empty-state">Ihrem Konto ist kein Arbeitsplatz zugeordnet. Bitte an die Administration wenden.</div>
      )}
      <StatusBar />
      <PoliceNoticePopup />
      {changePassword && (
        <Modal title="Passwort ändern" onClose={() => setChangePassword(false)}>
          <ChangePasswordForm
            api={api}
            onCancel={() => setChangePassword(false)}
            onDone={(tokens) => {
              useSession.getState().setMe(tokens.user);
              useSession.getState().realtime?.reauthenticate();
              setChangePassword(false);
              sysmsg('success', 'Konto', 'Passwort geändert. Andere Sitzungen wurden abgemeldet.');
            }}
          />
        </Modal>
      )}
    </div>
  );
}
