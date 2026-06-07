import { AppShell } from "@/components/layout/AppShell";

/*
 * The HeartTwin Lab console. This page is the app shell entry point: it renders
 * the AppShell (a "use client" leaf that composes every domain panel and wires
 * the trace stream + store). Marketing copy lives nowhere here — this is a tool.
 */
export default function Home() {
  return <AppShell />;
}
