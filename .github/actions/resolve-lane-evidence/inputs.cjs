const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

function digest(lines) {
  return crypto.createHash('sha256').update(lines.join('\n')).digest('hex');
}

// Bind the merged tree, base commit and head tree. A recreated merge commit
// with the same inputs may reuse evidence; a changed base or source tree may not.
async function testedIdentity(github, _shared, repo, mergeSha, _core) {
  const { data: merge } = await github.rest.git.getCommit({ ...repo, commit_sha: mergeSha });
  if (merge.parents?.length !== 2 || !merge.tree?.sha) throw new Error('Expected a two-parent PR merge');
  const [base, head] = merge.parents.map((parent) => parent.sha);
  const { data: headCommit } = await github.rest.git.getCommit({ ...repo, commit_sha: head });
  if (!headCommit.tree?.sha) throw new Error('Missing head tree');
  return `tree ${merge.tree.sha} base ${base} head-tree ${headCommit.tree.sha}`;
}

// Inventory evidence deliberately excludes application code and the PR merge SHA.
// The consumer declares its build/scan inputs; shared tool bytes are added by validationReceipt.
async function inventoryIdentity(github, _shared, repo, ref, paths) {
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
    const value = entry?.sha || 'missing';
    lines.push(`${input} ${entry?.mode || '-'} ${value}`);
  }
  return `inventory-v1 ${digest(lines)}`;
}

function validationReceipt(actionPath, testedIdentity) {
  const root = path.resolve(actionPath, '../../..');
  const hash = crypto.createHash('sha256').update(testedIdentity);
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
