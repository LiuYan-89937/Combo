# Bundled Resources

This directory will contain resources bundled with the application:

## Python Runtime (Production Builds)

For production builds, place the python-build-standalone distribution here:

```
resources/
  python/
    bin/python3           # Python interpreter (Unix)
    python.exe            # Python interpreter (Windows)
    lib/                  # Python standard library
    site-packages/        # Installed packages
```

Download python-build-standalone from:
https://github.com/indygreg/python-build-standalone/releases

Choose the appropriate architecture:
- macOS: `cpython-3.12.x-aarch64-apple-darwin-install_only.tar.gz` (Apple Silicon)
- macOS: `cpython-3.12.x-x86_64-apple-darwin-install_only.tar.gz` (Intel)
- Windows: `cpython-3.12.x-x86_64-pc-windows-msvc-shared-install_only.tar.gz`
- Linux: `cpython-3.12.x-x86_64-unknown-linux-gnu-install_only.tar.gz`

## Development Mode

In development, the system Python is used. No bundled runtime needed.
