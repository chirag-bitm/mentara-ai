import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Mentara AI — Live Transcription",
  description: "Real-time conversation intelligence, beginning with reliable streaming speech-to-text.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

