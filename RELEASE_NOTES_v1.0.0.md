# Release Notes v1.0.0

## Highlights

- Home Assistant add-on runtime stabilized for HAOS
- generic SANE scanner discovery verified on HAOS
- optional Brother `brscan4` runtime hardened with incremental startup fixes
- validated Brother network scan flow with `brother4:net1;dev0`
- successful `/api/v1/context` device detection and `/api/v1/scan` output generation
- GitHub Actions CI with YAML lint, shell validation, Node syntax checks, Docker build, and Trivy scanning

## Installation

- Repository URL: [https://github.com/magicx78/ha-scanservjs-addon](https://github.com/magicx78/ha-scanservjs-addon)
- Add repository to Home Assistant: [my.home-assistant.io add repository](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fmagicx78%2Fha-scanservjs-addon)
- Open add-on directly in Home Assistant: [my.home-assistant.io open add-on](https://my.home-assistant.io/redirect/supervisor_addon/?addon=9ca70578_scanservjs&repository_url=https%3A%2F%2Fgithub.com%2Fmagicx78%2Fha-scanservjs-addon)

## Upgrade Notes

- Brother support remains disabled by default
- proprietary Brother driver installation requires `brother_accept_eula: true`
- `ENABLE_BROTHER_SUPPORT=false` forces generic SANE mode even if Brother options are configured
- `brscan-skey` is optional and does not block the release gate for generic SANE operation

## Validation Summary

- `bash -n scanservjs/run.sh` passed via Git Bash
- `node --check scanservjs/config.local.js` passed
- CI build succeeded, including Trivy SARIF upload
- HAOS runtime validated with Brother MFC-L2710DW at `10.10.10.216`
- `/api/v1/context` returned `brother4:net1;dev0`
- `/api/v1/scan` successfully generated an output file
