// ─────────────────────────────────────────────
//  ProcessRunner
//  Resolves the correct command + args + cwd
//  for every supported process type, then
//  spawns (or returns the spawn config for) it.
// ─────────────────────────────────────────────
const path  = require('path');
const fs    = require('fs');

// On Windows, npm/npx are .cmd wrappers
const IS_WIN  = process.platform === 'win32';
const NPM     = IS_WIN ? 'npm.cmd'  : 'npm';
const NPX     = IS_WIN ? 'npx.cmd'  : 'npx';
const PYTHON  = IS_WIN ? 'python'   : 'python3';

/**
 * SUPPORTED TYPES
 * ───────────────
 * discord_py        → python3 <path>
 * discord_js / node → node <path>
 * node_npm_start    → npm start              (cwd = process dir)
 * npm_script        → npm run <npmScript>    (cwd = process dir)
 * shell             → sh <path>              (bash on Linux/macOS)
 * bat               → cmd /c <path>          (Windows only)
 * ps1               → powershell -File <path>(Windows only)
 */

const TYPES = {
  discord_py:     { label: 'Discord Bot (Python)',            icon: '🐍' },
  discord_js:     { label: 'Discord Bot (Node.js)',           icon: '🤖' },
  node:           { label: 'Node.js App',                     icon: '🟩' },
  node_npm_start: { label: 'Node.js App (npm start)',         icon: '🟩' },
  npm_script:     { label: 'npm Script (npm run …)',          icon: '📦' },
  shell:          { label: 'Shell Script (.sh)',               icon: '🐚' },
  bat:            { label: 'Batch File (.bat) — Windows',     icon: '🪟' },
  ps1:            { label: 'PowerShell Script (.ps1) — Windows', icon: '🪟' },
};

/**
 * Resolve the spawn config for a process definition.
 *
 * @param {object} proc - Process definition from ConfigStore
 * @returns {{ cmd: string, args: string[], cwd: string, env: object }}
 * @throws {Error} if the type is unknown or required fields are missing
 */
function resolveSpawnConfig(proc) {
  const { type, path: procPath, cwd, npmScript, env = {} } = proc;

  // Helper: determine the working directory
  // Priority: explicit cwd → parent dir of path → process.cwd()
  const resolveCwd = (filePath) => {
    if (cwd && fs.existsSync(cwd)) return cwd;
    if (filePath) return path.dirname(path.resolve(filePath));
    return process.cwd();
  };

  // Helper: assert a field exists
  const need = (field, val) => {
    if (!val) throw new Error(`Process "${proc.name}" (${type}): missing required field "${field}"`);
  };

  switch (type) {

    // ── Python-based Discord bot ───────────────────────────────────────
    case 'discord_py':
      need('path', procPath);
      return {
        cmd:  PYTHON,
        args: [path.resolve(procPath)],
        cwd:  resolveCwd(procPath),
        env,
      };

    // ── Node.js / Discord.js bot (direct file) ────────────────────────
    case 'discord_js':
    case 'node':
      need('path', procPath);
      return {
        cmd:  process.execPath,          // same node binary running this panel
        args: [path.resolve(procPath)],
        cwd:  resolveCwd(procPath),
        env,
      };

    // ── npm start (no script name needed) ─────────────────────────────
    case 'node_npm_start': {
      const workDir = cwd || (procPath ? path.dirname(path.resolve(procPath)) : null);
      if (!workDir) throw new Error(`Process "${proc.name}": provide "cwd" or "path" for npm start`);
      assertPackageJson(workDir, proc.name);
      return {
        cmd:  NPM,
        args: ['start'],
        cwd:  workDir,
        env,
      };
    }

    // ── npm run <script> ──────────────────────────────────────────────
    case 'npm_script': {
      const workDir = cwd || (procPath ? path.dirname(path.resolve(procPath)) : null);
      if (!workDir) throw new Error(`Process "${proc.name}": provide "cwd" or "path" for npm run`);
      if (!npmScript) throw new Error(`Process "${proc.name}": provide "npmScript" (e.g. "dev") for npm_script type`);
      assertPackageJson(workDir, proc.name);
      assertNpmScript(workDir, npmScript, proc.name);
      return {
        cmd:  NPM,
        args: ['run', npmScript],
        cwd:  workDir,
        env,
      };
    }

    // ── Shell script ──────────────────────────────────────────────────
    case 'shell':
      need('path', procPath);
      return {
        cmd:  IS_WIN ? 'bash' : '/bin/sh',
        args: [path.resolve(procPath)],
        cwd:  resolveCwd(procPath),
        env,
      };

    // ── Windows Batch file ────────────────────────────────────────────
    case 'bat':
      need('path', procPath);
      return {
        cmd:  'cmd',
        args: ['/c', path.resolve(procPath)],
        cwd:  resolveCwd(procPath),
        env,
      };

    // ── PowerShell script ─────────────────────────────────────────────
    case 'ps1':
      need('path', procPath);
      return {
        cmd:  'powershell',
        args: ['-ExecutionPolicy', 'Bypass', '-File', path.resolve(procPath)],
        cwd:  resolveCwd(procPath),
        env,
      };

    default:
      throw new Error(`Unknown process type: "${type}"`);
  }
}

/**
 * List of all supported types, for use in the UI type dropdown.
 * @returns {Array<{ value: string, label: string, icon: string, needsNpmScript: boolean, needsPath: boolean }>}
 */
function getSupportedTypes() {
  return Object.entries(TYPES).map(([value, { label, icon }]) => ({
    value,
    label,
    icon,
    // UI hints so the frontend can show/hide the right fields
    needsNpmScript: value === 'npm_script',
    needsPath:      !['node_npm_start', 'npm_script'].includes(value),
    needsCwd:       ['node_npm_start', 'npm_script'].includes(value),
  }));
}

// ── Internal helpers ──────────────────────────────────────────────────────────

function assertPackageJson(dir, procName) {
  const pkgPath = path.join(dir, 'package.json');
  if (!fs.existsSync(pkgPath)) {
    throw new Error(
      `Process "${procName}": no package.json found in "${dir}". ` +
      `Make sure "cwd" points to your project root.`
    );
  }
}

function assertNpmScript(dir, scriptName, procName) {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf-8'));
    const scripts = pkg.scripts || {};
    if (!scripts[scriptName]) {
      const available = Object.keys(scripts).join(', ') || '(none)';
      throw new Error(
        `Process "${procName}": npm script "${scriptName}" not found in package.json. ` +
        `Available scripts: ${available}`
      );
    }
  } catch (err) {
    if (err.message.includes('npm script')) throw err; // re-throw our own errors
    throw new Error(`Process "${procName}": failed to read package.json — ${err.message}`);
  }
}

module.exports = { resolveSpawnConfig, getSupportedTypes, TYPES };
