# Repository instructions

These instructions apply to the entire repository and all its subdirectories.

## Spec-driven development

The root [`spec.md`](spec.md) is the source of truth for requirements and application behavior.

For every new requirement, feature, bug fix, or change to application behavior:

1. Read `spec.md` and the relevant implementation before making changes.
2. **Update `spec.md` before writing or modifying implementation code.** Describe the intended behavior, affected contracts and constraints, and acceptance criteria. Reuse existing requirement IDs where appropriate; assign stable IDs to new requirements.
3. Clearly mark new or changed behavior as **planned / not yet implemented** while work is pending. Preserve the distinction between current behavior and intended behavior.
4. Implement the change to satisfy the updated specification. If scope changes during implementation, update the specification first again.
5. Run relevant checks and tests against the acceptance criteria. Update the specification's implementation status and verification notes to reflect the actual outcome; do not claim unverified behavior is tested.
6. Deliver the specification update together with the implementation. Do not leave code and specification describing different behavior.

If a requested implementation is absent from or conflicts with `spec.md`, update the specification first within the authorized task scope. Ask for clarification only when the intended behavior cannot reasonably be determined.

For internal refactors, document the intended change and the behavior that must remain unchanged in `spec.md` before modifying implementation code. Documentation-only edits that do not change requirements or application behavior do not require an artificial specification change.
