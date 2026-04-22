---
name: install-effect-package
description: Install @effect/* packages safely. Use whenever adding a new Effect ecosystem dependency.
user-invocable: false
---

## Installing Effect Ecosystem Packages

When installing any `@effect/*` package, **always use `npm install --force`**:

```bash
npm install --force @effect/package-name
```

### Why not `--legacy-peer-deps`?

The `--legacy-peer-deps` flag corrupts the lockfile by removing existing `@effect/*` peer dependencies (e.g., `@effect/rpc`, `@effect/sql`, `@effect/experimental`). The corruption is silent — `npm install` succeeds but the lockfile is broken, and you only discover the damage later when other Effect packages fail to resolve.

`--force` installs the package while preserving the existing dependency tree.
