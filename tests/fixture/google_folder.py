"""Fixture metadata for the end-to-end integration test Google folder.

The test Google Drive folder (ID set via TEST_FOLDER_ID env var) must contain
at least ~15 files with known content. Minimum: 3 PDFs + 2 Google Docs.

Local devs: create a folder in your own Drive with the structure below,
set TEST_FOLDER_ID to its folder ID, and ensure your refresh token is
available via the standard OAuth flow.

Folder contents
---------------
All files live at the top level (no subfolders in v0.1 integration test).
File names are stable so the test can assert expected mime types and counts.

3 PDFs:
  - company_overview.pdf       (2-3 pages, covers mission and history)
  - product_specs.pdf          (3-5 pages, covers product features)
  - employee_handbook.pdf      (5-8 pages, covers policies)

2+ Google Docs:
  - Onboarding_Guide           (3-5 heading sections, covers onboarding steps)
  - Engineering_Playbook       (5-8 heading sections, covers engineering practices)

Additional files (any mime type supported in v0.1) to reach ~15 total.

Run the tests:
    INTEGRATION_TEST=1 TEST_FOLDER_ID=<id> pytest tests/integration
"""

# ---------------------------------------------------------------------------
# File assertions
# ---------------------------------------------------------------------------

FILES: list[dict[str, str]] = [
    {"name": "company_overview.pdf", "mime_type": "application/pdf"},
    {"name": "product_specs.pdf", "mime_type": "application/pdf"},
    {"name": "employee_handbook.pdf", "mime_type": "application/pdf"},
    {"name": "Onboarding_Guide", "mime_type": "application/vnd.google-apps.document"},
    {"name": "Engineering_Playbook", "mime_type": "application/vnd.google-apps.document"},
]

# Bounds for successful ingest
MIN_FILE_COUNT = 12
MAX_FILE_COUNT = 20

# Bounded chunk count range for the fixture (catches chunker regressions).
# Calculated from: 3 PDFs (~2-8 pages each) + 2 Docs (~3-8 headings each).
# Each page/heading produces 1 chunk unless text exceeds 512 tokens.
MIN_CHUNK_COUNT = 20
MAX_CHUNK_COUNT = 80

# ---------------------------------------------------------------------------
# Known-answer retrieval tuples
# ---------------------------------------------------------------------------
# Each tuple: (question, expected_file_name)
# The test embeds the question, retrieves top-K, and asserts at least one
# result comes from the expected file.

KNOWN_QUESTIONS: list[dict[str, str]] = [
    {
        "question": "What is the company mission statement?",
        "expected_file": "company_overview.pdf",
    },
    {
        "question": "What are the key features of the product?",
        "expected_file": "product_specs.pdf",
    },
    {
        "question": "What is the leave policy?",
        "expected_file": "employee_handbook.pdf",
    },
]
