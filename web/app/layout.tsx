import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { CopilotProvider } from "@/components/copilot/CopilotProvider";

// One typeface for the whole console — Inter, tuned for on-screen readability.
const inter = Inter({
  variable: "--font-ui",
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
  themeColor: "#f5f6f8",
  colorScheme: "light",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={inter.variable}>
      <body>
        <CopilotProvider>{children}</CopilotProvider>
      </body>
    </html>
  );
}
