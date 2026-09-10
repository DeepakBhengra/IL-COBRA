import { useEffect, useRef, useState } from "react";

interface ConfirmResolutionModalProps {
  open: boolean;
  selectedText: string;
  sourceLabel: string;
  saving?: boolean;
  onConfirm: (comment: string) => Promise<void>;
  onCancel: () => void;
}

export function ConfirmResolutionModal({
  open,
  selectedText,
  sourceLabel,
  saving = false,
  onConfirm,
  onCancel,
}: ConfirmResolutionModalProps) {
  const [comment, setComment] = useState("");
  const [modalError, setModalError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (open) {
      setComment("");
      setModalError(null);
      requestAnimationFrame(() => textareaRef.current?.focus());
    }
  }, [open, selectedText]);

  if (!open) {
    return null;
  }

  const handleConfirmClick = async () => {
    setModalError(null);
    try {
      await onConfirm(comment);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to save confirmed resolution";
      setModalError(message);
    }
  };

  return (
    <div className="ops-modal-overlay" onClick={onCancel} role="presentation">
      <div
        className="ops-modal"
        role="dialog"
        aria-labelledby="confirm-resolution-title"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="confirm-resolution-title">Confirm resolution</h3>
        <p className="ops-modal-source">
          Source: <strong>{sourceLabel}</strong>
        </p>
        <p className="ops-modal-selected" title={selectedText}>
          {selectedText}
        </p>
        <label className="ops-modal-label" htmlFor="confirm-resolution-comment">
          Comments (optional)
        </label>
        <textarea
          id="confirm-resolution-comment"
          ref={textareaRef}
          className="ops-modal-textarea"
          rows={4}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          disabled={saving}
          placeholder="Add analyst notes about this resolution…"
        />
        {modalError && <p className="alert alert-error ops-modal-error">{modalError}</p>}
        <div className="ops-modal-actions">
          <button type="button" className="secondary-btn" onClick={onCancel} disabled={saving}>
            Cancel
          </button>
          <button
            type="button"
            className="primary-btn"
            onClick={() => void handleConfirmClick()}
            disabled={saving}
          >
            {saving ? "Saving…" : "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}
