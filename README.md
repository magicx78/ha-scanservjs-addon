# scanservjs Home Assistant Add-on

`scanservjs` provides a web UI for SANE-compatible scanners on Home Assistant OS. This repository packages scanservjs as a custom Home Assistant add-on for `amd64` systems and optionally supports Brother devices through `brscan4`.

## Status

- Release target: `v1.0.0`
- Primary architecture: `amd64`
- Add-on slug: `scanservjs`
- Repository URL: [https://github.com/hoenas/ha-scanservjs-addon](https://github.com/hoenas/ha-scanservjs-addon)

## Installation

1. In Home Assistant, open `Settings` -> `Add-ons` -> `Add-on Store`.
2. Open the repository menu and choose `Repositories`.
3. Add `https://github.com/hoenas/ha-scanservjs-addon`.
4. Install `scanservjs Scan Server`.
5. Configure the addon options and start the addon.

## Core Configuration

Available options in `scanservjs/config.yaml`:

- `saned_net_hosts`: semicolon-separated SANE network backends to append to `/etc/sane.d/net.conf`
- `airscan_devices`: semicolon-separated device entries to inject into `/etc/sane.d/airscan.conf`
- `copy_scans_to`: directory to copy completed scans to
- `ocr_lang`: Tesseract OCR languages, for example `deu+eng`
- `scanimage_list_ignore`: pass-through flag for scanservjs environments
- `devices`: optional scanner device filter

Example:

```yaml
saned_net_hosts: "192.168.1.10;192.168.1.11"
airscan_devices: ""
scanimage_list_ignore: false
devices: ""
ocr_lang: "deu+eng"
copy_scans_to: "/share/paperless/consume"
```

## Brother Support

Brother support is optional and disabled by default.

Controls:

- `brother_enable`: enables Brother setup logic from addon options
- `brother_accept_eula`: must be `true` before any proprietary driver download or installation happens
- `brother_driver_source`: `auto`, `url`, or `local`
- `brother_driver_url`: direct download URL if `brother_driver_source=url`
- `brother_driver_local_path`: local `.deb` path if `brother_driver_source=local`
- `brother_register_scanner`: controls `brsaneconfig4` registration on startup
- `brother_overwrite_existing`: removes an existing Brother registration before re-adding it

Feature flag fallback:

- `ENABLE_BROTHER_SUPPORT=false` keeps the container in generic SANE mode even if Brother addon options are set

Example for a Brother MFC-L2700DW:

```yaml
brother_enable: true
brother_accept_eula: true
brother_driver_source: auto
brother_register_scanner: true
brother_scanner_name: "MFC_L2700DW"
brother_scanner_model: "MFC-L2700DW"
brother_scanner_ip: "192.168.1.50"
brother_overwrite_existing: false
```

Equivalent manual registration inside the container:

```bash
brsaneconfig4 -a "name=MFC_L2700DW" "model=MFC-L2700DW" "ip=192.168.1.50"
brsaneconfig4 -q
```

## Troubleshooting

### Scanner not detected

- Check addon logs in Home Assistant.
- Open a shell in the addon container and run `scanimage -L`.
- Verify `saned_net_hosts` and `airscan_devices` are correct.

### USB passthrough

- Attach the scanner before the addon starts.
- Restart the addon after reconnecting the device.
- If `scanimage -L` works only as root on another system, this usually indicates permissions or device mapping issues.

### Network scanner

- Prefer static DHCP reservations or a stable Brother nodename.
- For Brother devices, confirm registration with `brsaneconfig4 -q`.
- If driver installation fails, set generic SANE mode by leaving `brother_enable=false` or forcing `ENABLE_BROTHER_SUPPORT=false`.

## Validation Commands

Local checks used for this repository:

```bash
bash -n scanservjs/run.sh
node --check scanservjs/config.local.js
docker build -t ha-scanservjs-addon:test ./scanservjs
```

## Test Plan

Target environment: Home Assistant OS on `amd64`.

1. Add the repository to the Home Assistant Add-on Store.
2. Install the addon.
3. Start the addon and confirm it reaches the `started` state.
4. Open the web UI through ingress or port `8080`.
5. Verify scanner discovery with `scanimage -L`.
6. Perform a test scan and confirm the file lands in `copy_scans_to`.
7. Test OCR with `ocr_lang` set to a valid language pair.
8. Enable Brother support and verify `brsaneconfig4 -q` plus `scanimage -L`.

## Release Process

1. Ensure CI is green.
2. Confirm Home Assistant OS smoke tests passed.
3. Update `CHANGELOG.md` if needed.
4. Tag the release as `v1.0.0`.
5. Publish GitHub release notes.
