"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function AppShell({ children }) {
  const pathname = usePathname() || "/";
  const onMap = pathname === "/" || pathname.startsWith("/radar");
  const onFleet = pathname.startsWith("/fleet");
  const onTruck = pathname.startsWith("/trucks");

  return (
    <div className={`rc-site${onMap ? " rc-site--map" : ""}`}>
      <header className="rc-hud-nav">
        <Link href="/" className="rc-brand">
          <span className="rc-brand__mark" aria-hidden="true" />
          <span>
            <em>Roach Coach</em>
            Radar
          </span>
        </Link>
        <nav>
          <Link href="/" className={onMap ? "is-on" : ""}>
            Live map
          </Link>
          <Link href="/fleet" className={onFleet ? "is-on" : ""}>
            Fleet
          </Link>
          {onTruck && (
            <Link href="/fleet" className="is-on">
              Truck
            </Link>
          )}
        </nav>
      </header>
      <main className="rc-site-main">{children}</main>
    </div>
  );
}
