import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Dashboard Agent",
  description: "Create a dashboard through a guided local conversation.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
