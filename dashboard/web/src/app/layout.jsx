import "./globals.css";

export const metadata = {
  title: "Hyperion",
  description: "Agent action ledger, rollback, and audit.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
