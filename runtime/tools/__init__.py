"""Built-in, production-quality Tool implementations.

`runtime.capabilities.tool` defines the abstract `Tool` contract and
`runtime.providers` holds concrete `AssistantProvider` integrations;
this package is the parallel home for concrete `Tool` integrations —
Filesystem, Shell, Git, Diff, and Test Runner. Every tool here runs
through the same pipeline as any other (`ToolRegistry`, `Command`,
`CommandExecutor`, `PermissionPolicy`, `AssistantHook`) and is never
auto-registered: like `runtime.providers.claude.ClaudeProvider`, an
integrator registers the tools it wants, with the sandbox roots and
policy appropriate to its deployment (see ADR 0016).
"""

from __future__ import annotations
