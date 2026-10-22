const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

// Files the backend-common bump automation owns. A retag rewrites only the pin inside them.
const PIN_URL = 'github.com/gigaverse-app/backend-common.git';
const PIN_FILES = new Set(['uv.lock', 'pyproject.toml']);
const PIN_METADATA = 'backend-common-bump.json';
const SHA = /^[0-9a-f]{40}$/;

async function readBlob(github, repo, sha) {
  const { data } = await github.rest.git.getBlob({ ...repo, file_sha: sha });
  return Buffer.from(data.content, data.encoding === 'base64' ? 'base64' : 'utf8').toString('utf8');
}

// The one backend-common commit a consumer lock installs, or null when it pins none or several.
function pinnedCommit(lock) {
  const commits = new Set();
  for (const match of lock.matchAll(/backend-common\.git\?rev=[^"#\s]+#([0-9a-f]{40})/g)) commits.add(match[1]);
  return commits.size === 1 ? [...commits][0] : null;
}

// Spell every backend-common pin as the tree it installs. Only the rev name and commit, which
// a retag changes, are rewritten; any other byte stays and still distinguishes the tree.
function normalizePin(text, commit, pinnedTree) {
  return text
    .replace(/(backend-common\.git)\?rev=[^"#\s]+(?:#[0-9a-f]{40})?/g, `$1?tree=${pinnedTree}`)
    .replace(/(backend-common\.git"\s*,\s*)rev\s*=\s*"[^"]*"/g, `$1tree = "${pinnedTree}"`)
    .split(commit).join(pinnedTree);
}

function digest(lines) {
  return crypto.createHash('sha256').update(lines.join('\n')).digest('hex');
}

// A tree's content address with its pin files normalized: every other entry keeps its Git
// object id, so any change outside the pin's spelling changes the result.
async function normalizedTree(github, repo, treeSha, pin) {
  const listing = async (sha, rewrite) => {
    const { data } = await github.rest.git.getTree({ ...repo, tree_sha: sha });
    if (data.truncated) throw new Error(`tree ${sha} is truncated`);
    const lines = [];
    for (const entry of data.tree) {
      lines.push(`${entry.mode} ${entry.type} ${await rewrite(entry)} ${entry.path}`);
    }
    return digest(lines);
  };
  const normalizedBlob = async (entry) =>
    digest([normalizePin(await readBlob(github, repo, entry.sha), pin.commit, pin.tree)]);
  return listing(treeSha, async (entry) => {
    if (entry.type === 'blob' && PIN_FILES.has(entry.path)) return normalizedBlob(entry);
    if (entry.type === 'tree' && entry.path === '.github') {
      return listing(entry.sha, async (child) =>
        child.type === 'blob' && child.path === PIN_METADATA ? normalizedBlob(child) : child.sha);
    }
    return entry.sha;
  });
}

// The pin a tree's lock installs, resolved to backend-common's tree through the shared client.
async function resolvePin(github, shared, repo, treeSha) {
  const { data } = await github.rest.git.getTree({ ...repo, tree_sha: treeSha });
  const lock = data.tree.find((entry) => entry.path === 'uv.lock' && entry.type === 'blob');
  const commit = lock && pinnedCommit(await readBlob(github, repo, lock.sha));
  if (!commit) return null;
  const { data: pinned } = await shared.rest.git.getCommit({
    owner: 'gigaverse-app', repo: 'backend-common', commit_sha: commit,
  });
  if (!SHA.test(pinned.tree?.sha || '')) throw new Error(`backend-common ${commit} has no tree`);
  return { commit, tree: pinned.tree.sha };
}

// What a lane tested: the merged tree, the base it merged into, and the head's tree. The head
// commit's own SHA is not an input to any verdict; its tree is (some jobs test the head).
// GitHub re-creates a PR's test-merge commit with a new SHA (gigaverse-backend#4957), and a
// retag moves only the backend-common pin between commits of one tree (#217's PR217 -> v217);
// neither changes a receipt. With `shared`, pins are spelled as the tree they install.
async function testedIdentity(github, shared, repo, mergeSha, core) {
  const { data: merge } = await github.rest.git.getCommit({ ...repo, commit_sha: mergeSha });
  if (merge.parents?.length !== 2 || !merge.tree?.sha) throw new Error('Expected a two-parent PR merge');
  const [base, head] = merge.parents.map((parent) => parent.sha);
  const { data: headCommit } = await github.rest.git.getCommit({ ...repo, commit_sha: head });
  const exact = `tree ${merge.tree.sha} base ${base} head-tree ${headCommit.tree.sha}`;
  if (!shared) {
    core.warning('No dependency token: backend-common pins are compared exactly, so a retag re-runs every lane.');
    return exact;
  }
  try {
    const identity = [];
    for (const [role, treeSha] of [['tree', merge.tree.sha], ['head-tree', headCommit.tree.sha]]) {
      const pin = await resolvePin(github, shared, repo, treeSha);
      identity.push(`${role} ${pin ? `pin-normalized ${await normalizedTree(github, repo, treeSha, pin)}` : treeSha}`);
    }
    return `${identity[0]} base ${base} ${identity[1]}`;
  } catch (error) {
    core.warning(`Could not normalize backend-common pins (${error.message}); pins are compared exactly.`);
    return exact;
  }
}

// Inventory evidence deliberately excludes application code and the PR merge SHA.
// The consumer declares its build/scan inputs; shared tool bytes are added by validationReceipt.
async function inventoryIdentity(github, shared, repo, ref, paths) {
  if (!Array.isArray(paths) || !paths.length || paths.some((p) => typeof p !== 'string' || /[\\*?]/.test(p) || p.replace(/\/$/, '').split('/').some((part) => ['', '.', '..'].includes(part)))) {
    throw new Error('Inventory inputs must be nonempty repository-relative file or directory paths');
  }
  const { data: commit } = await github.rest.git.getCommit({ ...repo, commit_sha: ref });
  const treeSha = commit.tree.sha;
  const cache = new Map();
  const listing = async (sha) => {
    if (!cache.has(sha)) {
      const { data } = await github.rest.git.getTree({ ...repo, tree_sha: sha });
      if (data.truncated) throw new Error(`tree ${sha} is truncated`);
      cache.set(sha, data.tree);
    }
    return cache.get(sha);
  };
  const pin = shared ? await resolvePin(github, shared, repo, treeSha) : null;
  const lines = [];
  for (const input of [...new Set(paths.map((p) => p.replace(/\/$/, '')))].sort()) {
    let tree = treeSha;
    let entry;
    const parts = input.split('/');
    for (let i = 0; i < parts.length; i++) {
      entry = (await listing(tree)).find((e) => e.path === parts[i]);
      if (!entry || (i < parts.length - 1 && entry.type !== 'tree')) { entry = null; break; }
      tree = entry.sha;
    }
    let value = entry?.sha || 'missing';
    if (pin && entry?.type === 'blob' && PIN_FILES.has(input)) {
      value = digest([normalizePin(await readBlob(github, repo, entry.sha), pin.commit, pin.tree)]);
    }
    lines.push(`${input} ${entry?.mode || '-'} ${value}`);
  }
  return `inventory-v1 ${digest(lines)}`;
}

function validationReceipt(actionPath, testedIdentity, executionContext = '') {
  const root = path.resolve(actionPath, '../../..');
  const hash = crypto.createHash('sha256').update(testedIdentity);
  if (executionContext !== '') {
    hash.update('\0execution-context-v1\0').update(JSON.stringify(executionContext)).update('\0');
  }
  // PR<N> refs move. Bind proof to the downloaded shared implementation,
  // not just the consumer commit or the spelling of the shared ref.
  for (const directory of ['.github/actions', '.github/workflows', 'scripts', 'src/ci_esta']) {
    if (!fs.existsSync(path.join(root, directory))) continue;
    for (const entry of fs.readdirSync(path.join(root, directory), {recursive: true}).sort()) {
      const relative = `${directory}/${entry.split(path.sep).join('/')}`;
      const full = path.join(root, relative);
      if (fs.lstatSync(full).isFile() && !relative.includes('__pycache__')) {
        hash.update(relative).update('\0').update(fs.readFileSync(full)).update('\0');
      }
    }
  }
  for (const manifest of ['pyproject.toml', 'uv.lock']) {
    const full = path.join(root, manifest);
    if (fs.existsSync(full)) hash.update(manifest).update('\0').update(fs.readFileSync(full)).update('\0');
  }
  return `Validated inputs ${hash.digest('hex')}`;
}

module.exports = { testedIdentity, inventoryIdentity, validationReceipt };
