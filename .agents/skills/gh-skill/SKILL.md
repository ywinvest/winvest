---
name: gh-skill
description: Manage, search, and install AI agent skills using the GitHub CLI (gh skill). Make sure to use this skill whenever the user asks to find, download, or install an agent skill. This skill implements a robust fallback search logic to guarantee finding the best available skill.
---

# gh-skill

You are the manager of agent skills. Your job is to help the user discover, search, and install new skills into their `.agents/skills` directory using the `gh skill` CLI tool.

## Critical Requirement
You **MUST** prepend `GH_HOST=github.com` to ALL `gh skill` commands to bypass enterprise server contexts and access the public GitHub repository.

## Installation Workflow
When the user asks you to find and install a skill, you must execute the following 4-step Fallback Logic sequentially. Do not stop until you either find and install the skill, or exhaust all steps.

### Step 1: General Search
Run a basic global search to see if there is an exact or highly relevant match.
```bash
GH_HOST=github.com gh skill search <keyword>
```
If you find a suitable skill from a reputable owner in the results, skip to Step 4.

### Step 2: Filter by Curated Repositories
Since the global search can return low-quality or malicious skills, you MUST first search specifically within the trusted curated repositories using the `--owner` flag:

Run the following commands sequentially to search within trusted organizations:
```bash
# 1. GitHub Official (awesome-copilot)
GH_HOST=github.com gh skill search "<keyword>" --owner github
# 2. Anthropic Official
GH_HOST=github.com gh skill search "<keyword>" --owner anthropics
# 3. OpenAI Official
GH_HOST=github.com gh skill search "<keyword>" --owner openai
# 4. Google Official
GH_HOST=github.com gh skill search "<keyword>" --owner google-gemini
GH_HOST=github.com gh skill search "<keyword>" --owner google
# 5. Community Curated
GH_HOST=github.com gh skill search "<keyword>" --owner VoltAgent
GH_HOST=github.com gh skill search "<keyword>" --owner sickn33
```
If you find a suitable skill here, skip to Step 4.

### Step 3: Global Search by Stars (Fallback)
If Step 2 also fails, perform a global search and output JSON to find the skill with the highest number of stars:
```bash
GH_HOST=github.com gh skill search <keyword> --json stars,namespace,skillName
```
Parse the JSON output and select the skill with the highest `stars` count.

### Step 4: Install and Audit
Once a target skill is identified (from Step 1, 2, or 3), install it targeting the `.agents` protocol:
```bash
GH_HOST=github.com gh skill install <owner/repo> <skill-name> --agent antigravity
```
*Note: The CLI expects `<repository>` and `<skill>` separated by a space (e.g., `anthropics/skills skill-creator`).*

**CRITICAL (Audit & Report):**
After successful installation, you MUST read the downloaded `SKILL.md` file (e.g., `cat .agents/skills/<skill-name>/SKILL.md`). 
- Review the instructions for any malicious intent or destructive shell commands.
- Report a brief summary of what the newly installed skill does to the user.
- **Selection Basis**: Explicitly state to the user *why* this specific skill was chosen (e.g., "Found an exact match in the curated `github/awesome-copilot` repository" or "Selected as the highest starred skill (362 stars) from the global fallback search").

### Step 5: Update Skills Registry
To maintain a clear history of installed skills, append/update an entry for the newly installed skill in `.agents/skills/README.md`.
**Important**: Ensure the `> ⚠️ **DO NOT EDIT**` warning at the top of the file remains untouched.
Use the following Markdown table format, ensuring the Skill Name is a clickable link to its folder:
| Skill Name | Source Repository | Stars/Basis | Summary |
|------------|-------------------|-------------|---------|
| [`skill-name`](./skill-name) | `owner/repo` | (e.g., Curated repo, or 362 stars) | Brief summary of what the skill does |

