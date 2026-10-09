import { Button } from "./UI";

export interface PageInfo { page?: number; pages?: number; total?: number; page_size?: number }

export default function ListPagination({ info, page, onChange, label }: { info?: PageInfo; page: number; onChange: (value: number) => void; label: string }) {
  if (!info?.pages || info.pages <= 1) return null;
  const current = info.page ?? page;
  return <nav className="launch-row" aria-label={`${label} pages`}><Button variant="secondary" disabled={current <= 1} onClick={() => onChange(current - 1)}>Previous</Button><span>Page {current} of {info.pages} · {info.total} records</span><Button variant="secondary" disabled={current >= info.pages} onClick={() => onChange(current + 1)}>Next</Button></nav>;
}
