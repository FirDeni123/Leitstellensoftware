/** Formatting and selection helpers for the Einsatzmittelvorschlag (unit tested). */
import type { Proposal, ProposalPick, TravelSource } from '@/api/types';

/** Seconds as "m:ss min" (same format as the server's reasons). */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '–';
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')} min`;
}

export const TRAVEL_SOURCE: Record<TravelSource | 'mixed', string> = {
  osrm: 'Route (OSRM)',
  estimate: 'Schätzung (Luftlinie × Umwegfaktor)',
  mixed: 'Route/Schätzung gemischt',
  none: 'ohne Fahrzeit (keine Koordinaten)',
};

/** Vehicles that would be newly assigned when accepting: proposed, not yet in the incident. */
export function initialSelection(proposal: Proposal): string[] {
  return proposal.picks.filter((p) => !p.in_incident).map((p) => p.vehicle_id);
}

/** Replace one proposed vehicle by an alternative (keeps the order of the selection). */
export function swapVehicle(selection: readonly string[], from: string, to: string): string[] {
  if (selection.includes(to)) return selection.filter((id) => id !== from);
  return selection.map((id) => (id === from ? to : id));
}

/** Picks grouped by demand line, in demand order. */
export function picksByDemand(proposal: Proposal): Map<string, ProposalPick[]> {
  const map = new Map<string, ProposalPick[]>(proposal.demands.map((d) => [d.key, []]));
  for (const p of proposal.picks) map.get(p.demand_key)?.push(p);
  return map;
}
