"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

function TruckIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M3 7.5A1.5 1.5 0 0 1 4.5 6h9A1.5 1.5 0 0 1 15 7.5V9h2.2c.5 0 .96.24 1.25.64l1.9 2.6c.2.27.3.6.3.94V16a1.5 1.5 0 0 1-1.5 1.5h-.6a2.5 2.5 0 0 1-4.8 0h-4.4a2.5 2.5 0 0 1-4.8 0H3.5A1.5 1.5 0 0 1 2 16V7.5H3Zm2.5 10.2a1 1 0 1 0 0-2 1 1 0 0 0 0 2Zm11 0a1 1 0 1 0 0-2 1 1 0 0 0 0 2ZM15 11V8.2H5V15h.76a2.5 2.5 0 0 1 4.48 0h3.52a2.5 2.5 0 0 1 .24-.8ZM16.5 11h2.05l1.45 2H16.5v-2Z"
      />
    </svg>
  );
}

function RadarIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 3a9 9 0 1 0 8.94 8H19a7 7 0 1 1-7-7V3Zm0 4a5 5 0 1 0 4.9 4H14.9A3 3 0 1 1 12 9V7Zm1 4.2 4.6-4.6.7.7-3.7 3.7A2 2 0 1 1 13 11.2Z"
      />
    </svg>
  );
}

const TABS = [
  { href: "/", label: "Trucks", icon: TruckIcon, match: (path) => path === "/" || path.startsWith("/trucks") },
  { href: "/radar", label: "Radar", icon: RadarIcon, match: (path) => path.startsWith("/radar") },
];

export default function AppShell({ children }) {
  const pathname = usePathname() || "/";
  const isRadar = pathname.startsWith("/radar");
  const isTruck = pathname.startsWith("/trucks");
  const isOwner = pathname.includes("/owner");

  let title = "Trucks";
  if (isRadar) title = "Radar";
  else if (isOwner) title = "Orders";
  else if (isTruck) title = "Truck";

  return (
    <div className={`rc-app${isRadar ? " rc-app--radar" : ""}`}>
      <header className="rc-nav">
        <div className="rc-nav__row">
          {isTruck ? (
            <Link href="/" className="rc-nav__back">
              ‹ Trucks
            </Link>
          ) : (
            <span className="rc-nav__mark">Roach Coach</span>
          )}
          <span className="rc-nav__title">{title}</span>
          <span className="rc-nav__spacer" />
        </div>
      </header>
      <main className="rc-main">{children}</main>
      <nav className="rc-tabbar" aria-label="App">
        {TABS.map((tab) => {
          const active = tab.match(pathname);
          const Icon = tab.icon;
          return (
            <Link key={tab.href} href={tab.href} className={`rc-tab${active ? " rc-tab--active" : ""}`}>
              <Icon />
              {tab.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
