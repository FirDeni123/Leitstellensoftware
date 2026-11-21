import { useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { useControlCenters, usePermissions, useRoles, useUsers } from '@/api/queries';
import type { Permission, PermissionOverride, User, UserCreatedResponse } from '@/api/types';
import { EmptyState, ErrorAlert, Field, fmtDateTime, Modal } from '@/components/common';
import { EditNotices, useEditBase } from '@/components/useEditBase';
import { hasPermission, useSession } from '@/state/session';
import { sysmsg } from '@/state/messages';

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

export function UsersPanel(): ReactNode {
  const me = useSession((s) => s.me)!;
  const [q, setQ] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const users = useUsers(q);
  const selected = users.data?.items.find((u) => u.id === selectedId) ?? null;
  const canWrite = hasPermission(me, 'users.write');

  return (
    <div className="panel">
      <div className="panel-toolbar">
        <input className="input" placeholder="Suchen (Name, Benutzername)" aria-label="Benutzer suchen" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 260 }} />
        <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{users.data?.total ?? 0} Benutzer</span>
        <div className="spacer" />
        {canWrite && <button className="btn primary sm" onClick={() => setCreating(true)}>+ Benutzer anlegen</button>}
      </div>
      <ErrorAlert error={users.error} />
      <div className="panel-split">
        <div className="master table-wrap">
          <table className="data">
            <thead><tr><th>Benutzername</th><th>Name</th><th>Rollen</th><th>Status</th><th>Letzte Anmeldung</th></tr></thead>
            <tbody>
              {(users.data?.items ?? []).map((u) => (
                <tr key={u.id} className={`clickable ${u.id === selectedId ? 'selected' : ''} ${u.is_active ? '' : 'inactive'}`} onClick={() => setSelectedId(u.id)}>
                  <td className="mono">{u.username}</td>
                  <td>{u.display_name}</td>
                  <td>{u.roles.join(', ')}</td>
                  <td><UserStatus user={u} /></td>
                  <td className="tabular muted">{fmtDateTime(u.last_login_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="detail">
          {selected ? <UserEditor key={selected.id} user={selected} canWrite={canWrite} /> : <EmptyState title="Benutzer auswählen" />}
        </div>
      </div>
      {creating && <CreateUserDialog onClose={() => setCreating(false)} onCreated={(id) => setSelectedId(id)} />}
    </div>
  );
}

function UserStatus({ user }: { user: User }): ReactNode {
  if (!user.is_active) return <span className="badge">Deaktiviert</span>;
  if (user.locked_until && new Date(user.locked_until) > new Date()) return <span className="badge danger">Gesperrt</span>;
  if (user.must_change_password) return <span className="badge warn">Passwort ändern</span>;
  return <span className="badge ok">Aktiv</span>;
}

interface UserForm {
  displayName: string;
  email: string;
  roles: string[];
  ccIds: string[];
  overrides: PermissionOverride[];
}

const toUserForm = (u: User | undefined): UserForm => ({
  displayName: u?.display_name ?? '',
  email: u?.email ?? '',
  roles: [...(u?.roles ?? [])].sort(),
  ccIds: (u?.control_centers ?? []).map((c) => c.id).sort(),
  overrides: u?.permission_overrides ?? [],
});

function UserEditor({ user, canWrite }: { user: User; canWrite: boolean }): ReactNode {
  const api = useSession((s) => s.api)!;
  const me = useSession((s) => s.me)!;
  const qc = useQueryClient();
  const roles = useRoles();
  const ccs = useControlCenters();
  const canRoles = hasPermission(me, 'roles.write');
  // Editing protection against concurrent changes (see useEditBase).
  const edit = useEditBase(user, toUserForm, (u) => u.version);
  const { form, dirty } = edit;
  const set = <K extends keyof UserForm>(key: K) => (value: UserForm[K]) =>
    edit.setForm((f) => ({ ...f, [key]: Array.isArray(value) && key !== 'overrides' ? [...value].sort() : value }));
  const { displayName, email, roles: userRoles, ccIds, overrides } = form;
  const [setDisplayName, setEmail, setUserRoles, setCcIds, setOverrides] =
    [set('displayName'), set('email'), set('roles'), set('ccIds'), set('overrides')] as const;
  const catalogue = usePermissions();
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [password, setPassword] = useState<string | null>(null);

  const run = async (fn: () => Promise<unknown>, success: string) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      sysmsg('success', 'Benutzerverwaltung', success);
      await qc.invalidateQueries({ queryKey: ['users'] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const save = () => run(async () => {
    const saved = await api.patch<User>(`/users/${user.id}`, {
    expected_version: edit.baseVersion,
    display_name: displayName,
    email: email || null,
    control_center_ids: ccIds,
    ...(canRoles ? { roles: userRoles, permission_overrides: overrides } : {}),
    });
    edit.rebase(saved);
  }, `Benutzer ${user.username} gespeichert`);

  const locked = !!user.locked_until && new Date(user.locked_until) > new Date();
  const isSelf = user.id === me.id;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div style={{ fontSize: 'var(--fs-lg)', fontWeight: 600 }}>{user.display_name}</div>
        <UserStatus user={user} />
        <span className="muted mono" style={{ marginLeft: 'auto', fontSize: 'var(--fs-xs)' }}>v{user.version}</span>
      </div>
      <div className="muted mono" style={{ fontSize: 'var(--fs-sm)' }}>{user.username}</div>


      <div className="section-title">Stammdaten</div>
      <div className="form-grid">
        <Field label="Anzeigename"><input className="input" value={displayName} disabled={!canWrite} onChange={(e) => setDisplayName(e.target.value)} /></Field>
        <Field label="E-Mail"><input className="input" value={email} disabled={!canWrite} onChange={(e) => setEmail(e.target.value)} /></Field>
      </div>

      <div className="section-title">Rollen {!canRoles && <span className="muted">(Änderung erfordert roles.write)</span>}</div>
      <div className="chips">
        {(roles.data ?? []).map((r) => (
          <button key={r.key} className={`chip ${userRoles.includes(r.key) ? 'on' : ''}`} disabled={!canWrite || !canRoles} title={r.description ?? ''} onClick={() => setUserRoles(toggle(userRoles, r.key))}>{r.name}</button>
        ))}
      </div>

      <div className="section-title">Leitstellen</div>
      <div className="chips">
        {(ccs.data ?? []).map((c) => (
          <button key={c.id} className={`chip ${ccIds.includes(c.id) ? 'on' : ''}`} disabled={!canWrite} onClick={() => setCcIds(toggle(ccIds, c.id))}>{c.code}</button>
        ))}
        {ccs.data?.length === 0 && <span className="muted">Keine Leitstellen angelegt</span>}
      </div>

      <div className="section-title">Individuelle Rechte {!canRoles && <span className="muted">(Änderung erfordert roles.write)</span>}</div>
      <OverridesEditor value={overrides} onChange={setOverrides} disabled={!canWrite || !canRoles} catalogue={catalogue.data ?? []} />

      <EditNotices stale={edit.stale} error={error} onReload={() => { edit.reload(); setError(null); }} />
      {canWrite && (
        <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
          <button className="btn primary" disabled={!dirty || busy} onClick={() => void save()}>Speichern</button>
          <button className="btn" disabled={!dirty || busy} onClick={() => edit.reload()}>Verwerfen</button>
        </div>
      )}

      <div className="section-title">Effektive Berechtigungen ({user.effective_permissions.length})</div>
      <div className="chips">{user.effective_permissions.map((p) => <span key={p} className="badge mono">{p}</span>)}</div>

      <div className="section-title">Konto</div>
      <dl className="kv">
        <dt>Letzte Anmeldung</dt><dd>{fmtDateTime(user.last_login_at)}</dd>
        <dt>Angelegt</dt><dd>{fmtDateTime(user.created_at)}</dd>
        <dt>Geändert</dt><dd>{fmtDateTime(user.updated_at)}</dd>
        {locked && <><dt>Gesperrt bis</dt><dd>{fmtDateTime(user.locked_until)}</dd></>}
      </dl>
      {canWrite && (
        <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
          <button className="btn" disabled={busy} onClick={() => void run(async () => {
            const res = await api.post<UserCreatedResponse>(`/users/${user.id}/reset-password`, { expected_version: user.version });
            setPassword(res.initial_password);
          }, `Passwort von ${user.username} zurückgesetzt`)}>Passwort zurücksetzen</button>
          {locked && <button className="btn" disabled={busy} onClick={() => void run(() => api.post(`/users/${user.id}/unlock`), `Sperre von ${user.username} aufgehoben`)}>Sperre aufheben</button>}
          <button className={`btn ${user.is_active ? 'danger' : ''}`} disabled={busy || isSelf} title={isSelf ? 'Eigenes Konto kann nicht deaktiviert werden' : undefined}
            onClick={() => void run(() => api.put(`/users/${user.id}/active`, { is_active: !user.is_active, expected_version: user.version }),
              `Benutzer ${user.username} ${user.is_active ? 'deaktiviert' : 'aktiviert'}`)}>
            {user.is_active ? 'Deaktivieren' : 'Aktivieren'}
          </button>
        </div>
      )}
      {password && <InitialPasswordDialog username={user.username} password={password} onClose={() => setPassword(null)} />}
    </div>
  );
}

/** grant/deny exceptions on top of the roles (deny wins). */
function OverridesEditor(props: { value: PermissionOverride[]; onChange: (v: PermissionOverride[]) => void; disabled: boolean; catalogue: Permission[] }): ReactNode {
  const [code, setCode] = useState('');
  const [effect, setEffect] = useState<'grant' | 'deny'>('grant');
  const label = (c: string) => props.catalogue.find((p) => p.code === c)?.description ?? c;
  const free = props.catalogue.filter((p) => !props.value.some((o) => o.permission_code === p.code));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div className="chips">
        {props.value.length === 0 && <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>keine – Rechte ergeben sich nur aus den Rollen</span>}
        {props.value.map((o) => (
          <span key={o.permission_code} className={`chip on ${o.effect === 'deny' ? 'deny' : ''}`} title={o.permission_code}>
            {o.effect === 'grant' ? '+' : '−'} {label(o.permission_code)}
            {!props.disabled && <button type="button" className="chip-x" aria-label="Ausnahme entfernen" onClick={() => props.onChange(props.value.filter((x) => x !== o))}>×</button>}
          </span>
        ))}
      </div>
      {!props.disabled && (
        <div style={{ display: 'flex', gap: 6 }}>
          <select className="select" aria-label="Berechtigung" value={code} onChange={(e) => setCode(e.target.value)} style={{ flex: 1, minWidth: 0 }}>
            <option value="">Berechtigung wählen …</option>
            {free.map((p) => <option key={p.code} value={p.code}>{p.area}: {p.description}</option>)}
          </select>
          <select className="select" aria-label="Wirkung" value={effect} onChange={(e) => setEffect(e.target.value as 'grant' | 'deny')}>
            <option value="grant">gewähren</option>
            <option value="deny">entziehen</option>
          </select>
          <button type="button" className="btn sm" disabled={!code} onClick={() => { props.onChange([...props.value, { permission_code: code, effect }]); setCode(''); }}>Hinzufügen</button>
        </div>
      )}
    </div>
  );
}

function InitialPasswordDialog(props: { username: string; password: string; onClose: () => void }): ReactNode {
  return (
    <Modal title="Initialpasswort" onClose={props.onClose} footer={<button className="btn primary" onClick={props.onClose}>Notiert – schließen</button>}>
      <div>Initialpasswort für <b className="mono">{props.username}</b>. Es wird nur jetzt angezeigt und muss bei der ersten Anmeldung geändert werden.</div>
      <div className="mono selectable" style={{ fontSize: 20, padding: 12, background: 'var(--bg-0)', border: '1px solid var(--line-strong)', borderRadius: 4, textAlign: 'center', letterSpacing: '0.05em' }}>{props.password}</div>
    </Modal>
  );
}

function CreateUserDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const roles = useRoles();
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [selectedRoles, setSelectedRoles] = useState<string[]>(['dispatcher']);
  const [error, setError] = useState<unknown>(null);
  const [created, setCreated] = useState<UserCreatedResponse | null>(null);

  if (created?.initial_password) {
    return <InitialPasswordDialog username={created.user.username} password={created.initial_password} onClose={onClose} />;
  }

  const submit = async () => {
    setError(null);
    try {
      const res = await api.post<UserCreatedResponse>('/users', { username, display_name: displayName, roles: selectedRoles });
      await qc.invalidateQueries({ queryKey: ['users'] });
      onCreated(res.user.id);
      sysmsg('success', 'Benutzerverwaltung', `Benutzer ${res.user.username} angelegt`);
      setCreated(res);
    } catch (e) {
      setError(e);
    }
  };

  return (
    <Modal title="Benutzer anlegen" onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Abbrechen</button>
      <button className="btn primary" disabled={!username || displayName.length < 2} onClick={() => void submit()}>Anlegen</button>
    </>}>
      <Field label="Benutzername"><input className="input mono" autoFocus value={username} onChange={(e) => setUsername(e.target.value.toLowerCase())} placeholder="z. B. m.mustermann" /></Field>
      <Field label="Anzeigename"><input className="input" value={displayName} onChange={(e) => setDisplayName(e.target.value)} /></Field>
      <div className="field"><label>Rollen</label>
        <div className="chips">{(roles.data ?? []).map((r) => (
          <button key={r.key} className={`chip ${selectedRoles.includes(r.key) ? 'on' : ''}`} onClick={() => setSelectedRoles(toggle(selectedRoles, r.key))}>{r.name}</button>
        ))}</div>
      </div>
      <div className="muted" style={{ fontSize: 'var(--fs-xs)' }}>Ein Initialpasswort wird erzeugt und einmalig angezeigt.</div>
      <ErrorAlert error={error} />
    </Modal>
  );
}
