import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "미국 전력망 관측소",
  description: "미국 권역별 부하·발전 믹스·접속 대기열과 단계별 병목 모니터링",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body className="antialiased">{children}</body>
    </html>
  );
}
