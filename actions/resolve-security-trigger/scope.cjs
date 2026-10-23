// Security admission owns path semantics for every caller. Uncertain evidence
// must retain all checks; only a complete, valid diff may eliminate work.
function pathMatcher(pattern) {
  const parts = pattern.split(/(\*\*\/|\*\*|\*)/);
  const regex = parts.map((part) => {
    if (part === '**/') return '(?:.*/)?';
    if (part === '**') return '.*';
    if (part === '*') return '[^/]*';
    return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }).join('');
  return new RegExp(`^${regex}${pattern.endsWith('/') ? '.*' : ''}$`);
}

function classifyChanges({ files, complete, dependencyPatterns = [], ignoredPaths = [], prosePatterns = [], sourceExcludedPaths = [] }) {
  const unknown = { depsChanged: true, semgrepChanged: true, sourceChanged: true };
  const statuses = new Set(['added', 'modified', 'removed', 'renamed', 'copied', 'changed', 'unchanged']);
  if (complete !== true || !Array.isArray(files) || files.some((file) =>
    !file || typeof file.filename !== 'string' || !file.filename ||
    !statuses.has(file.status) ||
    (file.status === 'renamed' && typeof file.previous_filename !== 'string') ||
    (file.previous_filename !== undefined && typeof file.previous_filename !== 'string')
  )) return unknown;
  const dependencies = dependencyPatterns.map(pathMatcher);
  const prose = prosePatterns.map(pathMatcher);
  const ignored = new Set(ignoredPaths);
  const findings = files.filter((file) => file.status !== 'removed' && !ignored.has(file.filename) &&
    !sourceExcludedPaths.some((path) => file.filename === path || file.filename.startsWith(`${path.replace(/\/$/, '')}/`)));
  return {
    // No configured inventory contract means the caller has not opted into skipping.
    depsChanged: dependencies.length === 0 || files.some((file) =>
      dependencies.some((matcher) => matcher.test(file.filename) ||
        (file.previous_filename && matcher.test(file.previous_filename)))),
    semgrepChanged: findings.length > 0,
    // Renames out of a runtime path cannot hide a source/configuration change.
    sourceChanged: findings.some((file) => !prose.some((matcher) => matcher.test(file.filename)) ||
      (file.previous_filename && !prose.some((matcher) => matcher.test(file.previous_filename)))),
  };
}

module.exports = { classifyChanges };
