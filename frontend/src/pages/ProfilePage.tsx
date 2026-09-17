import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { accountApi } from "../api/resources";
import { errorMessage } from "../api/client";
import { Button, ErrorState, Field, Loading, Panel } from "../components/UI";

const commonZones = ["Australia/Sydney", "Australia/Melbourne", "Australia/Brisbane", "Australia/Adelaide", "Australia/Perth", "Pacific/Auckland", "Asia/Singapore", "UTC"];

export default function ProfilePage() {
  const client = useQueryClient();
  const [message, setMessage] = useState("");
  const me = useQuery({ queryKey: ["me"], queryFn: accountApi.me });
  const update = useMutation({ mutationFn: accountApi.updateProfile, onSuccess: async (profile) => { document.documentElement.dataset.timeZone = profile.time_zone; await client.invalidateQueries({ queryKey: ["me"] }); setMessage("Profile saved."); } });
  if (me.isLoading) return <Loading label="Loading profile…" />;
  if (me.error || !me.data) return <ErrorState error={me.error} retry={() => void me.refetch()} />;
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setMessage(""); const data = new FormData(event.currentTarget);
    update.mutate({ display_name: String(data.get("display_name")), course_code: String(data.get("course_code")), time_zone: String(data.get("time_zone")), biography: String(data.get("biography")), avatar_url: String(data.get("avatar_url")) });
  };
  return <div className="page-stack"><div className="page-heading"><div><p className="eyebrow">Account</p><h2>Your profile</h2><p>These details help teammates recognise you. Your sign-in email is not editable here.</p></div></div>
    {(message || update.error) && <p className={update.error ? "notice notice--error" : "notice"} role={update.error ? "alert" : "status"}>{update.error ? errorMessage(update.error) : message}</p>}
    <Panel labelledBy="profile-heading"><h3 id="profile-heading">Profile details</h3><form className="form-grid" onSubmit={submit}>
      <Field label="Email"><input value={me.data.email} readOnly aria-readonly="true" /></Field>
      <Field label="Display name"><input name="display_name" required minLength={2} maxLength={80} defaultValue={me.data.profile.display_name} autoComplete="name" /></Field>
      <Field label="Course code"><input name="course_code" maxLength={20} defaultValue={me.data.profile.course_code} /></Field>
      <Field label="Time zone" hint="Use an IANA time zone, for example Australia/Sydney."><input name="time_zone" required list="time-zones" defaultValue={me.data.profile.time_zone} /><datalist id="time-zones">{commonZones.map((zone) => <option key={zone} value={zone} />)}</datalist></Field>
      <Field label="Avatar URL"><input name="avatar_url" type="url" maxLength={2048} defaultValue={me.data.profile.avatar_url} autoComplete="url" /></Field>
      <Field label="Short biography"><textarea name="biography" rows={5} maxLength={500} defaultValue={me.data.profile.biography} /></Field>
      <div className="form-actions"><Button type="submit" disabled={update.isPending}>{update.isPending ? "Saving…" : "Save profile"}</Button><a className="button button--secondary" href="/account/password/">Change password</a></div>
    </form></Panel>
  </div>;
}
