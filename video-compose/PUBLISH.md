# Publishing video-compose to PyPI

## Setup (one-time)

### 1. Register trusted publisher on pypi.org

Go to: https://pypi.org/manage/account/publishing/

Add a new trusted publisher:

| Field       | Value                                        |
|-------------|----------------------------------------------|
| Project     | `video-compose`                              |
| Owner       | `tomastimelock`                              |
| Repository  | `trollfabriken-video-compose-bootstrap`      |
| Workflow    | `publish.yml`                                |
| Environment | `pypi`                                       |

### 2. GitHub environment

The `pypi` environment has already been created on the repo.
No additional secrets or protection rules required — OIDC handles auth.

## Release

```bash
# From the video-compose/ subdirectory
git tag v0.1.0
git push origin v0.1.0
```

The `publish.yml` workflow triggers on `v*` tags, builds the wheel + sdist,
publishes to PyPI via OIDC trusted publishing (no API token needed), and
creates a GitHub release with the dist artifacts.

## Install extras

```bash
# Core only (blank/image/video segments — no fx packages)
pip install video-compose

# Core FX stack (mathviz + chart + geomap + shape + fractal + grade + cut + text + still)
pip install "video-compose[fx]"

# With audio (talk-cast voiceover + audio-arrange mixing)
pip install "video-compose[fx,audio]"

# Everything
pip install "video-compose[all]"

# Data sources (CSV / JSON / Excel / SQL / REST API)
pip install "video-compose[data]"
```

## Daily limit note

PyPI enforces a daily limit on new project registrations (~5/day per account).
If you hit it, wait until UTC midnight and retry.
