import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { observeDeployment, waitForRevision } from "../../actions/observe-deployment/observe.mjs";
const readDeployedBuild = (url, options = {}) => observeDeployment(url, {
  source: 'pattern', key: 'Build Info: Version ([0-9a-f]{40}),', ...options,
});

const oldSha = "a".repeat(40);
const newSha = "b".repeat(40);
const html = (sha) => `<!doctype html><!-- Build Info: Version ${sha}, Built at today, Universe: tapin -->`;

async function server(t, handler) {
  const instance = createServer(handler);
  await new Promise((resolve) => instance.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => {
    instance.close(resolve);
    instance.closeAllConnections();
  }));
  return `http://127.0.0.1:${instance.address().port}/?existing=kept`;
}

test("a scheduled run records the deployed build without waiting for its checkout", async (t) => {
  let requests = 0;
  const url = await server(t, (request, response) => {
    requests++;
    assert.equal(request.headers["cache-control"], "no-cache");
    assert.match(request.url, /existing=kept/);
    assert.match(request.url, /deployment_check=/);
    response.end(html(oldSha));
  });
  assert.deepEqual(await readDeployedBuild(url), { state: "ready", sha: oldSha });
  assert.equal(requests, 1);
});

test("a push waits through an unavailable deployment and a stale build for its exact SHA", async (t) => {
  let requests = 0;
  const url = await server(t, (_request, response) => {
    requests++;
    if (requests === 1) {
      response.writeHead(503).end();
      return;
    }
    response.end(html(requests === 2 ? oldSha : newSha));
  });
  assert.deepEqual(await readDeployedBuild(url, { expectedSha: newSha, pollMs: 1, timeoutMs: 2000 }), { state: "ready", sha: newSha });
  assert.equal(requests, 3);
});

test("a deployment that never reaches the requested commit fails instead of testing a stale build", async (t) => {
  const url = await server(t, (_request, response) => response.end(html(oldSha)));
  await assert.rejects(readDeployedBuild(url, { expectedSha: newSha, pollMs: 10, timeoutMs: 600 }), /was not deployed/);
});

test("an HTML response without Build Info cannot be reported as a known deployed build", async (t) => {
  const url = await server(t, (_request, response) => response.end("<html>Unavailable</html>"));
  await assert.rejects(readDeployedBuild(url), /Deployed revision missing or invalid/);
});

test("a deployed descendant supersedes the requested smoke without waiting for its deadline", async (t) => {
  let requests = 0;
  const comparisons = [];
  const url = await server(t, (_request, response) => {
    requests++;
    response.end(html(newSha));
  });
  const result = await readDeployedBuild(url, {
    expectedSha: oldSha, timeoutMs: 2000,
    compareCommits(base, head, timeoutMs) {
      comparisons.push([base, head]);
      assert.ok(timeoutMs > 0 && timeoutMs <= 2000);
      return "ahead";
    },
  });
  assert.deepEqual(result, { state: "superseded", sha: newSha });
  assert.equal(requests, 1);
  assert.deepEqual(comparisons, [[oldSha, newSha]]);
});

for (const status of ["behind", "diverged"]) {
  test(`a ${status} deployment never supersedes the smoke and is compared only once`, async (t) => {
    let requests = 0;
    let comparisons = 0;
    const url = await server(t, (_request, response) => {
      requests++;
      response.end(html(oldSha));
    });
    await assert.rejects(readDeployedBuild(url, {
      expectedSha: newSha, pollMs: 5, timeoutMs: 600,
      compareCommits() { comparisons++; return status; },
    }), /was not deployed/);
    assert.ok(requests > 1);
    assert.equal(comparisons, 1);
  });
}

test("a stale build followed by the exact SHA runs the smoke after one comparison", async (t) => {
  let requests = 0;
  let comparisons = 0;
  const url = await server(t, (_request, response) => {
    response.end(html(++requests < 3 ? oldSha : newSha));
  });
  assert.deepEqual(await readDeployedBuild(url, {
    expectedSha: newSha, pollMs: 1, timeoutMs: 2000,
    compareCommits(base, head) {
      assert.deepEqual([base, head], [newSha, oldSha]);
      comparisons++;
      return "behind";
    },
  }), { state: "ready", sha: newSha });
  assert.equal(comparisons, 1);
});

test("a transient comparison failure still allows the expected deployment to become ready", async (t) => {
  let requests = 0;
  let comparisons = 0;
  const url = await server(t, (_request, response) => response.end(html(++requests === 1 ? oldSha : newSha)));
  assert.deepEqual(await readDeployedBuild(url, {
    expectedSha: newSha, pollMs: 1, timeoutMs: 2000,
    compareCommits() { comparisons++; throw new Error("GitHub HTTP 502"); },
  }), { state: "ready", sha: newSha });
  assert.equal(requests, 2);
  assert.equal(comparisons, 1);
});

test("a failed comparison is retried for the same SHA before declaring it superseded", async (t) => {
  let comparisons = 0;
  const url = await server(t, (_request, response) => response.end(html(newSha)));
  assert.deepEqual(await readDeployedBuild(url, {
    expectedSha: oldSha, pollMs: 1, timeoutMs: 2000,
    compareCommits() {
      if (++comparisons === 1) throw new Error("GitHub HTTP 502");
      return "ahead";
    },
  }), { state: "superseded", sha: newSha });
  assert.equal(comparisons, 2);
});

