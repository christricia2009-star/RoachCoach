import "./globals.css";
import AppShell from "./components/AppShell";

export const metadata = {
  title: "Roach Coach Radar",
  description: "Find food trucks nearby — no check-in required.",
};

export const viewport = {
  themeColor: "#EA7A25",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
