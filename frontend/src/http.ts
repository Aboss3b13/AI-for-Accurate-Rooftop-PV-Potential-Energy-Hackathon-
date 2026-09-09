/**
 * Same-origin fetch that survives an ngrok tunnel.
 *
 * ngrok's free tier serves a browser interstitial before the real response
 * until the visitor clicks through. That page is HTML, so any API call made
 * before the click comes back as HTML and fails to parse. The header below
 * opts every request out of it; off a tunnel it is simply ignored.
 */
export function api(input: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  headers.set("ngrok-skip-browser-warning", "solarfit");
  return fetch(input, { ...init, headers });
}
