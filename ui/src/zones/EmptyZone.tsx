import "./EmptyZone.css";

/**
 * Shared shape for a dashboard zone with no real data source to render yet
 * (09_UI §4: "Empty states MUST be honest and quiet... never suggestions
 * to explore features"). Zone 3 ("What changed?") and Zone 4 ("What
 * opportunities exist?") are the same concept — a zone the constitution
 * requires to exist in a stable position, with nothing real behind it
 * today — so this is written once and used by both rather than
 * duplicated per zone.
 */
export default function EmptyZone({
  label,
  heading,
  message,
}: {
  label: string;
  heading: string;
  message: string;
}) {
  return (
    <section aria-label={label} className="empty-zone">
      <h2 className="empty-zone__heading">{heading}</h2>
      <p className="empty-zone__status">{message}</p>
    </section>
  );
}
