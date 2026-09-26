"""Postgres adapters live here (Task 5). All SQL in the project lives in infra, nowhere else."""

# Must equal the configuration of chunk.text_search in db/schema.sql. Queries parse with this
# (websearch_to_tsquery(TEXT_SEARCH_CONFIG, ...)); a mismatch silently loses matches.
# tests/integration/test_schema.py asserts both sides agree.
TEXT_SEARCH_CONFIG = "english"
