# scanservjs Home Assistant Addon

## Description

This addon provides the `scanservjs` web UI for SANE scanners on Home Assistant OS systems. The updated addon targets `amd64` and keeps standard scanservjs/SANE behavior unchanged by default.

## Brother support

Brother support is optional and disabled by default.

- `brother_enable: true` enables the Brother startup workflow.
- `brother_accept_eula: true` is required before any proprietary `brscan4` driver download or installation is attempted.
- `brother_driver_source` supports `auto`, `url`, and `local`.
- `brother_register_scanner` can automatically register a network scanner with `brsaneconfig4`.
- Registration is idempotent and can be forcibly refreshed with `brother_overwrite_existing: true`.

Typical example for a Brother MFC-L2700DW:

```yaml
brother_enable: true
brother_accept_eula: true
brother_driver_source: auto
brother_scanner_name: MFC_L2700
brother_scanner_model: MFC-L2700DW
brother_scanner_ip: 192.168.1.50
```

## Notes

- Network scanners are the preferred setup for containerized scanservjs deployments.
- USB scanners should be connected before the addon starts; if the device is replugged, restart the addon.
- Scanned files are copied to `copy_scans_to` after each scan. The default destination is `/share/paperless/consume`.
