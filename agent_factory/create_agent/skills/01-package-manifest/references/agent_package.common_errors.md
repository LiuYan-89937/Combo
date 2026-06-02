# Common Errors

- Referencing files that do not exist inside the package workspace.
- Using absolute paths instead of package-relative paths.
- Putting secrets or user-specific runtime values into `agent_package.json`.
- Adding top-level fields not accepted by `AgentPackageLoader`.
