// The REAL import allow-list (the regex lint is only a pre-filter). A webpack
// resolve hook that THROWS when the AI-authored entry file tries to import
// anything outside remotion / @remotion/* / react. Imports made by libraries
// themselves (issuer inside node_modules) are left alone — only the composition's
// own imports are constrained.
import path from "node:path";

const ALLOWED_EXACT = new Set([
  "remotion",
  "react",
  "react/jsx-runtime",
  "react/jsx-dev-runtime",
]);

export function isAllowedFromEntry(request: string): boolean {
  if (!request) return false;
  if (ALLOWED_EXACT.has(request)) return true;
  if (request.startsWith("@remotion/")) return true;
  if (request.startsWith("react/")) return true;
  return false;
}

// A `webpackOverride` for @remotion/bundler: throws at bundle time if the entry
// file imports a disallowed module. `entryAbsPath` is the absolute path of the AI
// composition we are bundling.
export function makeImportGuardOverride(entryAbsPath: string) {
  const entry = path.resolve(entryAbsPath);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (config: any) => {
    config.plugins = config.plugins || [];
    config.plugins.push({
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      apply(compiler: any) {
        compiler.hooks.normalModuleFactory.tap("AiImportGuard", (nmf: any) => {
          nmf.hooks.beforeResolve.tap("AiImportGuard", (data: any) => {
            const issuerRaw = data?.contextInfo?.issuer ?? data?.context ?? "";
            const issuer = issuerRaw ? path.resolve(issuerRaw) : "";
            const request: string = data?.request ?? "";
            if (issuer === entry && !isAllowedFromEntry(request)) {
              throw new Error(
                `[import-guard] composition imported '${request}', which is not allowed ` +
                  `(only remotion, @remotion/*, react).`,
              );
            }
          });
        });
      },
    });
    return config;
  };
}
