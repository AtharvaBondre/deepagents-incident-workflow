import * as assert from "node:assert/strict";
import dns from "node:dns";
import * as fsPromises from "node:fs/promises";
import * as net from "node:net";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";

import { AIMessage } from "@langchain/core/messages";
import { fakeModel } from "@langchain/core/testing";

import {
  ALLOWED_TOOLS,
  FORBIDDEN_TOOLS,
  buildBoundedAgent,
  buildProviderModel,
  installNetworkDeny,
  loadRequest,
  permissionSpecs,
  requireExactToolNames,
} from "./deepagents_worker.js";

function requestPacket(): Record<string, unknown> {
  return {
    schema_version: 1,
    run_id: "typescript-unit-test",
    attempt: 1,
    remaining_budget_seconds: 30,
    incident: {},
    evidence: {},
    feedback: [],
    policy: {
      allowed_paths: ["app/"],
      controller_is_sole_acceptor: true,
    },
    output_contract: {},
  };
}

function errorContains(value: unknown, expected: string, seen = new Set<unknown>()): boolean {
  if (value === null || value === undefined || seen.has(value)) return false;
  seen.add(value);
  if (value instanceof Error && value.message.includes(expected)) return true;
  if (typeof value !== "object") return false;
  const candidate = value as { cause?: unknown; errors?: unknown };
  if (errorContains(candidate.cause, expected, seen)) return true;
  return (
    Array.isArray(candidate.errors) &&
    candidate.errors.some((item) => errorContains(item, expected, seen))
  );
}

test("exports exactly the controller-approved filesystem tool names", () => {
  assert.deepEqual([...ALLOWED_TOOLS], [
    "ls",
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "grep",
  ]);
  assert.equal(FORBIDDEN_TOOLS.includes("delete"), true);
  assert.equal(FORBIDDEN_TOOLS.includes("execute"), true);
  assert.equal(FORBIDDEN_TOOLS.includes("task"), true);
  assert.equal(FORBIDDEN_TOOLS.includes("write_todos"), true);
});

test("rejects unnamed provider-side tools before a model request can be forwarded", () => {
  const tools: unknown[] = [
    ...ALLOWED_TOOLS.map((name) => ({ name })),
    { type: "web_search" },
  ];
  let forwarded = false;
  assert.throws(() => {
    requireExactToolNames(tools);
    forwarded = true;
  }, /unnamed or malformed tool/);
  assert.equal(forwarded, false);
});

test("rejects forbidden tool calls at the controller dispatch boundary", async () => {
  const temporary = await fsPromises.mkdtemp(path.join(os.tmpdir(), "daiw-ts-dispatch-test-"));
  const deleteCanary = path.join(temporary, "app", "delete-canary.txt");
  const executeCanary = path.join(temporary, "app", "execute-canary.txt");
  try {
    await fsPromises.mkdir(path.dirname(deleteCanary), { recursive: true });
    await fsPromises.writeFile(deleteCanary, "must-remain\n", "utf8");
    const args: Record<string, Record<string, unknown>> = {
      delete: { file_path: "/app/delete-canary.txt" },
      execute: { command: `touch ${JSON.stringify(executeCanary)}` },
      task: { description: "forbidden synthetic subagent dispatch" },
      write_todos: { todos: [] },
    };
    for (const toolName of ["execute", "delete", "task", "write_todos"] as const) {
      const model = fakeModel();
      model.respondWithTools([
        { name: toolName, id: `forbidden-${toolName}-dispatch`, args: args[toolName]! },
      ]);
      model.respond(new AIMessage("A forbidden dispatch unexpectedly returned."));
      Object.defineProperty(model, "getName", {
        configurable: false,
        value: () => "ChatOpenAI",
        writable: false,
      });
      const bounded = await buildBoundedAgent({
        model,
        profileKey: "openai",
        workspace: temporary,
        packet: requestPacket(),
      });
      await assert.rejects(
        async () =>
          bounded.agent.invoke(
            { messages: [{ role: "user", content: "Run the synthetic probe." }] },
            { recursionLimit: 8 },
          ),
        (error: unknown) => errorContains(error, `forbidden tool call: ${toolName}`),
      );
    }
    await assert.rejects(fsPromises.lstat(executeCanary), /ENOENT/);
    assert.equal(await fsPromises.readFile(deleteCanary, "utf8"), "must-remain\n");
  } finally {
    await fsPromises.rm(temporary, { recursive: true, force: true });
  }
});

test("uses first-match allow rules followed by deny-all rules", () => {
  assert.deepEqual(permissionSpecs(requestPacket()), [
    { operations: ["write"], paths: ["/app/**"], mode: "allow" },
    { operations: ["write"], paths: ["/**"], mode: "deny" },
    { operations: ["read"], paths: ["/**"], mode: "allow" },
    { operations: ["read"], paths: ["/**"], mode: "deny" },
  ]);
});

