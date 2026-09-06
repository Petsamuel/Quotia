// Cloudflare Workers entrypoint. This Worker does not serve the site itself — it
// forwards every request into a container running the FastAPI app (uvicorn on
// 7860, see the Dockerfile). Static files, HTML pages and the /v1 API all come
// from FastAPI, so there is deliberately no `assets` binding here: an assets
// directory would shadow the app and re-publish the repo as downloadable files.
import { Container, getContainer } from "@cloudflare/containers";

export class QuotiaContainer extends Container {
  // Must match the port uvicorn binds in the Dockerfile CMD.
  defaultPort = 7860;

  // Idle containers are stopped and cold-start on the next request. The word
  // bank is baked into the image at build time, so a cold start is just uvicorn
  // booting rather than a SQLite rebuild.
  sleepAfter = "10m";

  // main.py falls back to the request origin when this is unset, which is fine
  // locally but wrong behind Cloudflare — canonical tags, Open Graph URLs,
  // sitemap.xml and llms.txt would all point at the internal container address.
  envVars = {
    QUOTIA_BASE_URL: "https://quotia.petsamuel4.workers.dev",
  };
}

export default {
  async fetch(request, env) {
    // No id argument: all traffic lands on one shared instance, so the in-memory
    // FastAPICache and the quote cache actually get hits.
    return getContainer(env.QUOTIA_CONTAINER).fetch(request);
  },
};
