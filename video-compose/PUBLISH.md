# Publishing video-compose to PyPI

## Setup (one-time)

1. Register trusted publisher on pypi.org:
   - Project: `video-compose`
   - Owner: `tomastimelock`
   - Repo: `trollfabriken-video-compose-bootstrap`
   - Workflow: `publish.yml`
   - Environment: `pypi`

2. Create GitHub environment `pypi` on the repo settings page.

## Release

```bash
git tag v0.1.0
git push origin v0.1.0
```

The `publish.yml` workflow builds and uploads automatically via OIDC trusted publishing (no API token needed).

## Daily limit note

PyPI enforces a daily limit on new project registrations (~5/day per account).
If you hit it, wait until UTC midnight and retry.
