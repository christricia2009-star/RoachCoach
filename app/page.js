"use client";

import { useState } from "react";

export default function Home() {
  const [status, setStatus] = useState("Ready");
  const [data, setData] = useState(null);

  async function check() {
    setStatus("Checking…");
    try {
      const res = await fetch("/api/health", { cache: "no-store" });
      const json = await res.json();
      setData(json);
      setStatus(res.ok ? "🟢 RADAR BACKEND ONLINE" : "🔴 BACKEND ERROR");
    } catch (error) {
      setData(null);
      setStatus("🔴 Unable to reach Radar backend");
    }
  }

  return (
    <main className="shell">
      <section className="hero">
        <div className="eyebrow">RCR • 27.515</div>
        <h1>🪳 Roach Coach Radar</h1>
        <p>Live food-truck intelligence command center.</p>
        <div className="status">{status}</div>
        <button onClick={check}>Test Radar Connection</button>
      </section>

      <section className="grid">
        <article><span>ENGINE</span><strong>27.515</strong><small>Evidence → Prediction → Learning</small></article>
        <article><span>API</span><strong>/api</strong><small>FastAPI on Vercel</small></article>
        <article><span>DATA</span><strong>LIVE</strong><small>Configured sources only</small></article>
      </section>

      {data && <pre>{JSON.stringify(data, null, 2)}</pre>}

      <footer>
        Deploy this repository to Vercel. API secrets belong in Vercel Environment
        Variables, never in GitHub.
      </footer>
    </main>
  );
}
