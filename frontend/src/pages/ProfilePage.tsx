import { useEffect, useId, useMemo, useRef, useState, type ChangeEvent, type FormEvent, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { accountApi } from "../api/resources";
import type { Me, TimeZoneOption } from "../api/types";
import { errorMessage, fieldErrors } from "../api/client";
import { Button, ErrorState, Field, FloatingPanel, Loading, Panel } from "../components/UI";

const EMAIL_CHANGE_STORAGE_KEY = "studycrew.pending-email-change";
type PendingEmail = { request_id: string; new_email: string };

function ProfileIcon({ name }: { name: "person" | "camera" | "mail" | "lock" | "globe" | "arrow" }) {
  const paths = {
    person: <><circle cx="12" cy="8" r="3.5" /><path d="M5 21v-2a7 7 0 0 1 14 0v2" /></>,
    camera: <><path d="M8 5 6.5 8H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-9a2 2 0 0 0-2-2h-2.5L16 5Z" /><circle cx="12" cy="14" r="4" /></>,
    mail: <><rect x="3" y="5" width="18" height="14" rx="3" /><path d="m4 7 8 6 8-6" /></>,
    lock: <><rect x="5" y="10" width="14" height="11" rx="3" /><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3" /></>,
    globe: <><circle cx="12" cy="12" r="9" /><ellipse cx="12" cy="12" rx="4" ry="9" /><path d="M3 12h18" /></>,
    arrow: <path d="m9 5 7 7-7 7" />,
  };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function ProfileLocalTime({ timeZone }: { timeZone: string }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  let clock = "—";
  let date = "Local time is unavailable in this browser.";
  let offset: string | undefined;
  try {
    clock = new Intl.DateTimeFormat("en-GB", { timeZone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(now);
    date = new Intl.DateTimeFormat("en-GB", { timeZone, weekday: "long", day: "numeric", month: "short" }).format(now);
    offset = new Intl.DateTimeFormat("en-GB", { timeZone, timeZoneName: "longOffset" }).formatToParts(now).find((part) => part.type === "timeZoneName")?.value;
  } catch { /* Older browsers may not yet recognise a recently added IANA zone. */ }
  const city = timeZone.split("/").at(-1)?.replaceAll("_", " ") ?? timeZone;
  return <section className="profile-clock" aria-labelledby="profile-clock-heading">
    <div className="profile-clock__heading"><span className="profile-icon"><ProfileIcon name="globe" /></span><h3 id="profile-clock-heading">On your time</h3><span className="profile-clock__dot" aria-hidden="true" /></div>
    <p className="profile-clock__time">{clock}<span>{offset}</span></p>
    <p className="profile-clock__location">{city}<span>{date}</span></p>
    <p className="profile-clock__note">Your meetings, in your local time.</p>
  </section>;
}

function pendingEmailKey(userId: string) { return `${EMAIL_CHANGE_STORAGE_KEY}.${userId}`; }

function readPendingEmail(userId: string): PendingEmail | null {
  try {
    const stored = sessionStorage.getItem(pendingEmailKey(userId));
    if (!stored) return null;
    const parsed: unknown = JSON.parse(stored);
    if (typeof parsed === "object" && parsed !== null &&
      "request_id" in parsed && typeof parsed.request_id === "string" &&
      "new_email" in parsed && typeof parsed.new_email === "string") return parsed as PendingEmail;
  } catch { /* The browser may block session storage. The current page still works. */ }
  return null;
}

function storePendingEmail(userId: string, value: PendingEmail | null) {
  try {
    if (value) sessionStorage.setItem(pendingEmailKey(userId), JSON.stringify(value));
    else sessionStorage.removeItem(pendingEmailKey(userId));
  } catch { /* Keep the in-memory flow available when storage is blocked. */ }
}

function TimeZonePicker({ value, onChange, error }: { value: string; onChange: (value: string) => void; error?: string }) {
  const zones = useQuery({ queryKey: ["time-zones"], queryFn: accountApi.timeZones, staleTime: 60 * 60 * 1000 });
  const listId = useId();
  const hintId = `${listId}-hint`;
  const errorId = `${listId}-error`;
  const pickerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [active, setActive] = useState(0);
  const options = zones.data?.results ?? [];
  const selected = options.find((option) => option.value === value);
  const matches = useMemo(() => {
    const term = search.trim().toLocaleLowerCase();
    return term ? options.filter((option) => `${option.value} ${option.label} ${option.offset}`.toLocaleLowerCase().includes(term)) : [
      ...options.filter((option) => option.value === value),
      ...options.filter((option) => option.value !== value),
    ];
  }, [options, search, value]);
  const visible = matches;

  useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      if (!pickerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, []);

  useEffect(() => {
    if (open) document.getElementById(`${listId}-${active}`)?.scrollIntoView?.({ block: "nearest" });
  }, [active, listId, open, search]);

  const choose = (option: TimeZoneOption) => {
    onChange(option.value);
    setSearch("");
    inputRef.current?.focus();
    // Restoring input focus may fire onFocus; closing last keeps the choice visible.
    setOpen(false);
  };
  const openMenu = () => { setSearch(""); setActive(0); setOpen(true); };
  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") { setOpen(false); setSearch(""); return; }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setActive((index) => !open ? 0 : Math.max(0, Math.min(visible.length - 1, index + (event.key === "ArrowDown" ? 1 : -1))));
    }
    if (event.key === "Enter" && open) {
      event.preventDefault();
      if (visible[active]) choose(visible[active]);
    }
  };

  return <div className="field profile-time-zone" ref={pickerRef} onBlur={(event) => {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
  }}>
    <label className="field__label" htmlFor="profile-time-zone">Time zone</label>
    <div className="profile-time-zone__control">
      <input id="profile-time-zone" ref={inputRef} role="combobox" aria-autocomplete="list" aria-expanded={open} aria-controls={listId}
        aria-invalid={error ? true : undefined} aria-describedby={`${hintId}${error || zones.isError ? ` ${errorId}` : ""}`}
        aria-activedescendant={open && visible[active] ? `${listId}-${active}` : undefined}
        value={open ? search : selected?.label ?? value}
        placeholder={zones.isLoading ? "Loading time zones…" : "Search city or GMT offset"}
        disabled={zones.isLoading || zones.isError}
        onFocus={openMenu}
        onClick={() => { if (!open) openMenu(); }}
        onChange={(event) => { setSearch(event.target.value); setActive(0); setOpen(true); }}
        onKeyDown={handleKeyDown} />
      <span className="profile-time-zone__chevron" aria-hidden="true">⌄</span>
      {open && <div className="profile-time-zone__menu" id={listId} role="listbox" aria-label="Time zones">
      {visible.map((option, index) => <button key={option.value} id={`${listId}-${index}`} type="button" role="option"
        tabIndex={-1}
        aria-selected={option.value === value} className={index === active ? "profile-time-zone__option profile-time-zone__option--active" : "profile-time-zone__option"}
        onMouseDown={(event) => event.preventDefault()} onMouseEnter={() => setActive(index)} onClick={() => choose(option)}>
        <span>{option.value.replaceAll("_", " ")}</span><small>({option.offset})</small>
      </button>)}
      {!matches.length && <p className="profile-time-zone__empty">No matching time zones.</p>}
      </div>}
    </div>
    <span className="field__hint" id={hintId}>Worldwide cities · GMT offsets adjust for daylight saving.</span>
    {(error || zones.isError) && <span className="field__error" id={errorId} role="alert">{error || errorMessage(zones.error)} {zones.isError && <button type="button" className="profile-inline-link" onClick={() => void zones.refetch()}>Try again</button>}</span>}
  </div>;
}

function ProfileContent({ me }: { me: Me }) {
  const client = useQueryClient();
  const [displayName, setDisplayName] = useState(me.profile.display_name);
  const [biography, setBiography] = useState(me.profile.biography);
  const [timeZone, setTimeZone] = useState(me.profile.time_zone);
  const [profileMessage, setProfileMessage] = useState("");
  const [avatarMessage, setAvatarMessage] = useState("");
  const [emailMessage, setEmailMessage] = useState("");
  const [pendingEmail, setPendingEmail] = useState<PendingEmail | null>(() => readPendingEmail(me.user.id));
  const [emailOpen, setEmailOpen] = useState(Boolean(pendingEmail));
  const [emailDirty, setEmailDirty] = useState(false);
  const avatarInput = useRef<HTMLInputElement>(null);
  const profileForm = useRef<HTMLFormElement>(null);
  const emailForm = useRef<HTMLFormElement>(null);
  const avatarSource = me.profile.avatar_image_url
    ? `${me.profile.avatar_image_url}?v=${encodeURIComponent(me.profile.updated_at)}`
    : me.profile.avatar_url;
  const initials = me.profile.display_name.trim().slice(0, 1).toLocaleUpperCase() || "?";
  const dirty = displayName.trim() !== me.profile.display_name || biography.trim() !== me.profile.biography || timeZone !== me.profile.time_zone;

  const update = useMutation({
    mutationFn: accountApi.updateProfile,
    onSuccess: async (profile) => {
      document.documentElement.dataset.timeZone = profile.time_zone;
      await client.invalidateQueries({ queryKey: ["me"] });
      setProfileMessage("Profile saved.");
    },
  });
  const upload = useMutation({
    mutationFn: accountApi.uploadAvatar,
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ["me"] }); setAvatarMessage("Photo updated."); },
  });
  const requestChange = useMutation({
    mutationFn: accountApi.requestEmailChange,
    onSuccess: (result) => { storePendingEmail(me.user.id, result); setPendingEmail(result); setEmailDirty(false); setEmailOpen(true); setEmailMessage(`We sent a six-digit code to ${result.new_email}.`); },
  });
  const confirmChange = useMutation({
    mutationFn: accountApi.confirmEmailChange,
    onSuccess: async () => {
      storePendingEmail(me.user.id, null);
      setPendingEmail(null);
      setEmailDirty(false);
      setEmailOpen(false);
      await client.invalidateQueries({ queryKey: ["me"] });
      setEmailMessage("Email address verified and updated.");
    },
  });

  const profileErrors = fieldErrors(update.error);
  const emailError = pendingEmail ? confirmChange.error : requestChange.error;
  const emailErrors = fieldErrors(emailError);
  useEffect(() => {
    if (update.error) profileForm.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [update.error]);
  useEffect(() => {
    if (emailError) emailForm.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [emailError]);

  const submitProfile = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setProfileMessage("");
    update.mutate({ display_name: displayName.trim(), time_zone: timeZone, biography: biography.trim() });
  };
  const uploadAvatar = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setAvatarMessage("");
    upload.mutate(file);
  };
  const submitEmailRequest = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setEmailMessage("");
    const data = new FormData(event.currentTarget);
    requestChange.mutate({ new_email: String(data.get("new_email")).trim(), current_password: String(data.get("current_password")) });
  };
  const submitEmailCode = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!pendingEmail) return;
    setEmailMessage("");
    const data = new FormData(event.currentTarget);
    confirmChange.mutate({ request_id: pendingEmail.request_id, code: String(data.get("code")).trim() });
  };

  return <div className="page-stack profile-page">
    <div className="page-heading profile-heading"><div><p className="eyebrow">Your account</p><h2>Your profile</h2><p>A familiar face. A little about you.</p></div><span className="profile-heading__label"><ProfileIcon name="person" />Personal settings</span></div>
    <section className="profile-identity" aria-labelledby="profile-identity-heading">
      <div className="profile-identity__cover" aria-hidden="true"><span>A little more you.</span><div className="profile-identity__orbits"><i /><i /><i /></div><span className="profile-identity__wordmark">StudyCrew</span></div>
      <div className="profile-identity__body">
        <div className="profile-avatar">
          <div className="profile-avatar__image">{avatarSource ? <img src={avatarSource} alt="Your current profile photo" /> : <span aria-label="Your initials">{initials}</span>}</div>
          <button className="profile-avatar__edit" type="button" aria-label="Change profile photo" disabled={upload.isPending} onClick={() => avatarInput.current?.click()}><ProfileIcon name="camera" /></button>
        </div>
        <div className="profile-identity__details"><span className="profile-identity__label">Your team identity</span><h3 id="profile-identity-heading">{me.profile.display_name}</h3><p>{me.email}</p></div>
        <div className="profile-identity__actions"><Button type="button" variant="secondary" disabled={upload.isPending} onClick={() => avatarInput.current?.click()}><ProfileIcon name="camera" />{upload.isPending ? "Uploading…" : avatarSource ? "Change photo" : "Upload photo"}</Button><small>JPG, PNG or WebP · Up to 2 MB</small></div>
      </div>
      {(avatarMessage || upload.error) && <p className={upload.error ? "profile-identity__feedback field__error" : "profile-identity__feedback"} role={upload.error ? "alert" : "status"}>{upload.error ? errorMessage(upload.error) : avatarMessage}</p>}
      <input ref={avatarInput} className="profile-photo-card__input" type="file" accept="image/jpeg,image/png,image/webp" aria-hidden="true" tabIndex={-1} onChange={uploadAvatar} />
    </section>
    <div className="profile-layout">
        <Panel className="profile-card profile-details-card" labelledBy="profile-details-heading">
          <div className="profile-section-heading"><span className="profile-section-icon"><ProfileIcon name="person" /></span><div><h3 id="profile-details-heading">Personal details</h3><p>How you appear to your teammates.</p></div><span className={`profile-save-state${dirty ? " profile-save-state--draft" : ""}`}>{dirty ? "Unsaved changes" : "Up to date"}</span></div>
          {(profileMessage || update.error) && <p className={update.error ? "notice notice--error" : "notice"} role={update.error ? "alert" : "status"}>{update.error ? Object.keys(profileErrors).length ? "Please check the highlighted details." : errorMessage(update.error) : profileMessage}</p>}
          <form ref={profileForm} className="profile-form" onSubmit={submitProfile}>
            <Field label="Display name" error={profileErrors.display_name}><input name="display_name" required minLength={2} maxLength={80} value={displayName} onChange={(event) => { setDisplayName(event.target.value); if (update.error) update.reset(); }} autoComplete="name" /></Field>
            <TimeZonePicker value={timeZone} error={profileErrors.time_zone} onChange={(value) => { setTimeZone(value); if (update.error) update.reset(); }} />
            <div className="profile-biography"><Field label="About you" error={profileErrors.biography}><textarea name="biography" rows={4} maxLength={500} value={biography} onChange={(event) => { setBiography(event.target.value); if (update.error) update.reset(); }} placeholder="Your interests, your role, or what you bring to the team." /></Field><div className="profile-biography__meta"><span>A short introduction goes a long way.</span><span>{biography.length} / 500</span></div></div>
            <div className="profile-form__footer"><span><ProfileIcon name="person" />Visible to your project teammates</span><Button type="submit" disabled={update.isPending || !dirty}>{update.isPending ? "Saving…" : "Save changes"}</Button></div>
          </form>
        </Panel>
      <div className="profile-layout__aside">
        <Panel className="profile-card profile-security-card" labelledBy="profile-security-heading">
          <div className="profile-section-heading"><span className="profile-section-icon profile-section-icon--mint"><ProfileIcon name="lock" /></span><div><h3 id="profile-security-heading">Account &amp; security</h3><p>Just for you.</p></div></div>
          {emailMessage && !emailOpen && <p className="notice" role="status">{emailMessage}</p>}
          <div className="profile-security-row">
            <span className="profile-security-row__icon"><ProfileIcon name="mail" /></span><div><h4>Sign-in email</h4><p>{me.email}</p><Button type="button" variant="quiet" onClick={() => setEmailOpen(true)}>{pendingEmail ? "Continue email change" : "Change email"}<ProfileIcon name="arrow" /></Button></div>
          </div>
          <div className="profile-security-row">
            <span className="profile-security-row__icon"><ProfileIcon name="lock" /></span><div><h4>Password</h4><p>A private key to your workspace.</p><a className="button button--quiet" href="/account/password/">Change password<ProfileIcon name="arrow" /></a></div>
          </div>
          <p className="profile-security-note"><ProfileIcon name="lock" />Email changes require verification.</p>
        </Panel>
        <ProfileLocalTime timeZone={me.profile.time_zone} />
      </div>
    </div>
    {emailOpen && <FloatingPanel title={pendingEmail ? "Verify new email" : "Change sign-in email"} busy={requestChange.isPending || confirmChange.isPending} dirty={emailDirty} onDismiss={() => { setEmailOpen(false); setEmailDirty(false); requestChange.reset(); confirmChange.reset(); }}>
      <p className="profile-email-intro">{pendingEmail
        ? <>Enter the six-digit code sent to <strong>{pendingEmail.new_email}</strong>.</>
        : "For your security, confirm your current password. We will email a verification code to the new address."}</p>
      {(emailMessage || emailError) && <p className={emailError ? "notice notice--error" : "notice"} role={emailError ? "alert" : "status"}>{emailError ? Object.keys(emailErrors).length ? "Please check the highlighted details." : errorMessage(emailError) : emailMessage}</p>}
      {pendingEmail ? <form ref={emailForm} className="profile-email-form" onSubmit={submitEmailCode} onChange={() => { setEmailDirty(true); if (confirmChange.error) confirmChange.reset(); }}>
        <Field label="Six-digit verification code" error={emailErrors.code}><input name="code" required inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} placeholder="000000" /></Field>
        <div className="form-actions"><Button type="submit" disabled={confirmChange.isPending}>{confirmChange.isPending ? "Verifying…" : "Verify and update email"}</Button><Button type="button" variant="quiet" disabled={confirmChange.isPending} onClick={() => { storePendingEmail(me.user.id, null); setPendingEmail(null); setEmailDirty(false); setEmailMessage(""); confirmChange.reset(); requestChange.reset(); }}>Use a different address</Button></div>
      </form> : <form ref={emailForm} className="profile-email-form" onSubmit={submitEmailRequest} onChange={() => { setEmailDirty(true); if (requestChange.error) requestChange.reset(); }}>
        <Field label="New email address" error={emailErrors.new_email}><input name="new_email" type="email" required autoComplete="email" placeholder="you@example.com" /></Field>
        <Field label="Current password" error={emailErrors.current_password}><input name="current_password" type="password" required autoComplete="current-password" /></Field>
        <div className="form-actions"><Button type="submit" disabled={requestChange.isPending}>{requestChange.isPending ? "Sending code…" : "Send verification code"}</Button></div>
      </form>}
    </FloatingPanel>}
  </div>;
}

export default function ProfilePage() {
  const me = useQuery({ queryKey: ["me"], queryFn: accountApi.me });
  if (me.isLoading) return <Loading label="Loading profile…" />;
  if (me.error || !me.data) return <ErrorState error={me.error} retry={() => void me.refetch()} />;
  return <ProfileContent me={me.data} />;
}
