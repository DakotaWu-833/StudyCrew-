import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { accountReadinessApi, type AccountSecuritySummary } from "../api/accountReadiness";
import { APIError, errorMessage } from "../api/client";
import { Button, ErrorState, Field, Loading, Panel } from "../components/UI";
import { clearUserDrafts } from "../app/drafts";
import { clearOffline } from "../app/offlineTasks";
import type { Me } from "../api/types";

function date(value: string) {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function SecurityContent({ data }: { data: AccountSecuritySummary }) {
  const client = useQueryClient();
  const [verifiedUntil, setVerifiedUntil] = useState(0);
  const [clock, setClock] = useState(Date.now());
  const [message, setMessage] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const verified = verifiedUntil > clock;
  useEffect(() => {
    const interval = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, []);
  const refresh = () => client.invalidateQueries({ queryKey: ["account-security"] });

  const unlock = useMutation({
    mutationFn: accountReadinessApi.reauthenticate,
    onSuccess: (result) => {
      setClock(Date.now());
      setVerifiedUntil(Date.now() + result.valid_for_seconds * 1000);
      setMessage(result.message);
    },
  });
  type Action = { type: "recovery"; email: string } | { type: "remove" } | { type: "revoke"; id: string } | { type: "others" } | { type: "download" } | { type: "close"; confirmation: string };
  const action = useMutation({
    mutationFn: async (value: Action) => {
      switch (value.type) {
        case "recovery": return accountReadinessApi.requestRecoveryEmail(value.email);
        case "remove": return accountReadinessApi.removeRecoveryEmail();
        case "revoke": return accountReadinessApi.revokeDevice(value.id);
        case "others": return accountReadinessApi.revokeOthers();
        case "close": return accountReadinessApi.close(value.confirmation);
        case "download": {
          const payload = await accountReadinessApi.download();
          const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
          const anchor = document.createElement("a");
          anchor.href = url;
          anchor.download = "studycrew-personal-data.json";
          document.body.append(anchor);
          anchor.click();
          anchor.remove();
          window.setTimeout(() => URL.revokeObjectURL(url), 1000);
          return { message: "Your personal data download is ready. Store it privately." };
        }
      }
    },
    onSuccess: async (result, value) => {
      if (value.type === "close" || ("signed_out" in result && result.signed_out)) {
        const userId = client.getQueryData<Me>(["me"])?.user.id;
        if (userId) clearUserDrafts(userId);
        await clearOffline().catch(() => undefined);
        window.location.assign("/account/login/");
        return;
      }
      setMessage(result.message);
      await refresh();
    },
    onError: (error) => {
      if (error instanceof APIError && error.status === 403) setVerifiedUntil(0);
    },
  });
  const busy = unlock.isPending || action.isPending;
  const run = (value: Action) => { setMessage(""); action.mutate(value); };
  const submitPassword = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const password = String(new FormData(event.currentTarget).get("current_password") ?? "");
    event.currentTarget.reset();
    setMessage("");
    action.reset();
    unlock.mutate(password);
  };
  const submitRecovery = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get("email") ?? "").trim();
    run({ type: "recovery", email });
  };

  return <div className="page-stack">
    <div className="page-heading"><div><p className="eyebrow">Your account</p><h2>Security &amp; privacy</h2><p>Recover your account, review signed-in devices and control your information.</p></div></div>
    {(message || unlock.error || action.error) && <p className={unlock.error || action.error ? "notice notice--error" : "notice"} role={unlock.error || action.error ? "alert" : "status"}>{unlock.error || action.error ? errorMessage(action.error || unlock.error) : message}</p>}
    <Panel labelledBy="verify-password-heading">
      <h3 id="verify-password-heading">Confirm it is you</h3>
      <p>Confirm your password before changing recovery settings, revoking sessions, downloading personal data or closing your account. Verification lasts five minutes.</p>
      {verified && <p className="notice" role="status">Password confirmed. Sensitive actions are available for {Math.ceil((verifiedUntil - clock) / 60000)} minute(s).</p>}
      <form onSubmit={submitPassword} className="form-stack">
        <Field label="Current password"><input name="current_password" type="password" required autoComplete="current-password" maxLength={512} /></Field>
        <Button disabled={busy} type="submit">{unlock.isPending ? "Confirming…" : "Confirm password"}</Button>
      </form>
      <p><a href="/account/password/change/">Change password</a> · <a href="/account/password/reset/">Forgot password</a></p>
    </Panel>
    <Panel labelledBy="recovery-email-heading">
      <h3 id="recovery-email-heading">Recovery email</h3>
      <p>Verify a personally accessible email before your university mailbox expires. Recovering an unavailable mailbox requires your existing password, this verified recovery mailbox and verification of your new sign-in address.</p>
      {data.recovery_email ? <p><strong>{data.recovery_email.email}</strong><br />Verified {date(data.recovery_email.verified_at)}</p> : <p>No verified recovery email has been added.</p>}
      <form onSubmit={submitRecovery} className="form-stack">
        <Field label="Recovery email address"><input name="email" type="email" required autoComplete="email" maxLength={254} placeholder="Your personal email address" /></Field>
        <div className="form-actions"><Button type="submit" disabled={!verified || busy}>Send verification link</Button>
          {data.recovery_email && <Button type="button" variant="secondary" disabled={!verified || busy} onClick={() => run({ type: "remove" })}>Remove recovery email</Button>}</div>
      </form>
      <p>Your existing verified address remains until the replacement is verified. Verification links expire in 15 minutes.</p>
      <div className="form-actions"><Button type="button" variant="quiet" disabled={busy} onClick={() => void refresh()}>Refresh verification status</Button><a href="/account/recovery/">Recover an unavailable sign-in email</a></div>
    </Panel>
    <Panel labelledBy="device-sessions-heading">
      <h3 id="device-sessions-heading">Signed-in devices</h3>
      <p>Device descriptions come from each browser and do not prove a location or identity. Old sessions appear when they next use the service.</p>
      <div className="page-stack">{data.devices.map((device) => <div key={device.id} className="notice">
        <p><strong>{device.current ? "This browser" : "Signed-in browser"}</strong> · {device.browser}</p>
        <p>Last active: {date(device.last_seen_at)}<br />Session expires: {date(device.expires_at)}</p>
        <Button type="button" variant="secondary" disabled={!verified || busy} onClick={() => run({ type: "revoke", id: device.id })}>{device.current ? "Sign out this browser" : "Sign out device"}</Button>
      </div>)}</div>
      {!data.devices.length && <p>No active device registrations are available.</p>}
      <Button type="button" variant="secondary" disabled={!verified || busy} onClick={() => run({ type: "others" })}>Sign out all other devices</Button>
    </Panel>
    <Panel labelledBy="privacy-heading">
      <h3 id="privacy-heading">Your privacy and information</h3>
      <p>Notice version {data.privacy.version}</p>
      <h4>Visibility</h4><ul>{data.privacy.visibility.map((item) => <li key={item}>{item}</li>)}</ul>
      <h4>Retention and account closure</h4><ul>{data.privacy.retention.map((item) => <li key={item}>{item}</li>)}</ul>
      <h4>Download your information</h4><p>{data.privacy.download}</p>
      <Button type="button" disabled={!verified || busy} onClick={() => run({ type: "download" })}>Download my data</Button>
      <p><Link to="/app/support/">Contact support or request a privacy review</Link></p>
    </Panel>
    <Panel labelledBy="close-account-heading">
      <h3 id="close-account-heading">Close your account</h3>
      <p>This immediately disables sign-in, signs out all devices and removes your active project access. Editable profile details and your recovery email are removed. Shared work, historical attribution and immutable audit evidence remain. Download your information first if you need a copy.</p>
      {data.owned_projects.length > 0 && <div className="notice"><p>Transfer ownership or archive these active projects before closing your account. A single-person project can be archived first:</p><ul>{data.owned_projects.map((project) => <li key={project.project_id}>{project.project__name}</li>)}</ul></div>}
      <form className="form-stack" onSubmit={(event) => { event.preventDefault(); run({ type: "close", confirmation }); }}>
        <Field label="Type CLOSE MY ACCOUNT"><input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="off" required /></Field>
        <Button type="submit" variant="danger" disabled={!verified || busy || data.owned_projects.length > 0 || confirmation !== "CLOSE MY ACCOUNT"}>Close my account</Button>
      </form>
    </Panel>
  </div>;
}

export default function AccountSecurityPage() {
  const summary = useQuery({ queryKey: ["account-security"], queryFn: accountReadinessApi.summary });
  if (summary.isLoading) return <Loading label="Loading account security…" />;
  if (summary.error || !summary.data) return <ErrorState error={summary.error} retry={() => void summary.refetch()} />;
  return <SecurityContent data={summary.data} />;
}
