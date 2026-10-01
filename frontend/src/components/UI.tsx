import { cloneElement, createContext, isValidElement, useContext, useEffect, useId, useRef, useState, type AriaAttributes, type ButtonHTMLAttributes, type PropsWithChildren, type ReactElement, type ReactNode, type Ref } from "react";
import { errorMessage } from "../api/client";

export function Button({ className = "", variant = "primary", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "quiet"; ref?: Ref<HTMLButtonElement> }) {
  return <button className={`button button--${variant} ${className}`.trim()} {...props} />;
}

export function FloatingPanel({
  children,
  onDismiss,
  title,
  className = "",
  busy = false,
  dirty = false,
}: PropsWithChildren<{ title: string; onDismiss: () => void; className?: string; busy?: boolean; dirty?: boolean }>) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const dismissRef = useRef(onDismiss);
  const openerRef = useRef<HTMLElement | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(false);
  const dismissedRef = useRef(false);
  const keepEditingRef = useRef<HTMLButtonElement>(null);
  const editingFocusRef = useRef<HTMLElement | null>(null);
  const [closing, setClosing] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const titleId = useId();
  const discardId = useId();
  dismissRef.current = onDismiss;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    mountedRef.current = true;
    dismissedRef.current = false;
    if (!openerRef.current && document.activeElement instanceof HTMLElement && !dialog.contains(document.activeElement)) {
      openerRef.current = document.activeElement;
    }
    if (!dialog.open) dialog.showModal();
    return () => {
      mountedRef.current = false;
      if (closeTimer.current) clearTimeout(closeTimer.current);
      closeTimer.current = null;
      const shouldRestoreFocus = dialog.contains(document.activeElement) || document.activeElement === document.body;
      if (dialog.open) dialog.close();
      if (shouldRestoreFocus && openerRef.current?.isConnected) openerRef.current.focus();
    };
  }, []);

  useEffect(() => {
    if (!confirmDiscard) return;
    if (!dirty) { setConfirmDiscard(false); return; }
    keepEditingRef.current?.focus();
  }, [confirmDiscard, dirty]);

  const finishClose = () => {
    if (!mountedRef.current || dismissedRef.current) return;
    dismissedRef.current = true;
    closeTimer.current = null;
    dialogRef.current?.close();
    if (openerRef.current?.isConnected) openerRef.current.focus();
    dismissRef.current();
  };

  const close = () => {
    const dialog = dialogRef.current;
    if (!dialog?.open || busy || closing || closeTimer.current !== null || dismissedRef.current) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      finishClose();
      return;
    }
    setClosing(true);
    closeTimer.current = setTimeout(finishClose, 180);
  };

  const requestClose = () => {
    if (busy || closing) return;
    if (dirty) {
      if (!confirmDiscard && document.activeElement instanceof HTMLElement) editingFocusRef.current = document.activeElement;
      setConfirmDiscard(true);
    } else close();
  };

  return (
    <dialog
      ref={dialogRef}
      className={`floating-panel ${closing ? "floating-panel--closing" : ""} ${className}`.trim()}
      aria-labelledby={titleId}
      aria-busy={busy || undefined}
      onCancel={(event) => {
        event.preventDefault();
        requestClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) requestClose();
      }}
      onClose={() => {
        if (mountedRef.current && !dismissedRef.current && !dialogRef.current?.open) finishClose();
      }}
    >
      <header className="floating-panel__header">
        <h2 id={titleId}>{title}</h2>
        <Button type="button" variant="quiet" className="floating-panel__close" aria-label={`Close ${title}`} disabled={busy || closing} onClick={requestClose}>×</Button>
      </header>
      <div className="floating-panel__body" inert={closing || undefined}>
        {children}
        {busy && <p className="floating-panel__working" role="status">Working… Please keep this window open.</p>}
        {confirmDiscard && dirty && <section className="floating-panel__discard" aria-labelledby={discardId}>
          <h3 id={discardId}>Discard unsaved changes?</h3>
          <p>Your changes have not been saved.</p>
          <div className="form-actions">
            <Button ref={keepEditingRef} type="button" variant="secondary" disabled={busy} onClick={() => {
              setConfirmDiscard(false);
              if (dialogRef.current?.contains(editingFocusRef.current)) editingFocusRef.current?.focus();
            }}>Keep editing</Button>
            <Button type="button" variant="danger" disabled={busy} onClick={close}>Discard changes</Button>
          </div>
        </section>}
      </div>
    </dialog>
  );
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

  return (
    <>
      <Button type="button" variant={triggerVariant} disabled={busy} onClick={() => setConfirming(true)}>{triggerLabel}</Button>
      {confirming && <FloatingPanel title={confirmLabel} className="floating-panel--confirm" onDismiss={() => setConfirming(false)}>
        <p className="floating-panel__message">{message}</p>
        <div className="form-actions floating-panel__actions">
          <Button type="button" variant="danger" disabled={busy} onClick={() => { setConfirming(false); onConfirm(); }}>
            {busy ? "Working…" : confirmLabel}
          </Button>
          <Button type="button" variant="quiet" disabled={busy} onClick={() => setConfirming(false)}>Go back</Button>
        </div>
      </FloatingPanel>}
    </>
  );
}

export function Panel({ children, className = "", labelledBy }: PropsWithChildren<{ className?: string; labelledBy?: string }>) {
  return <section className={`panel ${className}`.trim()} aria-labelledby={labelledBy}>{children}</section>;
}

type FieldControl = Pick<AriaAttributes, "aria-describedby" | "aria-invalid"> & { id: string };
const FieldControlContext = createContext<FieldControl | undefined>(undefined);

// Composite controls opt in at their actual input rather than receiving DOM props on a component.
export function useFieldControl() {
  return useContext(FieldControlContext);
}

export function Field({ label, children, hint, error, id }: { label: string; children: ReactNode; hint?: string; error?: string; id?: string }) {
  const generatedId = useId();
  const nativeChild = isValidElement(children) && typeof children.type === "string" && ["input", "select", "textarea"].includes(children.type)
    ? children as ReactElement<FieldControl>
    : null;
  const controlId = nativeChild?.props.id ?? id ?? `field-${generatedId}`;
  const hintId = `${controlId}-hint`;
  const errorId = `${controlId}-error`;
  const describedBy = [nativeChild?.props["aria-describedby"], hint ? hintId : "", error ? errorId : ""].filter(Boolean).join(" ") || undefined;
  const control: FieldControl = { id: controlId, "aria-describedby": describedBy, "aria-invalid": error ? true : nativeChild?.props["aria-invalid"] };
  return (
    <div className="field">
      <label className="field__label" htmlFor={controlId}>{label}</label>
      <FieldControlContext value={control}>{nativeChild ? cloneElement(nativeChild, control) : children}</FieldControlContext>
      {hint && <span className="field__hint" id={hintId}>{hint}</span>}
      {error && <span className="field__error" id={errorId}>{error}</span>}
    </div>
  );
}

export function Loading({ label = "Loading…", size = "full" }: { label?: string; size?: "full" | "compact" }) {
  return <div className={`state-message state-message--${size}`} role="status"><span className="spinner" aria-hidden="true" />{label}</div>;
}

export function ErrorState({ error, retry, size = "full" }: { error: unknown; retry?: () => void; size?: "full" | "compact" }) {
  return (
    <div className={`state-message state-message--error state-message--${size}`} role="alert">
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
