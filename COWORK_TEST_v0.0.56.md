You are running the live acceptance test for version 0.0.56 of our Bullhorn MCP connector. It adds three things: CV uploads that you review and correct before anything is written (CR43), a weighted duplicate check on every candidate create (CR44), and match logging. Run every step yourself, including making the test files and uploading them. Do not ask me to upload anything. Report results at the end in the format given.

## Ground rules (read first, follow throughout)

1. **Live data. Writes are allowed ONLY to:**
   - Candidate **173063** ("Testcase Cr-Fortyone"), the approved test candidate;
   - candidates **you create in this test** from the invented people below.
   Never create, update, attach to or add notes to any other record. If a step would write anywhere else, stop and tell me.
2. **Every person you invent is obviously fake.** Use these names, `@example.com` emails, phone numbers starting `+353 87 555`, and put "TEST RECORD, CR43/CR44 acceptance" at the top of every CV.
3. **Real candidates are read-only.** On real data, only use `find_duplicate_candidates`, `get_candidate`, `list_candidates` and `search_entities`. In the report, give real-data results as bands and counts only, never names, emails or phone numbers.
4. **Never pass `force=True`** unless a step tells you to.
5. **Uploads:** for each file, call `request_cv_upload(filename=<exact file name>)`, then send the file with the curl command it returns (`curl -sS -X POST -F file=@"<full path>" <upload_url>`), then check `get_cv_upload(upload_id)` shows `received`. Uploads expire 15 minutes after the ticket is issued, so upload right before you use one.
6. **Reading a candidate back:** use `get_candidate(id, fields="id,firstName,lastName,email,mobile,occupation,companyName,skillSet,primarySkills(id,name),fileAttachments(id,name,type)")`. For history use `query_entities(entity="CandidateWorkHistory", where="candidate.id=<id>")` and `query_entities(entity="CandidateEducation", where="candidate.id=<id>")`.
7. Note every id you get back (candidate ids, upload ids, match_check_ids, file ids). If a step fails, record the exact error text, carry on with the steps that don't depend on it, and mark the dependent steps BLOCKED.

## Step 0: make the test files

Create these files in your working folder. Use real .docx and .pdf files, not renamed text.

**Person A, "Testcase Crfortythree Alpha":** email `testcase.alpha@example.com`, mobile `+353 87 555 0143`, LinkedIn `https://www.linkedin.com/in/testcase-crfortythree-alpha`. Occupation "Financial Controller". Work history: Wibblecorp Testing Ltd, Financial Controller, Jan 2021 to now; Wobble Example Holdings, Senior Accountant, Mar 2016 to Dec 2020. Education: University College Testshire, BComm, 2015; Chartered Accountants Ireland, ACA, 2018. Skills: Excel, IFRS, Consolidation, Budgeting.
- `Testcase_Alpha_CV.docx`: the full CV above.
- `Testcase_Alpha_CV_v2.pdf`: the same person and the same email and mobile, but occupation "Head of Finance". Add one extra job at the top (Quuxworks Demo Plc, Head of Finance, Feb 2025 to now) and the extra skill "Power BI".
- `Testcase_Alpha_CV.txt`: the plain-text content of the docx.

**Person B, "Testcase Crfortyfour Bravo":** email `testcase.bravo@example.com`, mobile `+353 87 555 0144`, occupation "Payroll Specialist", one job at Fizzbuzz Sample Services (2019 to now), education: Testshire Institute, Diploma in Payroll, 2018. Skills: Payroll, Excel. No CV file is needed for B.

**A file that should be rejected:** `not_a_cv.png`, any small image.

## Part 1: upload plumbing

1.1 Request an upload for `not_a_cv.png`. Expect a refusal naming the allowed types (pdf, doc, docx, rtf, odt, txt, html). Nothing is created.
1.2 Upload `Testcase_Alpha_CV.docx` with the curl route. Expect `get_cv_upload` = `received`, with the original file name.
1.3 Request a second upload for `Testcase_Alpha_CV_v2.pdf`, but this time do NOT use curl: call `show_cv_upload_box(upload_id)` and tell me it is showing. I will drop the file into the box. Then confirm `received`. If the box doesn't render or my upload fails, record the exact error, re-request the upload, send it with curl instead, and mark 1.3 FAIL.

## Part 2: parse and review (nothing written)

2.1 `parse_cv(upload_id)` on the docx. Check the parse against what you wrote in Step 0 and list anything the parser got wrong or missed. Expect a `duplicate_check` block with a `match_check_id` and no high match (Person A is new). Confirm nothing was written to Bullhorn.

## Part 3: create from CV with your corrections (CR43)

