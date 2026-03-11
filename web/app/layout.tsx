import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Fauna Photo-ID",
  description: "Wildlife camera trap species identification tool",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-background antialiased">{children}</body>
    </html>
  );
}
