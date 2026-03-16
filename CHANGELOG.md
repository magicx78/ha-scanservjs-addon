# Changelog

## [1.0.0] - 2026-03-16

### Added
- Optional Brother `brscan4` installation with explicit EULA gating.
- Optional Brother network scanner registration for devices such as the MFC-L2700DW.
- Fallback feature flag `ENABLE_BROTHER_SUPPORT=false` for generic SANE-only startup.
- GitHub Actions CI for YAML linting, shell validation, Node syntax checks, Docker build, and Trivy scanning.
- Repository maintenance files: issue templates, pull request template, security policy, and Dependabot.

### Changed
- Migrated Home Assistant addon metadata to `config.yaml` and `build.yaml`.
- Limited the supported architecture to `amd64` for a predictable release target.
- Fixed copy destination handling so `copy_scans_to` is honored.
- Improved startup idempotency for `saned_net_hosts`, `airscan_devices`, and Brother registration.
- Added LF enforcement through `.gitattributes`.

### Fixed
- Removed deprecated Debian Stretch based addon build metadata.
- Cleaned package management steps in the Docker image and at Brother driver install time.
