import {
  CopilotRuntime,
  copilotKitEndpoint,
  copilotRuntimeNextJSAppRouterEndpoint,
  OpenAIAdapter,
} from "@copilotkit/runtime";
import OpenAI from "openai";

export const runtime = "nodejs";
// This route reaches OpenAI + the backend at request time; never prerender or
// evaluate it during the build (where OPENAI_API_KEY is absent).
export const dynamic = "force-dynamic";

const DEFAULT_API_BASE = "http://localhost:8000";
const ROUTE_PATH = "/api/copilotkit";

function backendOriginFrom(value: string | undefined) {
  if (!value) {
    return undefined;
  }

  try {
    const url = new URL(value);

    if (url.pathname === "/" || url.pathname === "") {
      return url.origin;
    }

    const pathname = url.pathname.replace(/\/$/, "");
    if (pathname === "/api/v1") {
      return url.origin;
    }

    url.pathname = pathname;
    url.search = "";
    url.hash = "";
    return url.toString().replace(/\/$/, "");
  } catch {
    return value.replace(/\/$/, "");
  }
}

const apiBase =
  backendOriginFrom(process.env.API_BASE) ??
  backendOriginFrom(process.env.NEXT_PUBLIC_API_BASE) ??
  DEFAULT_API_BASE;

const copilotRuntime = new CopilotRuntime({
  remoteEndpoints: [
    copilotKitEndpoint({
      url: `${apiBase}/copilotkit`,
    }),
  ],
});

// Build the request handler lazily and memoize it. The OpenAI client must not
// be constructed at module load time: `next build` evaluates this module while
// collecting page data, when OPENAI_API_KEY is absent, and the OpenAI
// constructor throws on a missing key. Deferring to the first request keeps the
// build clean while still failing loud at request time if the key is missing.
type RouteHandler = ReturnType<
  typeof copilotRuntimeNextJSAppRouterEndpoint
>["handleRequest"];

let cachedHandler: RouteHandler | undefined;

function getHandler(): RouteHandler {
  if (!cachedHandler) {
    // The LLM that powers the chat. The remote Python endpoint contributes the
    // HeartTwin actions (create_case/extract/operate/simulate_recovery/...);
    // this adapter is the reasoning brain that drives the conversation and
    // calls them.
    const serviceAdapter = new OpenAIAdapter({
      openai: new OpenAI({ apiKey: process.env.OPENAI_API_KEY }),
      model: process.env.OPENAI_MODEL ?? "gpt-4o",
    });

    cachedHandler = copilotRuntimeNextJSAppRouterEndpoint({
      runtime: copilotRuntime,
      serviceAdapter,
      endpoint: ROUTE_PATH,
    }).handleRequest;
  }
  return cachedHandler;
}

export const GET: RouteHandler = (req) => getHandler()(req);
export const POST: RouteHandler = (req) => getHandler()(req);
export const OPTIONS: RouteHandler = (req) => getHandler()(req);
