"use client";

import { useState } from "react";
import { avatarCandidates } from "../lib/trucks";

function Glyph({ className }) {
  return (
    <span className={className} aria-hidden="true">
      <svg viewBox="0 0 24 24">
        <path
          fill="currentColor"
          d="M3 7.5A1.5 1.5 0 0 1 4.5 6h9A1.5 1.5 0 0 1 15 7.5V9h2.2c.5 0 .96.24 1.25.64l1.9 2.6c.2.27.3.6.3.94V16a1.5 1.5 0 0 1-1.5 1.5h-.6a2.5 2.5 0 0 1-4.8 0h-4.4a2.5 2.5 0 0 1-4.8 0H3.5A1.5 1.5 0 0 1 2 16V7.5H3Z"
        />
      </svg>
    </span>
  );
}

export default function TruckThumb({ truck, className = "rc-thumb" }) {
  const candidates = avatarCandidates(truck);
  const [index, setIndex] = useState(0);
  const src = candidates[index];

  if (!src) {
    return <Glyph className={`${className} rc-thumb--fallback`} />;
  }

  return (
    <img
      className={className}
      src={src}
      alt=""
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setIndex((i) => i + 1)}
    />
  );
}