3.1 `create_candidate_from_cv(upload_id=<docx upload>)`, passing your corrections from 2.1 as `fields_override`, `work_history`, `education`, `skills` and `primary_skills`. Only pass `primary_skills` if you found matching Skill ids; otherwise leave it out and say so. Pass the `match_check_id` from 2.1. Expect `created`, a new candidate id, and a report of what was written.
3.2 Read the new candidate back (rule 6) and check:
   - name, email, mobile and occupation are your corrected values;
   - one work history row per job and one education row per entry, with no duplicates and no raw-parse rows next to the corrected ones;
   - `skillSet` holds the skill names as free text;
   - `primarySkills` holds the ids you passed (this is separate from the `skillSet` text);
   - `fileAttachments` has the CV under its original name, `Testcase_Alpha_CV.docx`, with type CV;
   - `get_cv_upload` reports `attached`.
3.3 Call `attach_cv(candidate_id=<new id>, upload_id=<docx upload>)` again. Expect the file-only path: nothing re-written, no raw-parse entries added, and a note that corrections are ignored.

## Part 4: the duplicate check stops a second create (CR44)

4.1 Upload `Testcase_Alpha_CV_v2.pdf` (or use the 1.3 upload if it's still `received`). Call `create_candidate_from_cv` with it, with no force. Expect `duplicate_found` (same email and mobile), nothing created, Person A's new id listed with a percentage, band and reasons, and a hint that names `attach_cv(candidate_id=..., upload_id=..., match_check_id=...)`. Show me the reasons exactly as returned.
4.2 Follow the hint: `attach_cv` on Person A with the v2 upload and the `match_check_id`, without `confirm`. Expect:
   - additions written straight away (the Quuxworks job and the Power BI skill);
   - `pending_overwrites` listing occupation ("Financial Controller" to "Head of Finance") and nothing else that matters;
   - occupation NOT changed yet. Check with `get_candidate`.
4.3 Repeat the same call with `confirm=True`. Expect occupation to become "Head of Finance". Nothing added in 4.2 is added twice, and the file is not attached twice.

## Part 5: the text path and create_candidate

5.1 `parse_cv_text` with the contents of `Testcase_Alpha_CV.txt`. Expect a parse plus a `duplicate_check` that finds Person A.
5.2 `create_candidate_from_cv(content=<the txt contents>)`, with no force. Expect a duplicate stop whose hint names `update_record`, NOT `attach_cv` (there is no upload on the text path). Nothing created.
5.3 `create_candidate` for Person B with fields, `work_history`, `education` and `skills` from Step 0. Expect `created`, and a duplicate check that ran with no high or uncertain match. Check B's work history, education and skills with `get_candidate`.
5.4 `create_candidate` for Person B again, same fields, no force. Expect `duplicate_found` with an email reason. Nothing created.

## Part 6: the approved test candidate 173063

6.0 Before anything else, read 173063 back (rule 6) and keep the result. Expected today: 2 work history rows, 2 education rows, no skills and no file attachments.
6.1 Upload `Testcase_Alpha_CV.docx` again (new ticket) and call `attach_cv(candidate_id=173063, upload_id=...)` without `confirm`. 173063 is a different fake person, so expect many `pending_overwrites` (name, email and so on). Do NOT confirm. List the additions that were written and the overwrites that were held back. Read it back again and compare with 6.0: no existing value changed, and only the listed additions were added.
6.2 Confirm the file is attached to 173063.

## Part 7: duplicate check on real data (read-only, dry run)

7.1 Known trigger case: `find_duplicate_candidates(first_name="Kevin", last_name="Cassidy")`, then the same call with the email and mobile from candidate 90308 (read them with `get_candidate(90308)`, but don't include them in the report). Expect 90308 and the other live Kevin Cassidy record in the high band with reasons, and the soft-deleted one under `deleted_matches`, not `matches`. Report bands and counts only.
7.2 Self-match sanity: take the 5 most recently added real candidates (`list_candidates`) and run `find_duplicate_candidates` on each with their name, email, mobile and current company. Each should find itself at high. Report the 5 bands, and any other high or uncertain matches as counts only.
7.3 Common-name check: `find_duplicate_candidates(first_name="John", last_name="Murphy")` with no other details. Expect no high match: a name alone must not reach high. Report the band counts.

## Report

End with:
1. A table with these columns: step | expected | actual | PASS / FAIL / BLOCKED. Add one line of detail for anything that isn't PASS, including the exact error text.
2. Every id created or used: Person A and B candidate ids, upload ids, match_check_ids, file ids.
3. Parser accuracy notes from 2.1.
4. Anything that looked wrong even if the step passed: confusing hints, slow calls (over 20 seconds), odd percentages, or reasons that didn't make sense.
5. A cleanup list: every record this test created, so I can archive or delete them in Bullhorn. Do not delete anything yourself.
