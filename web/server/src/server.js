import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import fastifyStatic from "@fastify/static";
import Fastify from "fastify";

const here = path.dirname(fileURLToPath(import.meta.url));
const serverRoot = path.resolve(here, "..");
const uiDist = path.resolve(serverRoot, "..", "ui", "dist");

const apiOrigin = (process.env.PY_API || "http://127.0.0.1:8000").replace(/\/$/, "");
const apiToken = process.env.FXDESK_WEB_TOKEN || "";
const port = Number(process.env.PORT || 3000);
const host = process.env.HOST || "127.0.0.1";

const app = Fastify({
  logger: { level: process.env.LOG_LEVEL || "info" },
  bodyLimit: 10 * 1024 * 1024,
});

app.get("/healthz", async () => ({ status: "ok", api: apiOrigin }));

app.all("/api/*", async (request, reply) => {
  const target = `${apiOrigin}${request.raw.url}`;
  const headers = { ...request.headers };
  delete headers.host;
  delete headers.connection;
  delete headers["content-length"];
  delete headers["accept-encoding"];

  if (apiToken) {
    headers["x-api-key"] = apiToken;
  }

  const init = { method: request.method, headers };

  if (
    request.method !== "GET" &&
    request.method !== "HEAD" &&
    request.body !== undefined &&
    request.body !== null
  ) {
    init.body = JSON.stringify(request.body);
    headers["content-type"] = "application/json";
  }

  let upstream;
  try {
    upstream = await fetch(target, init);
  } catch (error) {
    request.log.error({ err: error }, "fxdesk API request failed");
    return reply
      .code(502)
      .send({ detail: `fxdesk API unavailable: ${error.message}` });
  }

  reply.code(upstream.status);
  const contentType = upstream.headers.get("content-type");
  if (contentType) {
    reply.header("content-type", contentType);
  }
  const cacheControl = upstream.headers.get("cache-control");
  if (cacheControl) {
    reply.header("cache-control", cacheControl);
  }

  const buffer = Buffer.from(await upstream.arrayBuffer());
  return reply.send(buffer);
});

if (existsSync(uiDist)) {
  app.register(fastifyStatic, {
    root: uiDist,
    prefix: "/",
    wildcard: false,
  });

  app.setNotFoundHandler((request, reply) => {
    if (request.raw.url.startsWith("/api")) {
      return reply.code(404).send({ detail: "not found" });
    }
    return reply.sendFile("index.html");
  });
} else {
  app.get("/", async () => ({
    service: "fxdesk-web",
    message:
      "UI is not built. Run `npm run ui:build` here, or use the Vite dev server (`npm run ui:dev`).",
    api: apiOrigin,
  }));
}

app
  .listen({ port, host })
  .then(() => {
    app.log.info(`fxdesk web listening on http://${host}:${port} -> ${apiOrigin}`);
  })
  .catch((error) => {
    app.log.error(error);
    process.exit(1);
  });
