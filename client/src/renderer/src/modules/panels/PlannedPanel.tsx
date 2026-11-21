import type { ReactNode } from 'react';
import type { PanelDefinition } from '../registry';

/** Honest placeholder for modules of later phases – no fake data. */
export function PlannedPanel({ definition }: { definition: PanelDefinition }): ReactNode {
  return (
    <div className="panel">
      <div className="planned">
        <div className="planned-head">
          <span className="badge warn">Noch nicht implementiert</span>
          <span className="badge">Geplant für Phase {definition.phase}</span>
        </div>
        <div className="planned-title">{definition.title}</div>
        <p className="muted">Dieses Fenster ist im Arbeitsplatz-Layout bereits vorgesehen. Die Funktion folgt mit Phase {definition.phase}:</p>
        <ul>
          {(definition.scope ?? []).map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
