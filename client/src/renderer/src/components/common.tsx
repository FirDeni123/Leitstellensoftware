import { useEffect, type ReactNode } from 'react';
import { ApiError, describeError } from '@/api/http';

const dateTime = new Intl.DateTimeFormat('de-DE', {
  day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
});
const timeOnly = new Intl.DateTimeFormat('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

export function fmtDateTime(value: string | Date | null | undefined): string {
  if (!value) return '–';
  return dateTime.format(typeof value === 'string' ? new Date(value) : value);
}

export function fmtTime(value: string | Date): string {
  return timeOnly.format(typeof value === 'string' ? new Date(value) : value);
}

export function ErrorAlert({ error }: { error: unknown }): ReactNode {
  if (!error) return null;
  const conflict = error instanceof ApiError && error.isConflict;
  return (
    <div className="alert error" role="alert">
      {conflict ? 'Konflikt: ' : ''}
      {describeError(error)}
    </div>
  );
}

export function Modal(props: {
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose?: () => void;
  width?: number;
}): ReactNode {
  const { onClose } = props;
  useEffect(() => {
    if (!onClose) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={props.title} style={props.width ? { width: props.width } : undefined}>
        <header>{props.title}</header>
        <div className="body">{props.children}</div>
        {props.footer && <footer>{props.footer}</footer>}
      </div>
    </div>
  );
}

/** Labelled form field. The <label> wraps the control, so the label is associated with it
 *  (screen readers, click-to-focus) without having to manage ids. */
export function Field(props: { label: string; children: ReactNode; className?: string }): ReactNode {
  return (
    <label className={`field ${props.className ?? ''}`}>
      <span className="field-label">{props.label}</span>
      {props.children}
    </label>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }): ReactNode {
  return (
    <div className="empty-state">
      <div style={{ fontWeight: 600, color: 'var(--text-1)' }}>{title}</div>
      {children}
    </div>
  );
}
