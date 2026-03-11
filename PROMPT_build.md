0a. Study @AGENTS.md. **STRICTLY FOLLOW THE INSTRUCTIONS IN AGENTS.MD**
0b. Study @PRD.md and any CRx.md files (if present) for the requirements and any change requests.
0c. Study @IMPLEMENTATION-PLAN.md for current tasks. 
**If @IMPLEMENTATION-PLAN.md does not exist Stop and alert the human**  

Once you have read and understood all three files, and have had an opportunity to quickly review the codebase, implement the following instructions:

1. Your task is to implement functionality per the plan using parallel Sonnet subagents.  You only work on one Sprint at a time.  When the Sprint has been completed, stop and await instructions.  

2. Implementation Plan:  
- Follow @IMPLEMENTATION-PLAN.md  
- The plan breaks the user stories into tasks and then groups those tasks into a "sprint" which is the amount of work achieveable by you within an estimated 100,000 token context window. Each task is discretely testable and the sprint should also end with working code that is separately testable.  
- Each task will finish with unit testing. If it does not pass, a quick fix may be performed quickly and restested. A more involved fix must be documented and added as a task for the next sprint.  
- Each sprint should target completing with working code and pass end-to-end test of all tasks that make up that sprint and previous sprints. If tests fail, and cannot be quickly fixed, then the required fix must be documented as a task for the next sprint.  

2. All testing must be executed in the .venv environment.  

3. After implementing functionality or resolving problems, run the tests for that unit of code that was improved. If functionality is missing then it's your job to add it as per the application specifications. Ultrathink.  

4. When test fail or you discover issues, immediately update @IMPLEMENTATION-PLAN.md with your findings using a subagent. When resolved, update and remove the item. If and item cannot be resolved then fully document it for the next Sprint planning.  

5. When the tests pass, update @IMPLEMENTATION-PLAN.md, then commit with a message describing the changes. After the commit, `git push`.  

6. Work on only one Sprint at a time. Do not move on to the next Sprint.  

99999. Important: When authoring documentation, capture the why — tests and implementation importance.
999999. Important: Single sources of truth, no migrations/adapters. If tests unrelated to your work fail, resolve them as part of the increment.
9999999. As soon as there are no build or test errors create a git tag. If there are no git tags start at 0.0.0 and increment patch by 1 for example 0.0.1  if 0.0.0 does not exist.
99999999. You may add extra logging if required to debug issues.
999999999. Keep @IMPLEMENTATION-PLAN.md current with learnings using a subagent — future work depends on this to avoid duplicating efforts. Update especially after finishing your turn.
9999999999. When you learn something new about how to run the application, update @AGENTS.md using a subagent but keep it brief. For example if you run commands multiple times before learning the correct command then that file should be updated.
99999999999. For any bugs you notice, resolve them or document them in @IMPLEMENTATION-PLAN.md using a subagent even if it is unrelated to the current piece of work.
999999999999. Implement functionality completely. Placeholders and stubs waste efforts and time redoing the same work.
9999999999999. When @IMPLEMENTATION-PLAN.md becomes large periodically clean out the items that are completed from the file using a subagent.
99999999999999. If you find inconsistencies in the specs/* then use an Opus subagent with 'ultrathink' requested to update the specs.
999999999999999. IMPORTANT: Keep @AGENTS.md operational only — status updates and progress notes belong in `IMPLEMENTATION-PLAN.md`. A bloated AGENTS.md pollutes every future loop's context.