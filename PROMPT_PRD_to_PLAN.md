0a. Study @AGENTS.md. **STRICTLY FOLLOW THE INSTRUCTIONS IN AGENTS.MD**  
0b. Study @PRD.md and any CRx.md files (if present) to understand the product requirements and any change requests.  
0c. Study @IMPLEMENTATION-PLAN.md (if present) to understand the plan so far.

1. Validate and update implementation plan, following these steps:

* @PRD.md contains user stories that implement the functional requirements and non-functional requirements.
* Validate that there is full coverage of the requirements in the user stories, and also whether there are user stories that implement features which are not in the requirements.
* **Stop and check** with the human if there are any discrepancies.

2. Validate and update implementation plan, following these steps:

* If @IMPLEMENTATION-PLAN.md does not exist you must create it. If @IMPLEMENTATION-PLAN.md does not comply with this structure then it should be rewritten.
* The plan should break the user stories into tasks and then group those tasks into a "sprint" which would be the amount of work achieveable by an AI coding agent within an estimated 100,000 token context window.
* Each task should be discretely testable and have defined unit tests.
* Each sprint should target completing with working code and define end-to-end tests of all tasks that make up that sprint, and define end-to-end testing of all sprint outputs to this point.
