import "./globals.css";

export const metadata = {
  title: "Roach Coach Radar",
  description: "Live food-truck intelligence dashboard",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
