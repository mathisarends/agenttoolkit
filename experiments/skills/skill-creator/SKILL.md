---
name: skill-creator
description: Create or update reusable agent skills from workflows, files, tools, or repeated user requests. Use when the user asks the agent to capture, improve, test, or maintain a skill.
---

# Skill Creator

Create compact, reliable skills that another agent can apply without
rediscovering the workflow.

## Scope

A skill is a self-contained folder for repeatable workflows, tool-specific
procedures, project conventions, or reusable resources. Do not create one for
facts that should be looked up fresh, one-off results, or instructions the agent
already follows reliably.

## Principles

Assume the receiving agent is capable.

- Include only non-obvious, reusable guidance.
- Write instructions in imperative form.
- Require observable validation, not confidence statements.
- Never store credentials, tokens, or transient secrets.

## Structure

Every skill requires `skill-name/SKILL.md`. Add only needed resources:

```text
skill-name/
|-- SKILL.md
|-- scripts/
|-- references/
`-- assets/
```

- Use `scripts/` for executable, deterministic operations.
- Use `references/` for detailed documentation, schemas, or policies.
- Use `assets/` for templates, media, or output boilerplate.

Do not add empty directories, READMEs, changelogs, installation guides, or
process notes unless the runtime requires them.

## SKILL.md

Use this minimal form:

```markdown
---
name: example-skill
description: Perform a specific workflow. Use when the user asks for the relevant task or works with the relevant artifact.
---

# Example Skill

1. Inspect the input.
2. Follow the workflow.
3. Validate the result.
```

The `name`:

- Must match the parent folder.
- Must contain only lowercase letters, digits, and single hyphens.
- Must not start or end with a hyphen.
- Must be at most 64 characters and preferably action-oriented.

The `description` is the trigger:

- Say what the skill does and when to use it.
- Include relevant task, tool, and artifact terms.
- Keep trigger guidance out of the body.

The body:

- Describe the operational workflow.
- Name resources and when to read or run them.
- Define observable success checks.
- Avoid repeating the frontmatter.

## Progressive disclosure

Keep selection and core workflow in `SKILL.md`; move optional detail into directly
linked resources and load only what the current task needs.

## Creation workflow

Follow these steps in order. Skip one only when it clearly does not apply.

### 1. Understand

Inspect relevant files, tools, commands, and existing skills.

Identify:

- Two or three realistic prompts that should trigger the skill.
- Expected observable outputs.
- Common failure modes.
- Stable knowledge versus facts that must be rediscovered.
- The target skill directory.

Ask only for choices that materially change the result and cannot be inferred
safely.

### 2. Plan

Mentally execute each use case from scratch, then decide:

- Which instructions belong in `SKILL.md`.
- Which repeated mechanical steps deserve scripts.
- Which detailed knowledge belongs in references.
- Which templates or output materials belong in assets.

Avoid duplication between files.

### 3. Initialize

Create under `/skills/<skill-name>` unless the user selects another writable root:

```bash
python /skills/skill-creator/scripts/init_skill.py <skill-name> --path /skills
```

Add `--resources scripts,references,assets` with only needed directories. Replace
every generated TODO.

Before changing an existing skill:

- Read its current files.
- Preserve useful behavior and user-owned resources.
- Change only what the request requires.

### 4. Implement and test resources

Create reusable resources before finalizing the instructions.

For every new or changed script:

1. Inspect inputs and side effects.
2. Run a representative normal case.
3. Run a meaningful edge or failure case.
4. Check exit status and produced artifacts.
5. Fix failures and rerun affected cases.

Never claim a script works without executing it.

If a dependency, permission, device, or live service prevents execution, state the
exact limitation and test the largest safe portion possible.

### 5. Write

Describe the shortest reliable workflow discovered during implementation.

Include:

- Required inspection and decision rules.
- Exact commands only where precision matters.
- Resource paths relative to the skill folder.
- Validation and recovery steps.

Exclude:

- Generic advice the agent already knows.
- Similar examples that teach the same behavior.
- History of how the skill was written.
- Unsupported claims about tools or environments.

### 6. Validate

Re-read every changed file and run:

```bash
python /skills/skill-creator/scripts/quick_validate.py /skills/<skill-name>
```

Confirm:

- Folder and frontmatter names match.
- YAML is valid and the description triggers correctly.
- Referenced files and commands exist in the target environment.
- No placeholders, secrets, stale facts, or needless content remain.

A newly named skill enters this chat's catalog after restart.

## Behavioral testing

Do not stop after reviewing prose. Test:

- One ordinary case.
- One edge case.
- One non-triggering case when trigger precision matters.

For each positive case:

1. Apply the skill as a receiving agent would.
2. Capture commands, outputs, artifacts, and errors.
3. Compare them with the expected observable outcome.
4. Fix the smallest general cause of any failure.
5. Repeat the failure and a normal case from the beginning.

Prefer a fresh agent or conversation. Give it the skill path and a realistic
request, but not the expected answer, suspected defect, or intended fix.

If no fresh-agent runner exists, test directly and disclose that the result was
not context-independent.

Use raw evidence such as tool traces, diffs, artifacts, and validation reports.
Avoid contaminating later rounds with earlier test artifacts.

Stop when representative cases succeed, failures are safe and understandable,
instructions match resources, and further additions do not improve execution.

## Completion

- Report the skill path and changed resources.
- Report scripts and behavioral cases actually run.
- Report any untested dependency or live-system limitation.
- Never describe validation that did not occur.
