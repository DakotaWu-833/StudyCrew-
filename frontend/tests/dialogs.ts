import { act } from "react";

export async function openCreation(label: string) {
  const trigger = [...document.body.querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent?.trim() === label);
  if (!trigger) throw new Error(`Missing creation trigger: ${label}`);
  await act(async () => { trigger.focus(); trigger.click(); });
}
