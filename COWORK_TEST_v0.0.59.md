You are running the live acceptance test for version 0.0.59 of our Bullhorn MCP connector (Sprint 44, CR45). It adds general file attachment: any allowed file can be uploaded and attached to a Candidate, Contact, Company, Job, Placement or Opportunity without parsing. The upload tools were renamed (`request_cv_upload` is now `request_file_upload`, `get_cv_upload` is now `get_file_upload`, `show_cv_upload_box` is now `show_upload_box`) and `attach_file` is new. Run every step yourself, including making the test files and uploading them. Do not ask me to upload anything, except where a step says I drop a file in the upload box. Report results at the end in the format given.

## Before the test (owner, not you)

Tick each box before starting. The old tool names no longer exist and there are no aliases, so a skill or prompt that still uses them will fail.

- [ ] v0.0.59 is deployed (`git pull`, `systemctl restart bullhorn-mcp.service`) and the Cowork connector is reconnected. The tool list shows 43 tools, including `attach_file`.
- [ ] Cowork skills and prompts use the new names: `request_file_upload`, `get_file_upload`, `show_upload_box`.
- [ ] Anywhere a skill passes `candidate_id` to the upload request, it now passes `entity="Candidate"` and `entity_id=<id>`. The `candidate_id` key is also gone from `get_file_upload`; the response has `entity`, `entity_id` and, once attached, `attached_entity` and `attached_entity_id`.
- [ ] Skills that read the success key of a match check now read `passed_match_check_id` (renamed in Sprint 43, m7).
- [ ] The new-job-setup skill attaches the letterheaded JD to the new job with `attach_file(entity="JobOrder", entity_id=<job id>, upload_id=...)` and no `type`.
- [ ] Claude Code (not Cowork) has created the test Placement and the test Opportunity with an inline `BullhornClient` script (owner approved 2026-11-13). Their ids are filled in below and recorded in IMPLEMENTATION-PLAN.md and the live test records. A Placement has no `isDeleted`, so it stays as test data.
  - Test Placement id: `<placement_id>`
  - Test Opportunity id: `<opportunity_id>`

## Ground rules (read first, follow throughout)

1. **Live data. Writes are allowed ONLY to these records:**
   - Candidate **173063** ("Testcase Cr-Fortyone");
   - JobOrder **51437**;
   - ClientCorporation **10666**;
   - ClientContact **145635**;
   - the test Placement `<placement_id>` and the test Opportunity `<opportunity_id>`.
   Never attach to, create, update or add notes to any other record. If a step would write anywhere else, stop and tell me.
