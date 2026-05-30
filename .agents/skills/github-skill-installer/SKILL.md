---
name: github-skill-installer
description: Installs a skill from a GitHub repository using `gh skill install`. Trigger this skill whenever the user provides a GitHub repository name (like owner/repo) or a URL and asks to install it as a skill.
---

# GitHub Skill Installer

You are helping the user install a skill from a GitHub repository.

## Instructions

1. Identify the GitHub repository the user wants to install (e.g., `anthropics/skills`).
2. Identify the specific skill name if the user provided one (e.g., `skill-creator`). If not provided, you can just install the repository or ask the user to specify.
3. Execute the installation command:
   ```bash
   GH_HOST=github.com gh skill install <owner>/<repo> [skill-name] --agent antigravity
   ```
4. If the installation fails due to a missing skill name but prompts you to select one, parse the error or output and let the user know what's available, or ask them to clarify.
5. Report the success or failure of the installation back to the user.
