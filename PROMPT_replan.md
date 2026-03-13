0a. Study @AGENTS.md. **STRICTLY FOLLOW THE INSTRUCTIONS IN AGENTS.MD**  
0b. Study @PRD.md and any CRx.md files (if present) to understand the product requirements and any change requests.  
0b. Study @IMPLEMENTATION-PLAN.md (if present) to understand the plan so far.  
0c. Study all files and subfolders with up to 250 parallel Sonnet subagents to understand components.

Once you have studies all the files, proceed to update the implementation plan as follows:

1. Validate and update the implementation plan, following these steps:

* @PRD.md contains user stories that implement the functional requirements and non-functional requirements.
* Validate that there is full coverage of the requirements in the user stories, and also whether there are user stories that implement features which are not in the requirements.
* **Stop and check** with the human if there are any discrepancies.

2. Validate and update implementation plan, following these steps:

* The plan should break the user stories into tasks and then group those tasks into a "sprint" which would be the amount of work achieveable by an AI coding agent within an estimated 100,000 token context window.
* Each task should be discretely testable and have defined unit tests.
* Each sprint should target completing with working code and define end-to-end tests of all tasks that make up that sprint, and define end-to-end testing of all sprint outputs to this point.
* There may be tasks left over from a previous Sprint, and they must be prioritised to be included in the forthcoming Sprint.

3. Confirm the implementation plan status, following these steps:

* Use up to 500 Sonnet subagents to study existing source code and compare it against the plan. Use an Opus subagent to analyze findings, prioritize tasks, and create/update @IMPLEMENTATION-PLAN.md sprints and tasks, confirming completed + tested tasks, and the tasks yet to be implemented. Ultrathink. Consider searching for TODO, minimal implementations, placeholders, failed/skipped/flaky tests, and inconsistent patterns. Study @IMPLEMENTATION-PLAN.md to determine starting point for research and keep it up to date with items considered complete/incomplete using subagents.

IMPORTANT: Plan and update @IMPLEMENTATION-PLAN.md only. Do NOT implement any code. Do NOT assume functionality is missing; confirm with code search first. Prefer consolidated, idiomatic implementations there over ad-hoc copies.

ULTIMATE GOAL: Implement the requirements from @PRD.md. Consider missing elements and plan accordingly. If an element is missing, search first to confirm it doesn't exist, then if needed author the specification at @PRD.md. If you create a new element then document the plan to implement it in @IMPLEMENTATION-PLAN.md using a subagent.

FINALLY: Write out any planned changes and update complete or incomplete status to the IMPLEMENTATION-PLAN.md and stop. Do not offer to perform any implementation of the plan.

