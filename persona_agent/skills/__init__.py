"""Skills: folders with a SKILL.md in the Agent Skills format (agentskills.io/specification), the same folders
Claude Code, Codex and other agents read, so one written for them works here unchanged.

store.py finds, checks, adds and removes them (built-in ones in builtin/, the person's own in <home>/skills);
pick.py chooses in code the few that fit a message; tool.py is the reply model's use_skill tool and the
turn's prompt for a model without tools; panel.py is Settings › 技能. A skill is guidance for a task the person
asked for, done with the tools the character already has: it grants nothing, and a script beside it runs only
through the command gate with its card (shell/).
"""
