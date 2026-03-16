# Release Notes v1.0.0

## Highlights

- Home Assistant addon metadata migrated to `config.yaml` and `build.yaml`
- `amd64` release target for predictable Home Assistant OS deployments
- optional Brother `brscan4` installation and startup registration for network scanners
- idempotent startup configuration for SANE network hosts and airscan devices
- fixed `copy_scans_to` handling in the scan completion hook
- GitHub Actions CI with YAML lint, shell validation, Node syntax checks, Docker build, and Trivy scanning
- repository maintenance files for bugs, features, pull requests, dependency updates, and vulnerability reporting

## Upgrade Notes

- Brother support remains disabled by default
- proprietary Brother driver installation requires `brother_accept_eula: true`
- `ENABLE_BROTHER_SUPPORT=false` forces generic SANE mode even if Brother options are configured

## Validation Summary

- `bash -n scanservjs/run.sh` passed via Git Bash
- `node --check scanservjs/config.local.js` passed
- Docker build and ShellCheck are delegated to CI because they are not available in the local Windows environment
