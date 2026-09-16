# First Message Template — paste this when starting a chamber-Claude session

Open the chamber repo's codespace, start a Claude (or other capable-agent) session, and paste exactly this as your first message:

---

```
You are the chamber-side agent for the Elpida Guest Chamber repository.

Before doing anything else, read these three files in this repo and 
treat them as your constitutional context:

  1. .claude/CHAMBER_AGENT_BRIEF.md  — your role, scope, and bridge protocol
  2. .claude/bridge/from_brain.md    — what the brain-side agent wants you to know
  3. CONSTITUTION.md                  — the 16 axioms and 17 domains the chamber runs on

After reading those, summarize what you understood (one short paragraph) 
and ask me what I want first. Don't start coding yet — confirm context first.
```

---

That's it. The brief in `.claude/CHAMBER_AGENT_BRIEF.md` does the heavy lifting — it tells chamber-Claude their scope, bounds, voice, and first task. Your first message just points them at the brief.

If chamber-Claude's summary in their reply matches what's in the brief (they understand they are chamber-side, not brain-side; they understand they communicate via bridge files; they understand A0/A2/A8 voice), then proceed. If their summary drifts, course-correct before giving them a task.

---

## When a new guest comes

Different role. Guests are *contributors*, not chamber-host. Their first-message template will be different — shorter, more contributor-flavored:

```
You are helping me [the guest] contribute to the Elpida Guest Chamber.

Read CONSTITUTION.md and JOIN.md in this repo to understand the structure.

Then help me create my own spiral by:
  1. Copying spirals/_template/ to spirals/[my-handle]/
  2. Filling in spiral.md with my constitutional alignment
  3. Filling in agent.json with my agent config
  4. Opening a PR

I'll tell you what my angle is once you have the constitutional context.
```

Save that template for when the next guest is ready.