test("an unavailable comparison is retried until the deployment deadline and reported there", async (t) => {
  let comparisons = 0;
  const url = await server(t, (_request, response) => response.end(html(newSha)));
  await assert.rejects(readDeployedBuild(url, {
    expectedSha: oldSha, pollMs: 5, timeoutMs: 600,
    compareCommits() { comparisons++; throw new Error("GitHub HTTP 502"); },
  }), /was not deployed.*commit comparison failed: GitHub HTTP 502/);
  assert.ok(comparisons > 1);
});

test("a request cut off by the deployment deadline keeps the last comparison failure in the report", async (t) => {
  let requests = 0;
  const url = await server(t, (_request, response) => {
    if (++requests === 1) response.end(html(newSha));
  });
  await assert.rejects(readDeployedBuild(url, {
    expectedSha: oldSha, pollMs: 1, timeoutMs: 600,
    compareCommits() { throw new Error("GitHub HTTP 502"); },
  }), /was not deployed.*commit comparison failed: GitHub HTTP 502/);
  assert.ok(requests > 1);
});

test("an unknown comparison result cannot silently suppress the smoke", async (t) => {
  const url = await server(t, (_request, response) => response.end(html(newSha)));
  await assert.rejects(readDeployedBuild(url, {
    expectedSha: oldSha, timeoutMs: 2000,
    compareCommits() { return "unknown"; },
  }), /Unknown commit comparison/);
});

test("scheduled reads and an exact smoke SHA do not query commit history", async (t) => {
  const url = await server(t, (_request, response) => response.end(html(newSha)));
  const compareCommits = () => assert.fail("unexpected comparison");
  for (const expectedSha of ["", newSha]) {
    assert.deepEqual(await readDeployedBuild(url, { expectedSha, compareCommits }), { state: "ready", sha: newSha });
  }
});

test("a failed deployment remains an error without querying commit history", async (t) => {
  const url = await server(t, (_request, response) => response.writeHead(503).end());
  await assert.rejects(readDeployedBuild(url, {
    expectedSha: newSha, pollMs: 5, timeoutMs: 600,
    compareCommits: () => assert.fail("unexpected comparison"),
  }), /HTTP 503/);
});

for (const state of ["ready", "superseded", "invalid-comparison"]) {
  test(`the CLI publishes the ${state} outcome for the workflow`, { skip: process.platform === "win32" && state !== "ready" }, async (t) => {
    const dir = mkdtempSync(path.join(tmpdir(), "deployed-build-"));
    t.after(() => rmSync(dir, { recursive: true, force: true }));
    writeFileSync(path.join(dir, "gh"), `#!/usr/bin/env bash
printf '%s\\n' "$@" > "$COMPARISON_LOG"
printf '%s\\n' "$COMPARISON_RESULT"
`, { mode: 0o755 });
    const url = await server(t, (_request, response) => response.end(html(newSha)));
    const expectedSha = state === "ready" ? newSha : oldSha;
    const output = path.join(dir, "outputs");
    const summary = path.join(dir, "summary");
    const comparisons = path.join(dir, "comparisons");
    const run = promisify(execFile)(process.execPath, [fileURLToPath(new URL("../../actions/observe-deployment/run.mjs", import.meta.url))], {
      timeout: 5000,
      env: {
        ...process.env,
        PATH: `${dir}:${process.env.PATH}`,
        DEPLOYMENT_URL: url,
        REVISION_SOURCE: "pattern",
        REVISION_KEY: "Build Info: Version ([0-9a-f]{40}),",
        EXPECTED_SHA: expectedSha,
        COMPARE_REPOSITORY: "example/web",
        GITHUB_OUTPUT: output,
        GITHUB_STEP_SUMMARY: summary,
        COMPARISON_LOG: comparisons,
        COMPARISON_RESULT: state === "invalid-comparison" ? "unknown" : "ahead",
      },
    });
    if (state === "invalid-comparison") {
      await assert.rejects(run, /Unknown commit comparison/);
      assert.equal(existsSync(output), false);
      assert.equal(existsSync(summary), false);
      return;
    }
    await run;
    assert.equal(readFileSync(output, "utf8"), `state=${state}\nsha=${newSha}\n`);
    if (state === "ready") {
      assert.equal(existsSync(comparisons), false);
      assert.equal(existsSync(summary), false);
    } else {
      assert.equal(readFileSync(comparisons, "utf8"), `api\n/repos/example/web/compare/${oldSha}...${newSha}\n--jq\n.status\n`);
      const text = readFileSync(summary, "utf8");
      assert.ok(text.includes(oldSha) && text.includes(newSha));
      assert.match(text, /Smoke skipped: newer commit deployed/);
      assert.match(text, /No smoke tests ran/);
    }
  });
}

for (const source of ['json', 'header']) {
  test(`another application exposes its revision through ${source}`, async t => {
    const url = await server(t, (_request, response) => {
      response.setHeader('x-revision', newSha);
      response.end(JSON.stringify({ build: { commit: newSha } }));
    });
    assert.deepEqual(await observeDeployment(url, {
      source, key: source === 'json' ? 'build.commit' : 'x-revision',
    }), { state: 'ready', sha: newSha });
  });
}

test('a non-HTTP observer shares the deadline and ancestry state machine', async () => {
  let calls = 0;
  assert.deepEqual(await waitForRevision(async () => ++calls === 1 ? oldSha : newSha, {
    expectedSha: newSha, pollMs: 1, timeoutMs: 6000,
  }), { state: 'ready', sha: newSha });
  assert.equal(calls, 2);
});

test('invalid HTTP revision data cannot become output or a comparison input', async t => {
  const url = await server(t, (_request, response) => response.end(JSON.stringify({sha: 'fake\\nstate=ready'})));
  await assert.rejects(observeDeployment(url, { timeoutMs: 50 }), /missing or invalid/);
});
