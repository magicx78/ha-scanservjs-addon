# Changelog

## [1.0.11] - 2026-03-16

### Added
- Brother frontpanel runtime options in add-on config:
  - per-button copy routing (`brother_copy_*_to_target`)
  - output format controls for image/ocr (`brother_image_output_format`, `brother_ocr_output_format`)
  - default Brother button DPI fallback (`brother_button_default_resolution`)
  - optional Brother button output directory (`brother_button_output_dir`)
- `copy_scans_to_mode` (`auto|paperless|custom`) for clearer scan target selection.
- Preset documentation for common HA/Paperless workflows.

### Changed
- Brother button scans now default to scanservjs `data/output`, making them visible in the scanservjs `Files` tab.
- Brother `brscan-skey` package download now tries the current URL first and only falls back to legacy URL if needed.
- Add-on app/store icon updated.

### Fixed
- Resolved restart loop caused by non-fatal `brscan-skey` process check under `set -e`.
- `Scan to Image` and `Scan to OCR` now run a real scan before webhook trigger.
- Paperless ingest compatibility improved by auto-converting Brother TIFF copies to JPG when target is `/share/paperless...`.

### Validation
- HAOS smoke validation passed for `v1.0.11` / `Runtime-Revision: 2026-03-16-r27`:
  - add-on starts without restart loop
  - `Starte scanservjs` reached
  - `/api/v1/context` returns Brother device (`brother4:net1;dev0`)
  - generic Web/API scanning works
  - Brother frontpanel `File/Email/Image/OCR` verified end-to-end

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
