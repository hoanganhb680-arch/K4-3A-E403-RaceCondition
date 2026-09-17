import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "VLearn Tutor CP3",
  description: "Question clustering and teacher-attention dashboard",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

