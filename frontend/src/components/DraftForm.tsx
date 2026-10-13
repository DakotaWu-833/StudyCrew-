import { useEffect, useRef, useState, type FormHTMLAttributes } from "react";
import { useQuery } from "@tanstack/react-query";
import { accountApi } from "../api/resources";
import { clearDraft, loadDraft, saveDraft, type StoredDraft } from "../app/drafts";
import { Button } from "./UI";

type Props = FormHTMLAttributes<HTMLFormElement> & { scope: string; fields: string[] };
export default function DraftForm({ scope, fields, children, onChange, onReset, ...props }: Props) {
  const form = useRef<HTMLFormElement>(null), me = useQuery({ queryKey: ["me"], queryFn: accountApi.me });
  const user = me.data?.user.id;
  const [saved, setSaved] = useState<StoredDraft | null>(null), [stored, setStored] = useState(false);
  const fieldsKey = fields.join(",");
  useEffect(() => { setSaved(user ? loadDraft(user, scope) : null); setStored(false); }, [user, scope]);
  function store() {
    if (!user || !form.current) return;
    const data = new FormData(form.current), values: Record<string, string> = {};
    // Call sites explicitly name plain text fields. Credentials and identifiers
    // are never copied from the rest of the form.
    for (const field of fieldsKey.split(",")) {
      if (/password|token|secret|otp|email|code/i.test(field)) continue;
      const value = data.get(field); if (typeof value === "string") values[field] = value.slice(0, 12000);
    }
    saveDraft(user, scope, values); setStored(true);
  }
  function discard() { if (user) clearDraft(user, scope); setSaved(null); setStored(false); }
  function restore() {
    if (!form.current || !saved) return;
    for (const field of fields) {
      const value = saved.values[field], element = form.current.elements.namedItem(field);
      if (typeof value !== "string" || !(element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement)) continue;
      const setter = Object.getOwnPropertyDescriptor(element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, "value")?.set;
      setter?.call(element, value); element.dispatchEvent(new Event("input", { bubbles: true })); element.dispatchEvent(new Event("change", { bubbles: true }));
    }
    setSaved(null); setStored(true);
  }
  return <form ref={form} {...props} onChange={event => { store(); onChange?.(event); }} onReset={event => { discard(); onReset?.(event); }}>
    {saved && <div className="notice" role="status"><p>A local draft from {new Date(saved.savedAt).toLocaleString()} is available.</p><Button type="button" variant="secondary" onClick={restore}>Restore draft</Button><Button type="button" variant="quiet" onClick={discard}>Discard draft</Button></div>}
    {children}{stored && <p className="muted" role="status">Draft kept on this device for up to 24 hours. It is cleared after saving or signing out.</p>}
  </form>;
}
