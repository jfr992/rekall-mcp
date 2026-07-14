# Releasing

`publish.yml` fires on tags `v*`: it builds and pushes the multi-arch image to
`ghcr.io/jfr992/rekall-mcp` (size-gated at 1 GB) and publishes the wheel to
PyPI via Trusted Publishing. Everything below the "Cutting a release" section
is one-time operator setup.

## Cutting a release

```bash
# on main, after the release PR merges
# 1. bump version in pyproject.toml (feature branch + PR like any change)
# 2. tag and push
git tag vX.Y.Z
git push origin vX.Y.Z
# 3. watch the Publish workflow; then create the GitHub release
gh release create vX.Y.Z --title vX.Y.Z --notes-file <(sed -n '/^# Migration Guide — /,/^---$/p' docs/MIGRATION.md)
```

Verify afterwards:

```bash
docker run --rm -v rekall-smoke:/data -p 127.0.0.1:8000:8000 ghcr.io/jfr992/rekall-mcp:X.Y.Z &
curl -sf http://localhost:8000/health | jq .server   # "rekall"
uvx rekall-mcp@X.Y.Z --help >/dev/null || true       # wheel resolves from PyPI
docker volume rm rekall-smoke
```

## One-time: PyPI Trusted Publishing

No API tokens; PyPI trusts the GitHub Actions OIDC identity.

1. Create the project once: `uv build && uv publish` with a scoped API token,
   or reserve the name via PyPI's "pending publisher" flow (preferred — no
   token ever exists): pypi.org → Your account → Publishing → "Add a pending
   publisher".
2. Publisher settings, exactly matching `publish.yml`:
   - PyPI project name: `rekall-mcp`
   - Owner: `jfr992`, repository: `rekall-mcp`
   - Workflow name: `publish.yml`
   - Environment: `pypi`
3. In the GitHub repo: Settings → Environments → create `pypi` (optionally
   add required reviewers — this gates every publish).

## One-time: ghcr visibility

The first push creates the package as **private**. Make it public:
github.com → profile → Packages → `rekall-mcp` → Package settings →
Change visibility → Public. Then link it to the repo (same page, "Connect
repository") so it shows on the repo sidebar and inherits repo permissions.

## Post-publish: registry listings

All of these want a *published* artifact first (uvx from PyPI, image from
ghcr) — run a cold-start install against the published artifacts before
listing anywhere.

| Registry | How |
|---|---|
| Smithery (smithery.ai) | Sign in with GitHub → Add server → point at the repo; needs `smithery.yaml` describing the stdio command (`uvx rekall-mcp`) |
| Glama (glama.ai/mcp) | Submit via glama.ai/mcp/servers → Add server → GitHub URL; auto-indexes the README |
| mcp.so | Submit form on mcp.so → Submit; name, repo URL, install command |
| PulseMCP (pulsemcp.com) | Submit via pulsemcp.com/submit; they scrape the repo README |

Keep the README quickstart accurate — every registry above renders it as the
install doc.
