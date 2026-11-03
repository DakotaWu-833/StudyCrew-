import { useEffect, useRef, useState, type PropsWithChildren } from "react";
import { createPortal } from "react-dom";
import { errorMessage } from "../api/client";
import { Button, FloatingPanel, PanelCancel } from "./UI";

/** The same modal, focus handling and discard guard as New project. */
export default function CreationDialog({ children, title, triggerLabel, busy = false, disabled = false,
  completedKey, forceOpen = false, onClose, error,
}: PropsWithChildren<{ title: string; triggerLabel?: string; busy?: boolean; disabled?: boolean;
  completedKey?: number; forceOpen?: boolean; onClose?: () => void; error?: unknown }>) {
  const [opened, setOpened] = useState(false);
  const [dirty, setDirty] = useState(false);
  const visible = forceOpen || opened;
  const wasOpen = useRef(false);
  const initialCompletion = useRef(completedKey);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const close = () => { setOpened(false); setDirty(false); closeRef.current?.(); };

  useEffect(() => {
    if (visible && !wasOpen.current) {
      initialCompletion.current = completedKey;
      setDirty(false);
    }
    wasOpen.current = visible;
    // Only a fresh successful operation closes the form. Pending, failed and
    // previous operations leave it open with its values available for retry.
    if (visible && !busy && completedKey !== undefined && completedKey !== initialCompletion.current) close();
  }, [visible, busy, completedKey]);

  return <>
    {triggerLabel && <Button type="button" disabled={busy || disabled} aria-haspopup="dialog" aria-expanded={visible}
      onClick={() => { initialCompletion.current = completedKey; setDirty(false); setOpened(true); }}>{triggerLabel}</Button>}
    {visible && createPortal(<FloatingPanel title={title} busy={busy} dirty={dirty} onDismiss={close}>
      <fieldset className="creation-dialog__content" disabled={busy} onChangeCapture={() => setDirty(true)} onInputCapture={() => setDirty(true)}
        onSubmitCapture={event => { if (busy) { event.preventDefault(); event.stopPropagation(); } }}
        onSubmit={event => event.stopPropagation()}>
        {children}
      </fieldset>
      {Boolean(error) && <p className="form-error" role="alert">{typeof error === "string" ? error : errorMessage(error)}</p>}
      <div className="form-actions creation-dialog__cancel"><PanelCancel busy={busy} /></div>
    </FloatingPanel>, document.body)}
  </>;
}