test("tagged model identifiers still resolve the mandatory provider safety profile", async () => {
  const temporary = await fsPromises.mkdtemp(path.join(os.tmpdir(), "daiw-ts-profile-test-"));
  try {
    const model = fakeModel();
    model.respond(new AIMessage("No edit required."));
    Object.defineProperty(model, "getName", {
      configurable: false,
      value: () => "ConfigurableModel",
      writable: false,
    });
    Object.defineProperty(model, "_defaultConfig", {
      configurable: false,
      value: { model: "llama3.2:latest", modelProvider: "ollama" },
      writable: false,
    });
    const bounded = await buildBoundedAgent({
      model,
      profileKey: "ollama",
      workspace: temporary,
      packet: requestPacket(),
    });
    await bounded.agent.invoke({ messages: [{ role: "user", content: "Inspect the workspace." }] });
    assert.deepEqual(bounded.observedTools(), [...ALLOWED_TOOLS].sort());
  } finally {
    await fsPromises.rm(temporary, { recursive: true, force: true });
  }
});

test("no-transport guard rejects fetch, socket, and DNS-only attempts", async () => {
  const attempts: string[] = [];
  const originalLookup = dns.lookup;
  const restore = installNetworkDeny(attempts);
  try {
    const [namedDns, namedDnsPromises] = await Promise.all([
      import("node:dns"),
      import("node:dns/promises"),
    ]);
    await assert.rejects(
      async () => globalThis.fetch("https://example.invalid"),
      /network access is disabled/,
    );
    assert.throws(
      () => new net.Socket().connect({ host: "127.0.0.1", port: 9 }),
      /network access is disabled/,
    );
    assert.throws(
      () => namedDns.lookup("example.invalid", () => undefined),
      /network access is disabled/,
    );
    await assert.rejects(
      async () => namedDnsPromises.resolve4("example.invalid"),
      /network access is disabled/,
    );
    const resolver = new namedDnsPromises.Resolver();
    await assert.rejects(
      async () => resolver.resolve4("example.invalid"),
      /network access is disabled/,
    );
    assert.deepEqual(attempts, [
      "fetch",
      "socket.connect",
      "dns.lookup",
      "dns.promises.resolve4",
      "dns.promises.Resolver.resolve4",
    ]);
  } finally {
    restore();
  }
  assert.equal(dns.lookup, originalLookup);
});

test("constructs tagged Ollama models with an explicit non-configurable provider", async () => {
  const model = await buildProviderModel("ollama", "llama3.2:latest");
  const configurable = model as {
    getName(): string;
    _defaultConfig?: { model?: unknown; modelProvider?: unknown };
    _configurableFields?: unknown;
  };
  assert.equal(configurable.getName(), "ConfigurableModel");
  assert.equal(configurable._defaultConfig?.model, "llama3.2:latest");
  assert.equal(configurable._defaultConfig?.modelProvider, "ollama");
  assert.deepEqual(configurable._configurableFields, []);
});

test("accepts only the strict controller request fields", async () => {
  const temporary = await fsPromises.mkdtemp(path.join(os.tmpdir(), "daiw-ts-worker-test-"));
  try {
    const validPath = path.join(temporary, "valid.json");
    await fsPromises.writeFile(validPath, JSON.stringify(requestPacket()), "utf8");
    assert.deepEqual(await loadRequest(validPath), requestPacket());

    const extended = { ...requestPacket(), untrusted_success: true };
    const extendedPath = path.join(temporary, "extended.json");
    await fsPromises.writeFile(extendedPath, JSON.stringify(extended), "utf8");
    await assert.rejects(loadRequest(extendedPath), /request fields are invalid/);

    const missing = requestPacket();
    delete missing.policy;
    const missingPath = path.join(temporary, "missing.json");
    await fsPromises.writeFile(missingPath, JSON.stringify(missing), "utf8");
    await assert.rejects(loadRequest(missingPath), /request fields are invalid/);

    const linkPath = path.join(temporary, "link.json");
    await fsPromises.symlink(validPath, linkPath);
    await assert.rejects(loadRequest(linkPath), /regular file/);
  } finally {
    await fsPromises.rm(temporary, { recursive: true, force: true });
  }
});

test("rejects unsafe write prefixes", async () => {
  const temporary = await fsPromises.mkdtemp(path.join(os.tmpdir(), "daiw-ts-path-test-"));
  try {
    for (const [index, value] of [["/app/"], ["../app/"], [".hidden/"], []].entries()) {
      const packet = requestPacket();
      packet.policy = { controller_is_sole_acceptor: true, allowed_paths: value };
      const requestPath = path.join(temporary, `unsafe-${index}.json`);
      await fsPromises.writeFile(requestPath, JSON.stringify(packet), "utf8");
      await assert.rejects(loadRequest(requestPath), /request write paths are invalid/);
    }
  } finally {
    await fsPromises.rm(temporary, { recursive: true, force: true });
  }
});
