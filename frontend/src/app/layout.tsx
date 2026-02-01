import type { Metadata } from "next";
import "./globals.css";
import { Shell } from "./_components/Shell";

export const metadata: Metadata = {
  title: "OpenClaw Agency — Mission Control",
  description: "Company OS for projects, departments, people, and HR.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
