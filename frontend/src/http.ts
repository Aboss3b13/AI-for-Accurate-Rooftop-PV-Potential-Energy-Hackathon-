/**
 * Same-origin fetch that survives an ngrok tunnel.
 *
 * ngrok's free tier serves a browser interstitial before the real response
 * until the visitor clicks through. That page is HTML, so any API call made
 * before the click comes back as HTML and fails to parse. The header below
 * opts every request out of it; off a tunnel it is simply ignored.
 */
export async function api(input: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  headers.set("ngrok-skip-browser-warning", "solarfit");
  const response = await fetch(input, { ...init, headers });
  if (!response.ok) {
    let detail: unknown;
    try { detail = (await response.clone().json()).detail; } catch { /* Proxies and server crashes may return plain text or HTML. */ }
    const fallback = response.status === 404 && input.includes("/shadow/")
      ? "The running SolarFit backend is outdated. Restart SolarFit and select the roof again."
      : response.status >= 500
        ? "SolarFit could not complete this request. Retry or select the roof again. If it continues, check the server log."
        : `Request failed (${response.status}). Please retry.`;
    throw new Error(response.status === 404 && input.includes("/shadow/")
      ? fallback : typeof detail === "string" ? detail : fallback);
  }
  if (input.startsWith("/api/") && !response.headers.get("content-type")?.includes("application/json")) {
    throw new Error("SolarFit received an unexpected server response. Restart SolarFit and reload the page.");
  }
  return response;
}
