import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/http.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { api } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);

test("API handles actual server/proxy error formats without JSON syntax errors", async () => {
  const original = globalThis.fetch;
  try {
    for (const body of ["Internal Server Error", "<html>Bad gateway</html>"]) {
      globalThis.fetch = async () => new Response(body, { status: 500 });
      await assert.rejects(api("/api/map/prepare"), /could not complete this request/);
    }
    globalThis.fetch = async () => Response.json({ detail: "Map capture expired. Select the building again." }, { status: 410 });
    await assert.rejects(api("/api/map/shadow/old"), /capture expired/);
    globalThis.fetch = async () => new Response("Not Found", { status: 404 });
    await assert.rejects(api("/api/map/shadow/old"), /backend is outdated/);
    globalThis.fetch = async () => Response.json({ detail: "Not Found" }, { status: 404 });
    await assert.rejects(api("/api/map/shadow/old"), /backend is outdated/);
    globalThis.fetch = async () => new Response("<html>proxy page</html>", { status: 200 });
    await assert.rejects(api("/api/map/prepare"), /unexpected server response/);
    globalThis.fetch = async (_, init) => {
      assert.equal(init.headers.get("ngrok-skip-browser-warning"), "solarfit");
      return Response.json({ capture_id: "fresh" });
    };
    assert.deepEqual(await (await api("/api/map/prepare")).json(), { capture_id: "fresh" });
  } finally { globalThis.fetch = original; }
});
