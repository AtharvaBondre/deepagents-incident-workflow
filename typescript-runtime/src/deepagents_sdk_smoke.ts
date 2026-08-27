#!/usr/bin/env node
/** No-cost smoke of the pinned TypeScript SDK and exact bounded tool surface. */

import dns from "node:dns";
import dnsPromises from "node:dns/promises";
import * as fsPromises from "node:fs/promises";
import { syncBuiltinESMExports } from "node:module";
import * as net from "node:net";
import * as os from "node:os";
import * as path from "node:path";
import { pathToFileURL } from "node:url";

type JsonObject = Record<string, unknown>;
const EXPECTED_NODE_VERSION = "22.23.2";

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function contentText(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function toolResults(result: unknown): Map<string, string> {
  const values = new Map<string, string>();
  if (!isObject(result) || !Array.isArray(result.messages)) return values;
  for (const message of result.messages) {
    if (!isObject(message)) continue;
    const rawId = message.tool_call_id ?? message.toolCallId;
    if (typeof rawId === "string") {
      values.set(rawId, contentText(message.content));
    }
  }
  return values;
}

function finalResponsePresent(result: unknown): boolean {
  if (!isObject(result) || !Array.isArray(result.messages) || result.messages.length === 0) {
    return false;
  }
  const last = result.messages[result.messages.length - 1];
  return isObject(last) && contentText(last.content).length > 0;
}

const DNS_METHODS = [
  "lookup",
  "lookupService",
  "resolve",
  "resolve4",
  "resolve6",
  "resolveAny",
  "resolveCaa",
  "resolveCname",
  "resolveMx",
  "resolveNaptr",
  "resolveNs",
  "resolvePtr",
  "resolveSoa",
  "resolveSrv",
  "resolveTxt",
  "reverse",
] as const;

function installNetworkDeny(attempts: string[]): () => void {
  const originalFetch = globalThis.fetch;
  const originalConnect = net.Socket.prototype.connect;
  const restores: Array<() => void> = [];
  const deny = (kind: string): never => {
    attempts.push(kind);
    throw new Error("network access is disabled during the TypeScript SDK smoke");
  };
  const patchMethods = (target: object, prefix: string): void => {
    const mutable = target as Record<string, unknown>;
    for (const method of DNS_METHODS) {
      const original = mutable[method];
      if (typeof original !== "function") continue;
      mutable[method] = (..._args: unknown[]) => deny(`${prefix}.${method}`);
      restores.push(() => {
        mutable[method] = original;
      });
    }
  };
  globalThis.fetch = ((..._args: Parameters<typeof fetch>) => deny("fetch")) as typeof fetch;
  net.Socket.prototype.connect = function (..._args: unknown[]): net.Socket {
    return deny("socket.connect");
  } as typeof net.Socket.prototype.connect;
  patchMethods(dns, "dns");
  patchMethods(dns.Resolver.prototype, "dns.Resolver");
  patchMethods(dnsPromises, "dns.promises");
  patchMethods(dnsPromises.Resolver.prototype, "dns.promises.Resolver");
  syncBuiltinESMExports();
  return () => {
    for (const restore of restores.reverse()) restore();
    globalThis.fetch = originalFetch;
    net.Socket.prototype.connect = originalConnect;
    syncBuiltinESMExports();
  };
}

async function assertOsNetworkDisabled(): Promise<void> {
  const failures: string[] = [];
  try {
    await dnsPromises.lookup("docs.langchain.com");
    failures.push("DNS resolution unexpectedly succeeded");
  } catch {
    // Expected under the container's network-none boundary.
  }
  await new Promise<void>((resolve) => {
    const socket = net.createConnection({ host: "1.1.1.1", port: 443 });
    socket.setTimeout(1000);
    socket.once("connect", () => {
      failures.push("external socket connection unexpectedly succeeded");
      socket.destroy();
      resolve();
    });
    socket.once("error", () => resolve());
    socket.once("timeout", () => {
      socket.destroy();
      resolve();
    });
  });
  if (failures.length > 0) throw new Error(failures.join("; "));
}

async function scriptedModel() {
  const [{ AIMessage }, { fakeModel }] = await Promise.all([
    import("@langchain/core/messages"),
    import("@langchain/core/testing"),
  ]);
  const scripted = fakeModel();
  const calls = [
    {
      name: "write_file",
      id: "write-forbidden-smoke",
      args: { file_path: "/tests/forbidden.txt", content: "must-not-exist\n" },
    },
    {
      name: "write_file",
      id: "write-traversal-smoke",
      args: { file_path: "/../escape-write.txt", content: "must-not-escape\n" },
    },
    {
      name: "read_file",
      id: "read-traversal-smoke",
      args: { file_path: "/../outside-secret.txt" },
    },
    {
      name: "read_file",
      id: "read-smoke",
      args: { file_path: "/app/value.txt" },
    },
    {
      name: "edit_file",
      id: "edit-smoke",
      args: {
        file_path: "/app/value.txt",
        old_string: "before\n",
        new_string: "after\n",
      },
    },
  ];
  for (const call of calls) scripted.respondWithTools([call]);
  scripted.respond(new AIMessage("Candidate edit prepared; controller verification required."));
  Object.defineProperty(scripted, "getName", {
    configurable: false,
    value: () => "ChatOpenAI",
    writable: false,
  });
  return scripted;
}

export async function runSmoke(options: {
  output?: string;
  assertOsNetworkDisabled?: boolean;
} = {}): Promise<JsonObject> {
  if (process.versions.node !== EXPECTED_NODE_VERSION) {
    throw new Error(`Node ${EXPECTED_NODE_VERSION} is required; found ${process.versions.node}`);
  }
  if (options.assertOsNetworkDisabled) await assertOsNetworkDisabled();
  const temporary = await fsPromises.mkdtemp(path.join(os.tmpdir(), "daiw-typescript-sdk-smoke-"));
  const workspace = path.join(temporary, "workspace");
  const target = path.join(workspace, "app", "value.txt");
  const forbiddenTarget = path.join(workspace, "tests", "forbidden.txt");
  const escapedTarget = path.join(temporary, "escape-write.txt");
  const outsideSecret = path.join(temporary, "outside-secret.txt");
  const outsideCanary = "DAIW_TYPESCRIPT_OUTSIDE_READ_CANARY";
  const networkAttempts: string[] = [];
  const restoreNetwork = installNetworkDeny(networkAttempts);
  try {
    // The guard is deliberately active before either the worker or SDK module
    // graph is evaluated. Any import-time fetch, socket, or DNS request fails
    // closed and is counted in this controller-validated smoke record.
    const worker = await import("./deepagents_worker.js");
    if (worker.EXPECTED_NODE_VERSION !== EXPECTED_NODE_VERSION) {
      throw new Error("worker and smoke Node version policy diverged");
    }
    await fsPromises.mkdir(path.dirname(target), { recursive: true });
    await fsPromises.writeFile(target, "before\n", "utf8");
    await fsPromises.writeFile(outsideSecret, `${outsideCanary}\n`, "utf8");
    const model = await scriptedModel();
    const bounded = await worker.buildBoundedAgent({
      model,
      profileKey: "openai",
      workspace,
      packet: {
        schema_version: 1,
        policy: { controller_is_sole_acceptor: true, allowed_paths: ["app/"] },
      },
    });
    const result = await bounded.agent.invoke(
      { messages: [{ role: "user", content: "Apply the scripted edit." }] },
      { recursionLimit: 24 },
    );
    const results = toolResults(result);
    const traversalWriteOutput = (results.get("write-traversal-smoke") ?? "").toLowerCase();
    const traversalReadOutput = results.get("read-traversal-smoke") ?? "";
    const exactTools = bounded.observedTools();
    const forbiddenAbsent = worker.FORBIDDEN_TOOLS.every((name) => !exactTools.includes(name));
    const workspaceEditSucceeded = (await fsPromises.readFile(target, "utf8")) === "after\n";
    const outOfScopeWriteDenied = !(await fsPromises
      .lstat(forbiddenTarget)
      .then(() => true)
      .catch(() => false));
    const traversalWriteDenied =
      !(await fsPromises
        .lstat(escapedTarget)
        .then(() => true)
        .catch(() => false)) &&
      ["denied", "not allowed", "error", "outside"].some((marker) =>
        traversalWriteOutput.includes(marker),
      );
    const traversalReadDenied =
      !traversalReadOutput.includes(outsideCanary) &&
      ["denied", "not allowed", "error", "outside"].some((marker) =>
        traversalReadOutput.toLowerCase().includes(marker),
      );
    const hasFinalResponse = finalResponsePresent(result);
    const passed =
      workspaceEditSucceeded &&
      outOfScopeWriteDenied &&
      traversalWriteDenied &&
      traversalReadDenied &&
      JSON.stringify(exactTools) === JSON.stringify([...worker.ALLOWED_TOOLS].sort()) &&
      forbiddenAbsent &&
      hasFinalResponse &&
      networkAttempts.length === 0;
    const record: JsonObject = {
      schema_version: 1,
      at: new Date().toISOString(),
      runtime: "deepagents",
      sdk_language: "typescript",
      runtime_version: worker.EXPECTED_DEEPAGENTS_VERSION,
      node_version: process.versions.node,
      model: "openai:scripted-smoke (scripted, no transport)",
      profile_provider: "openai",
      model_transport: "scripted-no-transport",
      network_request_made: networkAttempts.length > 0,
      network_attempts: networkAttempts.length,
      observed_tools: exactTools,
      forbidden_tools_absent: forbiddenAbsent,
      workspace_edit_succeeded: workspaceEditSucceeded,
      out_of_scope_write_denied: outOfScopeWriteDenied,
      traversal_write_denied: traversalWriteDenied,
      traversal_read_denied: traversalReadDenied,
      final_response_present: hasFinalResponse,
      passed,
    };
    if (options.output) {
      await fsPromises.writeFile(options.output, `${JSON.stringify(record, null, 2)}\n`, {
        encoding: "utf8",
        flag: "wx",
        // The network-none container runs as UID 65532 while the host-side
        // controller validates this synthetic record under its own UID. The
        // parent temporary directory remains private; the record must be
        // host-readable across that UID boundary.
        mode: 0o644,
      });
    }
    return record;
  } finally {
    restoreNetwork();
    await fsPromises.rm(temporary, { recursive: true, force: true });
  }
}

function parseArguments(argv: string[]): { output?: string; assertOsNetworkDisabled: boolean } {
  let output: string | undefined;
  let assertNetwork = false;
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--assert-os-network-disabled") {
      assertNetwork = true;
    } else if (value === "--output" && index + 1 < argv.length) {
      output = argv[index + 1];
      index += 1;
    } else {
      throw new Error(`unsupported argument: ${String(value)}`);
    }
  }
  return output === undefined
    ? { assertOsNetworkDisabled: assertNetwork }
    : { output, assertOsNetworkDisabled: assertNetwork };
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : "";
if (import.meta.url === invokedPath) {
  runSmoke(parseArguments(process.argv.slice(2)))
    .then((record) => {
      process.stdout.write(`${JSON.stringify(record, null, 2)}\n`);
      if (record.passed !== true) process.exitCode = 1;
    })
    .catch((error: unknown) => {
      process.stderr.write(`${error instanceof Error ? error.message : "smoke failed"}\n`);
      process.exitCode = 1;
    });
}
