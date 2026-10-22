// A github-script client fake that cannot drift from the real client.
//
// Hand-written fakes let tests call any method name they define. resolve.cjs called
// `actions.listWorkflowRunsForWorkflow`, the test fake defined it, every test passed,
// and in production the pinned Octokit had no such method: `github.paginate(undefined)`
// fetched the API root and every same-head reuse fell back without a word. This fake
// only accepts methods the pinned actions/github-script provides
// (github_script_rest_surface.json), and its paginate refuses a non-function the way the
// real call silently would not.
const { rest: SURFACE } = require("./github_script_rest_surface.json");

function unknown(namespace, method) {
  return new Error(
    `github.rest.${namespace}.${method} does not exist in the pinned actions/github-script ` +
      "(tests/ci/github_script_rest_surface.json)",
  );
}

// `pages` optionally replaces the default paginate body, for tests that serve canned pages.
function strictGithub(rest, pages) {
  for (const [namespace, methods] of Object.entries(rest)) {
    for (const method of Object.keys(methods)) {
      if (!(SURFACE[namespace] || []).includes(method)) throw unknown(namespace, method);
    }
  }
  const namespaces = new Proxy(rest, {
    get(target, namespace) {
      if (typeof namespace === "symbol") return target[namespace];
      if (!SURFACE[namespace]) throw new Error(`github.rest.${namespace} does not exist in the pinned client`);
      const implemented = target[namespace] || {};
      return new Proxy(implemented, {
        get(methods, method) {
          if (typeof method === "symbol") return methods[method];
          if (!SURFACE[namespace].includes(method)) throw unknown(namespace, method);
          if (!(method in methods)) throw new Error(`the test fake does not implement github.rest.${namespace}.${method}`);
          return methods[method];
        },
      });
    },
  });
  return {
    rest: namespaces,
    paginate: async (method, args) => {
      // The real paginate treats a non-function as a route and requests the API root.
      if (typeof method !== "function") {
        throw new Error("github.paginate received a non-function; the real client would fetch the API root");
      }
      if (pages) return pages(method, args);
      const data = (await method(args)).data;
      return data.workflow_runs ?? data.jobs ?? data.check_runs ?? data;
    },
  };
}

module.exports = { strictGithub, SURFACE };
