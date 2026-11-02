export function DocumentChip({
  filename,
  busy,
  onRemove,
}: {
  filename: string;
  busy: boolean;
  onRemove: () => void;
}) {
  return (
    <div className="document-chip">
      <span className="document-name">{filename}</span>
      <button
        type="button"
        aria-label="Remove document"
        disabled={busy}
        onClick={onRemove}
      >
        ×
      </button>
    </div>
  );
}
