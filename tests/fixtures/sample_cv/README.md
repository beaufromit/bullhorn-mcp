# Sample CV fixtures (CR41, T40.8)

`cr41_test_candidate.docx` and `cr41_test_candidate.pdf` are CVs for a fictional person, "Testcase Cr-Fortyone". Both carry "TEST RECORD, NOT A REAL PERSON" in the body, a fake email (testcase.cr41@example.com), a fake phone number (+353 1 555 0141) and fictional employers, so Bullhorn's resume parser has fields to extract.

They are for the T40.8 live acceptance of CR41 (upload tickets): upload one through `request_cv_upload` and `curl`, then run `create_candidate_from_cv` or `attach_cv`. Any Candidate record created from them is a test record and should be cleaned up afterwards. They are not used by the automated test suite.

Generated on 2026-09-29 with python-docx and fpdf2 in a throwaway virtualenv (neither is a project dependency).
