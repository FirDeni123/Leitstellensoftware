/**
 * Dockable work area. Panels can be dragged, split, tabbed and floated. The layout is
 * persisted per user and workstation on the server (debounced, optimistic locking) so a
 * dispatcher gets their arrangement back on any PC.
 */
import { DockviewReact, themeAbyss, type DockviewApi, type DockviewReadyEvent, type IDockviewPanelProps } from 'dockview-react';
import { useCallback, useEffect, useRef, type FunctionComponent, type ReactNode } from 'react';
import { create } from 'zustand';
import { ApiError, describeError } from '@/api/http';
import type { LayoutDoc } from '@/api/types';
import { canOpenPanel, PANEL_BY_ID, PANELS } from '@/modules/registry';
import { PanelHost } from '@/modules/PanelHost';
import { sysmsg } from '@/state/messages';
import { useSession } from '@/state/session';
import { permittedLayout, type DefaultLayout, type Workstation } from './workstations';

// Bumped when default layouts change substantially (stored layouts are replaced once).
const LAYOUT_SCHEMA = 6;
const SAVE_DEBOUNCE_MS = 1500;

interface LayoutActions {
  openPanel: (id: string) => void;
  resetLayout: () => void;
  set: (actions: Partial<Omit<LayoutActions, 'set'>>) => void;
}

export const useLayoutActions = create<LayoutActions>((set) => ({
  openPanel: () => undefined,
  resetLayout: () => undefined,
  set: (actions) => set(actions),
}));

// Stable component map (dockview requires referentially stable components).
const COMPONENTS: Record<string, FunctionComponent<IDockviewPanelProps>> = Object.fromEntries(
  PANELS.map((def) => [def.id, () => <PanelHost definition={def} />]),
);

export function applyDefaultLayout(api: DockviewApi, layout: DefaultLayout): void {
  api.clear();
  for (const column of layout.columns) {
    let previousGroupLead: string | undefined;
    column.groups.forEach((group, groupIndex) => {
      const lead = group[0]!;
      group.forEach((panelId, index) => {
        const def = PANEL_BY_ID.get(panelId);
        if (!def) return;
        const position =
          index > 0
            ? { referencePanel: lead, direction: 'within' as const }
            : groupIndex > 0 && previousGroupLead
              ? { referencePanel: previousGroupLead, direction: 'below' as const }
              : api.panels.length > 0
                ? { direction: 'right' as const }
                : undefined;
        const width = index === 0 && groupIndex === 0 && api.panels.length > 0 ? column.width : undefined;
        api.addPanel({ id: panelId, component: panelId, title: def.title, position, ...(width ? { initialWidth: width } : {}) });
      });
      api.getPanel(lead)?.api.setActive();
      previousGroupLead = lead;
    });
  }
}

