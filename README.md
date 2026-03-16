# scanservjs Home Assistant Add-on

`scanservjs` provides a web UI for SANE-compatible scanners on Home Assistant OS. This repository packages scanservjs as a custom Home Assistant add-on for `amd64` systems and optionally supports Brother devices through `brscan4`.

## Purpose

This add-on targets a stable, maintainable `scanservjs` deployment for Home Assistant OS with:

- ingress-enabled web access
- reproducible Docker builds
- semantically versioned releases
- optional Brother `brscan4` integration behind explicit opt-in controls

## Supported Architecture

- Primary target: `amd64`
- Not currently released: `aarch64`

## Installation

1. In Home Assistant, open `Settings` -> `Add-ons` -> `Add-on Store`.
2. Open the repository menu and choose `Repositories`.
3. Add the custom repository URL you want to consume.
4. Install `scanservjs Scan Server`.
5. Configure the add-on and start it.

Repository URLs:

- Upstream repository: [https://github.com/hoenas/ha-scanservjs-addon](https://github.com/hoenas/ha-scanservjs-addon)
- Fork with release workflow: [https://github.com/magicx78/ha-scanservjs-addon](https://github.com/magicx78/ha-scanservjs-addon)

## Configuration

### Generic SANE mode

```yaml
saned_net_hosts: "192.168.1.10;192.168.1.11"
airscan_devices: ""
scanimage_list_ignore: false
devices: ""
ocr_lang: "deu+eng"
copy_scans_to: "/share/paperless/consume"
brother_enable: false
```

### Brother-enabled mode

```yaml
saned_net_hosts: ""
airscan_devices: ""
scanimage_list_ignore: false
devices: ""
ocr_lang: "deu+eng"
copy_scans_to: "/share/paperless/consume"
brother_enable: true
brother_accept_eula: true
brother_driver_source: auto
brother_driver_url: ""
brother_driver_sha256: ""
brother_driver_local_path: "/share/brscan4.amd64.deb"
brother_register_scanner: true
brother_scanner_name: "MFC_L2700DW"
brother_scanner_model: "MFC-L2700DW"
brother_scanner_ip: "192.168.1.50"
brother_scanner_nodename: ""
brother_overwrite_existing: false
```

### Option reference

- `saned_net_hosts`: semicolon-separated hosts appended idempotently to `/etc/sane.d/net.conf`
- `airscan_devices`: semicolon-separated device lines inserted into `/etc/sane.d/airscan.conf`
- `scanimage_list_ignore`: optional scanservjs environment toggle
- `devices`: optional device filter forwarded to scanservjs
- `ocr_lang`: Tesseract OCR language selection such as `deu+eng`
- `copy_scans_to`: target directory for completed scans
- `brother_enable`: enables Brother setup logic
- `brother_accept_eula`: required before proprietary Brother download or install
- `brother_driver_source`: `auto`, `url`, or `local`
- `brother_driver_url`: direct `.deb` URL for `url` mode
- `brother_driver_sha256`: optional integrity check for downloaded package
- `brother_driver_local_path`: local `.deb` path for `local` mode
- `brother_register_scanner`: runs `brsaneconfig4` during startup
- `brother_scanner_name`: registration name used by `brsaneconfig4`
- `brother_scanner_model`: Brother model string
- `brother_scanner_ip`: scanner IP for network registration
- `brother_scanner_nodename`: optional nodename instead of IP
- `brother_overwrite_existing`: removes existing Brother registration before adding a new one

## USB vs Network

USB devices:

- require the scanner to be attached before add-on start
- depend on Home Assistant device passthrough and permissions

Network devices:

- are preferred for Home Assistant OS deployments
- can be configured through `saned_net_hosts`, `airscan_devices`, or Brother registration
- work best with static DHCP reservations or stable hostnames

## Brother Notes

Brother support is optional and disabled by default.

Variant A: stable generic add-on

- leave `brother_enable: false`
- keep `ENABLE_BROTHER_SUPPORT=false`
- rely on generic SANE backends only

Variant B: optional Brother mode

- set `brother_enable: true`
- set `brother_accept_eula: true`
- choose `auto`, `url`, or `local` package source
- verify registration with `brsaneconfig4 -q`

The container-level fallback remains available through `ENABLE_BROTHER_SUPPORT=false`, which forces generic SANE mode even if Brother options are set.

## Troubleshooting

Scanner not detected:

- inspect add-on logs
- run `scanimage -L` inside the container
- confirm `saned_net_hosts` and `airscan_devices`

Ingress or Web UI unavailable:

- verify the add-on reached the `started` state
- confirm ingress is enabled
- test direct port `8080` if ingress debugging is needed

Brother registration issues:

- confirm EULA acceptance
- validate the package source or local `.deb` path
- run `brsaneconfig4 -q`
- fall back to generic mode if Brother tooling fails

Known limits:

- `amd64` is the only release target at the moment
- Brother `auto` download still depends on Brother-hosted metadata and package availability
- full runtime validation on HAOS remains a manual test activity

## CI and Validation

Automated CI currently covers:

- `yamllint`
- `bash -n scanservjs/run.sh`
- `shellcheck`
- `node --check scanservjs/config.local.js`
- `docker build --build-arg BUILD_FROM=sbs20/scanservjs:v3.0.3 ./scanservjs`
- Trivy SARIF upload for vulnerability review

## Upgrade Notes

- `config.yml` was replaced by `config.yaml`
- `build.json` was replaced by `build.yaml`
- Brother support stays opt-in and disabled by default
- users upgrading from older snapshots should re-check add-on options after installation
