import type { TaskPriority, TaskStatus } from "../api/types";

const statusColours: Record<TaskStatus, string> = {
  todo: "#4f73df", in_progress: "#bd8314", blocked: "#bc4455", done: "#27866f",
};
const priorityColours: Record<TaskPriority, string> = {
  low: "#748399", medium: "#bd8314", high: "#db7732", urgent: "#bc4455",
};
const assigneeColours = ["#4f73df", "#27866f", "#9e60ce", "#db7732", "#3155b2", "#26969c"];

export function distributionColour(key: string, kind: "status" | "priority" | "assignee") {
  if (kind === "status" && key in statusColours) return statusColours[key as TaskStatus];
  if (kind === "priority" && key in priorityColours) return priorityColours[key as TaskPriority];
  if (key === "unassigned") return "#748399";
  // Member colours remain stable when the response order or counts change.
  const hash = [...key].reduce((value, character) => (value * 31 + character.charCodeAt(0)) >>> 0, 0);
  return assigneeColours[hash % assigneeColours.length];
}

export function countAxisTicks(maximum: number): number[] {
  const upper = Math.max(1, Math.ceil(maximum));
  return [...new Set([0, Math.ceil(upper / 2), upper])];
}

export function cycleAxisScale(maximumHours: number) {
  if (maximumHours > 0 && maximumHours < 1 / 60) return { multiplier: 3600, suffix: "s", label: "seconds" };
  if (maximumHours < 1) return { multiplier: 60, suffix: "min", label: "minutes" };
  return { multiplier: 1, suffix: "h", label: "hours" };
}

export function formatCycleNumber(value: number): string {
  return new Intl.NumberFormat("en-GB", { maximumSignificantDigits: 3 }).format(value);
}

export function formatCycleDuration(hours: number): string {
  const scale = cycleAxisScale(hours);
  return `${formatCycleNumber(hours * scale.multiplier)} ${scale.label}`;
}
