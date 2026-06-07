import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { CopilotProvider } from "@/components/copilot/CopilotProvider";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "HeartTwin Lab",
  description:
    "Multi-agent cardiac digital twin console for WeaveHacks 4. Educational simulation only, not for diagnosis or treatment decisions.",
  applicationName: "HeartTwin Lab",
  keywords: [
    "HeartTwin Lab",
    "WeaveHacks",
    "CopilotKit",
    "Weave",
    "Redis",
    "cardiac simulation",
    "agent trace",
  ],
};

export const viewport: Viewport = {
  themeColor: "#0c111c",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
        <CopilotProvider>{children}</CopilotProvider>
      </body>
    </html>
  );
}