export function DockArea({ workstation }: { workstation: Workstation }): ReactNode {
  const api = useSession((s) => s.api)!;
  const permissions = useSession((s) => s.me?.permissions ?? []);
  const dockRef = useRef<DockviewApi | null>(null);
  const versionRef = useRef<number | null>(null);
  const loadingRef = useRef(true);
  const pendingOpen = useRef<string[]>([]);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const permsRef = useRef(permissions);
  permsRef.current = permissions;

  const path = `/me/layouts/${workstation.key}`;

  const removeForbidden = useCallback((dock: DockviewApi) => {
    for (const panel of [...dock.panels]) {
      const def = PANEL_BY_ID.get(panel.id);
      if (!def || !canOpenPanel(def, permsRef.current)) panel.api.close();
    }
  }, []);

  const save = useCallback(async () => {
    const dock = dockRef.current;
    if (!dock || loadingRef.current) return;
    const body = { layout: { schema: LAYOUT_SCHEMA, dock: dock.toJSON() }, expected_version: versionRef.current };
    try {
      const doc = await api.put<LayoutDoc>(path, body);
      versionRef.current = doc.version;
    } catch (e) {
      if (e instanceof ApiError && e.isConflict) {
        // Same user changed the layout on another PC: their latest action here wins.
        const current = (e.details['current_version'] as number | null | undefined) ?? null;
        versionRef.current = current;
        try {
          const doc = await api.put<LayoutDoc>(path, { ...body, expected_version: current });
          versionRef.current = doc.version;
        } catch (e2) {
          sysmsg('warning', 'Layout', `Layout konnte nicht gespeichert werden: ${describeError(e2)}`);
        }
      } else {
        sysmsg('warning', 'Layout', `Layout konnte nicht gespeichert werden: ${describeError(e)}`);
      }
    }
  }, [api, path]);

  const scheduleSave = useCallback(() => {
    if (loadingRef.current) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => void save(), SAVE_DEBOUNCE_MS);
  }, [save]);

  const loadDefault = useCallback(() => {
    const dock = dockRef.current;
    if (!dock) return;
    loadingRef.current = true;
    applyDefaultLayout(dock, permittedLayout(workstation, permsRef.current));
    loadingRef.current = false;
  }, [workstation]);

  const load = useCallback(async () => {
    const dock = dockRef.current;
    if (!dock) return;
    loadingRef.current = true;
    try {
      const doc = await api.get<LayoutDoc>(path);
      versionRef.current = doc.version;
      const stored = doc.layout as { schema?: number; dock?: Parameters<DockviewApi['fromJSON']>[0] };
      if (stored.schema !== LAYOUT_SCHEMA || !stored.dock) throw new Error('Layout-Format veraltet');
      dock.fromJSON(stored.dock);
      removeForbidden(dock);
      if (dock.panels.length === 0) throw new Error('Layout leer');
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) {
        sysmsg('info', 'Layout', 'Gespeichertes Layout nicht verwendbar – Standardlayout geladen');
      }
      applyDefaultLayout(dock, permittedLayout(workstation, permsRef.current));
    } finally {
      loadingRef.current = false;
      const pending = pendingOpen.current.splice(0);
      for (const id of pending) useLayoutActions.getState().openPanel(id);
    }
  }, [api, path, removeForbidden, workstation]);

  const onReady = useCallback(
    (event: DockviewReadyEvent) => {
      dockRef.current = event.api;
      event.api.onDidLayoutChange(() => scheduleSave());
      void load();
    },
    [load, scheduleSave],
  );

  // Permissions can change at runtime (admin edits the user): close panels no longer allowed.
  useEffect(() => {
    if (dockRef.current && !loadingRef.current) removeForbidden(dockRef.current);
  }, [permissions, removeForbidden]);

  useEffect(() => {
    useLayoutActions.getState().set({
      openPanel: (id: string) => {
        const dock = dockRef.current;
        const def = PANEL_BY_ID.get(id);
        if (!def) return;
        if (!dock || loadingRef.current) {
          pendingOpen.current.push(id); // opened after the stored layout has been applied
          return;
        }
        const existing = dock.getPanel(id);
        if (existing) {
          existing.api.setActive();
          return;
        }
        const active = dock.activePanel;
        dock.addPanel({
          id, component: id, title: def.title,
          position: active ? { referencePanel: active.id, direction: 'within' } : undefined,
        });
      },
      resetLayout: () => {
        void api.delete(path).catch(() => undefined);
        versionRef.current = null;
        loadDefault();
        sysmsg('info', 'Layout', `Standardlayout „${workstation.title}" wiederhergestellt`);
      },
    });
    return () => {
      if (saveTimer.current) {
        clearTimeout(saveTimer.current);
        void save(); // flush pending change when switching workstation
      }
    };
  }, [api, path, loadDefault, save, workstation.title]);

  return (
    <div className="dock-host">
      <DockviewReact components={COMPONENTS} onReady={onReady} theme={themeAbyss} />
    </div>
  );
}
