# pre-release-0.6

## New in this pre-release

- Configurable work directory for extract/repack jobs (for SSD/RAM-disk workflows)
- Optional compression thread control (`compression_threads`, 0 = auto)
- Live system status in UI (CPU usage, RAM usage, load average, uptime)
- Top navigation bar with sections: Dashboard, Settings, What's new, About
- In-app release notes view (`What's new`)
- Language selector available in top bar
- Improved runtime diagnostics and debug scan output

## Notes

- CPU usage first sample may show as `sampling...` until the second status refresh.
- Compression speed depends on archive type, storage speed, and selected thread count.