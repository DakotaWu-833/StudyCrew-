import { useState, type ButtonHTMLAttributes, type PropsWithChildren, type ReactNode } from "react";
import { errorMessage } from "../api/client";

export function Button({ className = "", variant = "primary", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "quiet" }) {
  return <button className={`button button--${variant} ${className}`.trim()} {...props} />;
}

export function ConfirmAction({
  busy = false,
  confirmLabel = "Confirm",
  message,
  onConfirm,
  triggerLabel,
  triggerVariant = "danger",
}: {
  busy?: boolean;
  confirmLabel?: string;
  message: string;
  onConfirm: () => void;
  triggerLabel: string;
  triggerVariant?: "primary" | "secondary" | "danger" | "quiet";
}) {
  const [confirming, setConfirming] = useState(false);

  if (!confirming) {
    return <Button type="button" variant={triggerVariant} disabled={busy} onClick={() => setConfirming(true)}>{triggerLabel}</Button>;
  }

  return (
    <span className="confirm-action" role="group" aria-label={message}>
      <span className="confirm-action__message">{message}</span>
      <span className="confirm-action__buttons">
        <Button type="button" variant="danger" disabled={busy} onClick={onConfirm}>
          {busy ? "Working…" : confirmLabel}
        </Button>
        <Button type="button" variant="quiet" disabled={busy} onClick={() => setConfirming(false)}>Go back</Button>
      </span>
    </span>
  );
}

export function Panel({ children, className = "", labelledBy }: PropsWithChildren<{ className?: string; labelledBy?: string }>) {
  return <section className={`panel ${className}`.trim()} aria-labelledby={labelledBy}>{children}</section>;
}

export function Field({ label, children, hint, error }: { label: string; children: ReactNode; hint?: string; error?: string }) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      {children}
      {hint && <span className="field__hint">{hint}</span>}
      {error && <span className="field__error">{error}</span>}
    </label>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="state-message" role="status"><span className="spinner" aria-hidden="true" />{label}</div>;
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="state-message state-message--error" role="alert">
      <span>{errorMessage(error)}</span>
      {retry && <Button variant="secondary" onClick={retry}>Try again</Button>}
    </div>
  );
}

export function EmptyState({ title, children }: PropsWithChildren<{ title: string }>) {
  return <div className="empty-state"><h3>{title}</h3><p>{children}</p></div>;
}

export function StatusBadge({ value }: { value: string }) {
  return <span className={`badge badge--${value.replaceAll("_", "-")}`}>{value.replaceAll("_", " ")}</span>;
}
