import { useState } from "react";

interface AvatarProps {
  name: string;
  imageUrl?: string;
  version?: string;
  className?: string;
}

function imageSource(imageUrl: string, version?: string) {
  if (!version) return imageUrl;
  const hashIndex = imageUrl.indexOf("#");
  const base = hashIndex === -1 ? imageUrl : imageUrl.slice(0, hashIndex);
  const hash = hashIndex === -1 ? "" : imageUrl.slice(hashIndex);
  const queryIndex = base.indexOf("?");
  const path = queryIndex === -1 ? base : base.slice(0, queryIndex);
  const parameters = new URLSearchParams(queryIndex === -1 ? "" : base.slice(queryIndex + 1));
  parameters.set("v", version);
  return `${path}?${parameters.toString()}${hash}`;
}

/** A decorative photo beside a visible name, with a resilient initials fallback. */
export default function Avatar({ name, imageUrl, version, className = "" }: AvatarProps) {
  const [failedSource, setFailedSource] = useState<string | null>(null);
  const trimmedUrl = imageUrl?.trim();
  const source = trimmedUrl ? imageSource(trimmedUrl, version) : "";
  const initial = name.trim().slice(0, 1).toUpperCase() || "?";

  return <span className={`avatar ${className}`.trim()} aria-hidden="true">
    {source && failedSource !== source
      ? <img key={source} src={source} alt="" loading="lazy" decoding="async" onError={() => setFailedSource(source)} />
      : initial}
  </span>;
}
