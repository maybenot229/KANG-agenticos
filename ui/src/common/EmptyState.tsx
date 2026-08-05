import "./EmptyState.css";

/**
 * Shared shape for any screen with no real data source behind it yet
 * (09_UI §4: "Empty states MUST be honest and quiet... never suggestions
 * to explore features"). Originally written for dashboard Zones 3/4;
 * promoted here (from zones/EmptyZone.tsx) once the domain shells needed
 * the identical concept — Projects/Competitions/Learn/Know/Chat are each
 * "a screen the constitution requires to exist, with nothing real behind
 * it today," the same shape as the two zones, not a second one.
 */
export default function EmptyState({
  label,
  heading,
  message,
}: {
  label: string;
  heading: string;
  message: string;
}) {
  return (
    <section aria-label={label} className="empty-state">
      <h2 className="empty-state__heading">{heading}</h2>
      <p className="empty-state__status">{message}</p>
    </section>
  );
}