2. **Attach only fake test files** that you make yourself, each with "TEST RECORD, CR45 acceptance" in the body or file name. Never attach a real person's document.
3. **Lead is write-refused.** The one Lead step (2.1) must be refused. If it is not refused, stop and tell me.
4. **Uploads:** for each file, call `request_file_upload(filename=<exact file name>)` (add `entity` and `entity_id` only where a step says so), send the file with the curl command it returns (`curl -sS -X POST -F file=@"<full path>" <upload_url>`), then check `get_file_upload(upload_id)` shows `received`. Tickets expire 15 minutes after they are issued, so upload right before you use one.
5. **Reading a record's files back:** use `get_<entity>` or `get_entity_fields`-guided reads with `fileAttachments(id,name,type)` where the entity supports it (for example `get_candidate(173063, fields="id,fileAttachments(id,name,type)")`). If a record's files cannot be read back with a tool, say so and give the `file_id` from the `attach_file` response; I will check in Bullhorn.
6. **Baseline (read live 2026-11-13).** Compare before and after against this. Files not listed here are not yours.
   - Candidate 173063: skillSet `[Excel, IFRS, Power BI]`; primarySkills Python, Financial Reporting, IFRS; 3 files: 326613 `cr41_test_candidate.docx` (no type), 326614 `cr41_test_candidate.pdf` (Original CV), 327585 `cr41_test_candidate.docx` (Original CV).
   - JobOrder 51437: 4 files: 327510 and 327511 `cr45_t44_1_probe.txt`, 327606 `cr45_t447_probe.png`, 327607 `cr45_t447_probe.eml`; none has a type.
   - ClientCorporation 10666: 19 existing files, including legacy labels such as "Terms of Business" (not on today's list) and probe files 896 to 898.
   - ClientContact 145635: no files.
   - Test Placement and Opportunity: no files.
7. **File type lists (this tenant).** Candidate, JobOrder, ClientContact, Placement and Opportunity: Original CV, Formatted CV, Cover Letter, References, Signed Contract, Proof of ID, Visa. ClientCorporation: Fee Agreement, Directions, Contract, Credit Check. The check is case-insensitive.
8. Note every id you get back (upload ids, file ids). If a step fails, record the exact error text, carry on with the steps that don't depend on it, and mark the dependent steps BLOCKED.

## Step 0: make the test files

Create these in your working folder. Use real files, not renamed text.

- `cr45_t448_jd.docx`: a short fake job description, "TEST RECORD, CR45 acceptance" at the top.
- `cr45_t448_cover_letter.pdf`: a short fake cover letter.
- `cr45_t448_contract.pdf`: a one-page fake contract.
- `cr45_t448_contact_note.txt`: one line of text.
- `cr45_t448_placement.docx` and `cr45_t448_opportunity.eml`: any small valid file of that type.
- `cr45_t448_sheet.xlsx`: any small spreadsheet (this one must be refused).
- `cr45_t448_image.png`: any small image (this one is for the parse_cv refusal).

## Part 1: attach_file on each entity

For each step: upload as in rule 4 (with the `entity` and `entity_id` hint where shown), call `attach_file`, then check `get_file_upload` and read the files back where you can.

1.1 **JD on a job, no label.** `request_file_upload(filename="cr45_t448_jd.docx", entity="JobOrder", entity_id=51437)`. After the file is sent, `get_file_upload(upload_id)` shows `entity` JobOrder and `entity_id` 51437 (`request_file_upload` itself does not echo them). Then `attach_file(entity="JobOrder", entity_id=51437, upload_id=..., description="CR45 acceptance JD")` with no `type`.
- Expected: `attached: true`, a `file_id`, `filename` `cr45_t448_jd.docx`, `type` empty or null, no warnings. Job 51437 now has 5 files, the new one has no type, and the four baseline files are unchanged.
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

1.2 **Cover letter on the candidate.** Upload `cr45_t448_cover_letter.pdf` with `entity="Candidate"`, `entity_id=173063`. `attach_file(entity="Candidate", entity_id=173063, upload_id=..., type="cover letter")` (lower case on purpose).
- Expected: attached, `type` comes back as `Cover Letter` (the tenant's spelling). Candidate 173063 has 4 files, the new one typed Cover Letter. The three baseline files are unchanged, and no parse ran (skillSet, work history and education unchanged).
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

1.3 **Contract on the company.** Upload `cr45_t448_contract.pdf` with `entity="ClientCorporation"`, `entity_id=10666`. `attach_file(entity="ClientCorporation", entity_id=10666, upload_id=..., type="Contract")`.
- Expected: attached with `type` `Contract`. Company 10666 has 20 files. The legacy "Terms of Business" files and probe files 896 to 898 are untouched.
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

1.4 **A file on the contact.** Upload `cr45_t448_contact_note.txt` with `entity="ClientContact"`, `entity_id=145635`. `attach_file(entity="ClientContact", entity_id=145635, upload_id=...)` with no `type`.
- Expected: attached, no type. Contact 145635 has 1 file.
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

1.5 **A file on the test Placement.** Upload `cr45_t448_placement.docx` with `entity="Placement"`, `entity_id=<placement_id>`. `attach_file(entity="Placement", entity_id=<placement_id>, upload_id=..., type="References")`.
- Expected: attached with `type` `References`.
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

1.6 **A file on the test Opportunity.** Upload `cr45_t448_opportunity.eml` with `entity="Opportunity"`, `entity_id=<opportunity_id>`. `attach_file(entity="Opportunity", entity_id=<opportunity_id>, upload_id=...)` with no `type`.
- Expected: attached, no type.
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

1.7 **Same-name re-attach warns.** Upload `cr45_t448_cover_letter.pdf` again (new ticket, same name) and call `attach_file` on candidate 173063 with `type="Cover Letter"`.
- Expected: the file is attached anyway (a second file with the same name), and the response `warnings` says a file with that name was already there. Nothing is blocked.
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

## Part 2: refusals (nothing may be written)

2.1 **Lead.** `request_file_upload(filename="cr45_t448_contact_note.txt", entity="Lead", entity_id=172990)`.
- Expected: refused with `unsupported_entity` ("Bullhorn does not allow files on leads..."), no ticket issued. Then call `attach_file(entity="Lead", entity_id=172990, upload_id=<a fresh upload of cr45_t448_contact_note.txt, requested with no entity hint>)`: also `unsupported_entity`. Nothing attached anywhere.
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

2.2 **Candidate-only label on a company.** Upload a fresh `cr45_t448_contract.pdf` ticket and call `attach_file(entity="ClientCorporation", entity_id=10666, upload_id=..., type="Cover Letter")`.
- Expected: `invalid_file_type_label`, listing the company's allowed values (Fee Agreement, Directions, Contract, Credit Check). Nothing attached; the upload stays `received` and can still be used. Then attach the same upload with `type="Fee Agreement"` to prove it is still usable (this adds a 21st file to company 10666).
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

2.3 **A type that is not allowed.** `request_file_upload(filename="cr45_t448_sheet.xlsx")`.
- Expected: refused, naming the allowed types: pdf, doc, docx, rtf, odt, txt, html, htm, png, jpg, jpeg, msg, eml. No ticket.
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

2.4 **A CV tool on a non-CV file.** Upload `cr45_t448_image.png` (allowed upload type) and call `parse_cv(upload_id=...)`.
- Expected: `not_a_cv_file`, with a pointer to `attach_file`. Nothing parsed or written. Also call `attach_cv(candidate_id=173063, upload_id=<the png upload>)` and expect the same refusal. Then attach the png to job 51437 with `attach_file(entity="JobOrder", entity_id=51437, ...)` and no type, to prove the upload still works for `attach_file`.
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

2.5 **Missing record.** With a received upload, call `attach_file(entity="JobOrder", entity_id=999999999, upload_id=...)`.
- Expected: `record_not_found`. Nothing attached.
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

## Part 3: get_file_upload and the upload box

3.1 After any successful `attach_file` in Part 1, call `get_file_upload(upload_id)`.
- Expected: `status: attached`, `filename`, `size`, `entity`, `entity_id`, plus `file_id`, `attached_entity` and `attached_entity_id` matching where the file went. There is no `candidate_id` key.
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

3.2 **Upload box in Cowork.** Request an upload for `cr45_t448_contact_note.txt` and do NOT use curl: call `show_upload_box(upload_id)`. The upload box should appear in the chat, never blank (on a handshake failure it shows an error). Tell me it is showing. I drop `cr45_t448_contact_note.txt` into it and the box shows `received`. Confirm with `get_file_upload`. Then attach it to contact 145635 with `attach_file` (this is a same-name file, so expect the warning from 1.7's rule).
- Expected: box renders with generic wording (not "CV"), file received, attach works.
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

3.3 **Upload box on claude.ai web.** Repeat 3.2 in a claude.ai web chat with the same connector (new ticket, same file, I drop it in). Attach to contact 145635 again.
- Expected: same result as Cowork. Record any difference.
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

## Part 4: one CV through the renamed tools

4.1 Upload `cr41_test_candidate.docx` (from `tests/fixtures/sample_cv/`, or make an equivalent fake CV) with `request_file_upload(filename="cr41_test_candidate.docx", entity="Candidate", entity_id=173063)` and curl. Call `parse_cv(upload_id)`, review it, then `attach_cv(candidate_id=173063, upload_id=...)` with no `overwrite`.
- Expected: `parse_cv` works on the new upload; additions are written and any differing field comes back in `pending_overwrites` and is NOT changed (do not accept any). The CV is attached with `type` `Original CV`. skillSet still holds Excel, IFRS and Power BI, each once. `get_file_upload` shows `attached_entity` Candidate and `attached_entity_id` 173063.
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

4.2 Confirm `get_file_upload` shows the hint from 4.1 (`entity` Candidate, `entity_id` 173063; `request_file_upload` itself does not echo it) and that the CV kept the label `Original CV` after `attach_cv`.
- [ ] PASS  [ ] FAIL  [ ] BLOCKED

## Part 5: the journal (owner runs this on the server)

5.1 After 3.2 and 3.3, run on the server: `journalctl -u bullhorn-mcp.service --since "1 hour ago" | grep "MCP App resource read"`.
- Expected: at least one line `MCP App resource read: ui://bullhorn/cv-upload-box.html` per box shown. (Before F10 the server never configured logging, so this line never appeared.) Also confirm the upload token does not appear in clear anywhere in the journal (`/upload/<redacted>`).
- [ ] PASS  [ ] FAIL

## Report

End with:
1. A table with these columns: step | expected | actual | PASS / FAIL / BLOCKED. Add one line of detail for anything that isn't PASS, including the exact error text.
2. Every id used or created: upload ids and file ids per step, and the final file counts per record against the baseline in rule 6.
3. Anything that looked wrong even if the step passed: confusing hints, slow calls (over 20 seconds), warnings that didn't read well, wording that still says "CV" where the file is not a CV.
4. A cleanup list: every file this test attached (record, file id, name), so I can delete them in Bullhorn. Do not delete anything yourself.
