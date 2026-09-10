import type { Analysis } from "./types";

type Context = {
  registerTool: (
    tool: {
      name: string;
      description: string;
      inputSchema: object;
      annotations: object;
      execute: (input: unknown) => unknown;
    },
    options: { signal: AbortSignal },
  ) => void | Promise<void>;
};

export function registerAnalysisReader(
  read: () => Analysis | null,
): () => void {
  const context = (document as Document & { modelContext?: Context })
    .modelContext;
  if (!context?.registerTool) return () => {};
  const lifecycle = new AbortController();
  try {
    void Promise.resolve(
      context.registerTool(
        {
          name: "read_solarfit_analysis",
          description:
            "Read the completed roof analysis, including capacity, coverage limitations and uncertainty. Does not initiate analysis.",
          inputSchema: {
            type: "object",
            properties: {},
            additionalProperties: false,
          },
          annotations: { readOnlyHint: true, untrustedContentHint: true },
          execute(input) {
            if (
              !input ||
              typeof input !== "object" ||
              Array.isArray(input) ||
              Object.keys(input).length
            )
              throw Error("Expected an empty object.");
            const result = read();
            if (!result)
              throw Error(
                "No completed analysis. Upload, trace and analyse a roof in the interface first.",
              );
            return {
              mode: result.mode,
              statistics: result.statistics,
              confidence: result.confidence,
              warnings: result.warnings,
            };
          },
        },
        { signal: lifecycle.signal },
      ),
    ).catch(() => {});
  } catch {
    /* Unsupported experimental implementations do not affect the app. */
  }
  return () => lifecycle.abort();
}
