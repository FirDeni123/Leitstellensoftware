import { useQueryClient } from '@tanstack/react-query';
import { useMemo, useState, type ReactNode } from 'react';
import { ApiError } from '@/api/http';
import { usePermissions, useRoles } from '@/api/queries';
import type { Permission, Role } from '@/api/types';
import { EmptyState, ErrorAlert, Field, Modal } from '@/components/common';
import { sysmsg } from '@/state/messages';
import { hasPermission, useSession } from '@/state/session';

/** Roles and their permissions, grouped by area. */
export function RolesPanel(): ReactNode {
  const me = useSession((s) => s.me)!;
  const roles = useRoles();
  const perms = usePermissions();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const canWrite = hasPermission(me, 'roles.write');
  const selected = roles.data?.find((r) => r.id === selectedId);

  return (
    <div className="panel">
      <div className="panel-toolbar">
        <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{roles.data?.length ?? 0} Rollen · {perms.data?.length ?? 0} Berechtigungen</span>
        <div className="spacer" />
        {canWrite && <button className="btn primary sm" onClick={() => setCreating(true)}>+ Rolle</button>}
      </div>
      <ErrorAlert error={roles.error} />
      <div className="panel-split">
        <div className="master table-wrap">
          <table className="data">
            <thead><tr><th>Rolle</th><th>Schlüssel</th><th>Rechte</th><th>Typ</th></tr></thead>
            <tbody>
              {(roles.data ?? []).map((r) => (
                <tr key={r.id} className={`clickable ${r.id === selectedId ? 'selected' : ''}`} onClick={() => setSelectedId(r.id)}>
                  <td>{r.name}</td>
                  <td className="mono">{r.key}</td>
                  <td className="tabular">{r.permissions.length}</td>
                  <td>{r.is_system ? <span className="badge">System</span> : <span className="badge accent">Eigene</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="detail">
          {selected ? <RoleEditor key={`${selected.id}:${selected.version}`} role={selected} catalogue={perms.data ?? []} canWrite={canWrite} onDeleted={() => setSelectedId(null)} />
            : <EmptyState title="Rolle auswählen" />}
        </div>
      </div>
      {creating && <CreateRoleDialog onClose={() => setCreating(false)} onCreated={setSelectedId} />}
    </div>
  );
}

function RoleEditor(props: { role: Role; catalogue: Permission[]; canWrite: boolean; onDeleted: () => void }): ReactNode {
  const { role, catalogue, canWrite } = props;
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const [name, setName] = useState(role.name);
  const [description, setDescription] = useState(role.description ?? '');
  const [granted, setGranted] = useState(new Set(role.permissions));
  const [error, setError] = useState<unknown>(null);
  const areas = useMemo(() => {
    const map = new Map<string, Permission[]>();
    for (const p of catalogue) map.set(p.area, [...(map.get(p.area) ?? []), p]);
    return [...map.entries()];
  }, [catalogue]);
  const dirty = name !== role.name || description !== (role.description ?? '') || [...granted].sort().join() !== [...role.permissions].sort().join();
  const toggle = (code: string) => setGranted((g) => { const n = new Set(g); if (n.has(code)) n.delete(code); else n.add(code); return n; });

  const save = async () => {
    setError(null);
    try {
      await api.patch(`/roles/${role.id}`, { name, description: description || null, permissions: [...granted], expected_version: role.version });
      await qc.invalidateQueries({ queryKey: ['roles'] });
      sysmsg('success', 'Rollen', `Rolle „${name}“ gespeichert – betroffene Benutzer erhalten die Rechte sofort`);
    } catch (e) {
      setError(e);
    }
  };
  const remove = async () => {
    if (!window.confirm(`Rolle „${role.name}“ löschen?`)) return;
    try {
      await api.delete(`/roles/${role.id}`);
      await qc.invalidateQueries({ queryKey: ['roles'] });
      props.onDeleted();
    } catch (e) {
      setError(e);
    }
  };

  return (
    <div>
      <div style={{ fontSize: 'var(--fs-lg)', fontWeight: 600 }}>{role.name} <span className="muted mono" style={{ fontSize: 'var(--fs-xs)' }}>{role.key}</span></div>
      {error instanceof ApiError && error.isConflict ? (
        <div className="alert error" style={{ marginTop: 8 }}>{error.message} <button className="btn sm" onClick={() => void qc.invalidateQueries({ queryKey: ['roles'] })}>Neu laden</button></div>
      ) : <div style={{ marginTop: 8 }}><ErrorAlert error={error} /></div>}
      <div className="form-grid" style={{ marginTop: 8 }}>
        <Field label="Name"><input className="input" value={name} disabled={!canWrite} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Beschreibung"><input className="input" value={description} disabled={!canWrite} onChange={(e) => setDescription(e.target.value)} /></Field>
      </div>
      {areas.map(([area, list]) => (
        <div key={area}>
          <div className="section-title">{area}</div>
          <div className="perm-grid">
            {list.map((p) => {
              const locked = role.key === 'admin' && p.code === 'system.admin';
              return (
                <label key={p.code} className="checkbox" title={p.code}>
                  <input type="checkbox" checked={granted.has(p.code)} disabled={!canWrite || locked} onChange={() => toggle(p.code)} />
                  <span>{p.description}{p.code === 'interfaces.activate_real' || p.code === 'system.mode.change' ? <span className="badge danger" style={{ marginLeft: 6 }}>kritisch</span> : null}</span>
                </label>
              );
            })}
          </div>
        </div>
      ))}
      {canWrite && (
        <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
          <button className="btn primary" disabled={!dirty} onClick={() => void save()}>Speichern</button>
          <button className="btn" disabled={!dirty} onClick={() => { setName(role.name); setDescription(role.description ?? ''); setGranted(new Set(role.permissions)); }}>Verwerfen</button>
          {!role.is_system && <button className="btn danger" style={{ marginLeft: 'auto' }} onClick={() => void remove()}>Löschen</button>}
        </div>
      )}
    </div>
  );
}

function CreateRoleDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const [key, setKey] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState<unknown>(null);
  const submit = async () => {
    try {
      const role = await api.post<Role>('/roles', { key, name, permissions: [] });
      await qc.invalidateQueries({ queryKey: ['roles'] });
      onCreated(role.id);
      onClose();
    } catch (e) {
      setError(e);
    }
  };
  return (
    <Modal title="Rolle anlegen" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Abbrechen</button><button className="btn primary" disabled={!key || name.length < 2} onClick={() => void submit()}>Anlegen</button></>}>
      <Field label="Schlüssel"><input className="input mono" autoFocus value={key} placeholder="z. B. funk" onChange={(e) => setKey(e.target.value.toLowerCase())} /></Field>
      <Field label="Name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <ErrorAlert error={error} />
    </Modal>
  );
}
