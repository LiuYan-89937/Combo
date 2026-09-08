# Vendored Computer Use engine

Source: https://github.com/iFurySt/open-codex-computer-use
Revision: `1571a4eecf325cba4bc9ae2af36b74f8c2d00105`.

## Contents and adaptations

- `Sources/OpenComputerUseKit`: upstream Swift core, excluding `MCPServer.swift`. Server instructions are extracted into `Instructions.swift`; tool definitions/results and execution logic are retained.
- `Sources/ComboCUBridge`: C ABI dispatch invoked on the host AppKit main thread. Session dispatchers preserve upstream state across calls.
- Permissions use the embedding application's bundle identity and only its running bundle location, instead of locating a separately installed upstream app.
- The upstream software cursor PNG is included in host resources. Its development fallback points to the relocated source resource directory.
- `windows`: upstream Go service code before the CLI entrypoint, minus the now-unused `io` import; embedded PowerShell runtime. `bridge.go` supplies private stream dispatch in place of CLI/MCP transport.
- MIT license and third-party notices are retained. Upstream application heuristics are retained as source behavior, not newly authored Combo rules.

## Build and runtime requirements

Cargo's `src-tauri/build.rs` builds and stages the current platform engine, including for ordinary development builds. macOS requires Swift 6.2+ and macOS 14+; SwiftPM produces `libComboCU.dylib`, linked by Rust and bundled as a Tauri framework. Windows require Go 1.22+ and run a bundled `combo-cu` worker. Artifacts are also copied beside the Cargo executable for direct development runs.

Windows runtime requires Windows PowerShell and UI Automation. Linux CU and Linux release jobs have been removed; Combo distributes macOS and Windows only.

The Python CU loop retrieves upstream schemas and instructions at runtime. No MCP listener, client configuration or registration is needed. The authenticated local transport exists only between Combo components.

The current macOS distribution uses ad-hoc signatures (`signingIdentity: "-"`). The host keeps Hardened Runtime enabled and declares `com.apple.security.cs.disable-library-validation` in `src-tauri/entitlements.plist`, because ad-hoc signatures cannot satisfy the same-Team-ID check when loading the Swift library. This entitlement permits libraries without a matching Team ID; it is not restricted to the CU library. Tauri applies it during signing, before creating updater artifacts. When migrating to Developer ID distribution, sign all embedded libraries with the same team and remove this entitlement if no other component needs it. Deep signature verification alone does not establish runtime library-validation compatibility.

## Verification boundary

This migration was checked by source comparison and syntax parsers only. Compilation, native linkage, packaged resource lookup, platform permission behavior and actual UI interaction have not been executed. Syntax checks do not establish runtime availability or cross-platform parity.

The original transplant was compared against upstream; the input contract is now an intentional divergence. See `../../combo/computer_use/README.md` for target, selection and readback semantics. Current changes are syntax-checked only; no compilation or platform interaction has been performed.
