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
