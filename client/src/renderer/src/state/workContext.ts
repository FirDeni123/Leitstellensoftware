/**
 * Active control centre of this workstation. Panels of tenant-scoped data (stations,
 * vehicles, RICs …) filter by it and use it for new records. Remembered per PC.
 */
import { useEffect } from 'react';
import { create } from 'zustand';
import { useControlCenters } from '@/api/queries';
import type { ControlCenter } from '@/api/types';

const STORAGE_KEY = 'ils-active-control-center';

function readStored(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

interface WorkContext {
  controlCenterId: string | null;
  setControlCenter: (id: string) => void;
}

export const useWorkContext = create<WorkContext>((set) => ({
  controlCenterId: readStored(),
  setControlCenter: (id) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* ignore – only a convenience */
    }
    set({ controlCenterId: id });
  },
}));

/** Active control centre, falling back to the first visible one. */
export function useActiveControlCenter(): { active: ControlCenter | null; all: ControlCenter[]; loading: boolean } {
  const { data, isLoading } = useControlCenters();
  const { controlCenterId, setControlCenter } = useWorkContext();
  const all = data ?? [];
  const active = all.find((c) => c.id === controlCenterId) ?? all[0] ?? null;
  useEffect(() => {
    if (active && active.id !== controlCenterId) setControlCenter(active.id);
  }, [active, controlCenterId, setControlCenter]);
  return { active, all, loading: isLoading };
}
