/**
 * Editing protection for records that other dispatchers may change at the same time.
 *
 * `base` is the version the user started editing. A newer version arriving via realtime
 * replaces the form only when it has no unsaved input; otherwise the user keeps the input,
 * sees a warning, and a save is rejected by the server (409) instead of silently overwriting
 * either side. "Neu laden" adopts the latest version.
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { ApiError } from '@/api/http';
import { ErrorAlert } from './common';

export interface EditBase<T, F> {
  form: F;
  setForm: (update: F | ((f: F) => F)) => void;
  initial: F;
  dirty: boolean;
  stale: boolean;
  baseVersion: number | undefined;
  /** Adopt the latest record version (discarding input). */
  reload: () => void;
  /** After an own successful save: the server response becomes the new base. */
  rebase: (saved: T) => void;
}

export function useEditBase<T, F>(item: T | undefined, toForm: (record: T | undefined) => F,
  version: (record: T) => number | undefined): EditBase<T, F> {
  const [base, setBase] = useState<T | undefined>(item);
  const initial = useMemo(() => toForm(base), [base]); // eslint-disable-line react-hooks/exhaustive-deps
  const [form, setForm] = useState<F>(initial);
  const dirty = JSON.stringify(form) !== JSON.stringify(initial);
  const stale = !!item && !!base && version(item) !== version(base);

  useEffect(() => {
    if (stale && !dirty) {
      setBase(item);
      setForm(toForm(item));
    }
  }, [item]); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    form, setForm, initial, dirty, stale,
    baseVersion: base ? version(base) : undefined,
    reload: () => { setBase(item); setForm(toForm(item)); },
    rebase: (saved: T) => { setBase(saved); setForm(toForm(saved)); },
  };
}

/** Warning for a concurrently changed record plus error / conflict display. */
export function EditNotices({ stale, error, onReload }: { stale: boolean; error: unknown; onReload: () => void }): ReactNode {
  const conflict = error instanceof ApiError && error.isConflict;
  return (
    <>
      {stale && !conflict && (
        <div className="alert warning" style={{ marginTop: 12 }}>
          Dieser Datensatz wurde zwischenzeitlich von einer anderen Person geändert. Ihre Eingaben sind noch nicht gespeichert.{' '}
          <button type="button" className="btn sm" onClick={onReload}>Neu laden (Eingaben verwerfen)</button>
        </div>
      )}
      {conflict ? (
        <div className="alert error" style={{ marginTop: 12 }}>
          {(error as ApiError).message} <button type="button" className="btn sm" onClick={onReload}>Neu laden</button>
        </div>
      ) : (
        error ? <div style={{ marginTop: 12 }}><ErrorAlert error={error} /></div> : null
      )}
    </>
  );
}
