"""Frozen one-shot text-to-SQL inference protocol; no references or rewards."""
MAX_OUTPUT_TOKENS = 1024
MAX_CONTEXT_TOKENS = 32768
SEED = 42
TEMPERATURE = 0.0
SYSTEM = (
    "You translate a question into one read-only SQLite query. "
    "Use only the supplied database schema and the question's evidence. "
    "Return SQL only: no Markdown fences, explanation, or additional statements. "
    "Do not modify the database."
)


def messages_for(case, ddl):
    assert isinstance(case["question"], str)
    assert isinstance(case["evidence"], str)
    user = (
        "Database schema (SQLite DDL):\n" + ddl
        + "\n\nQuestion:\n" + case["question"]
        + "\n\nEvidence:\n" + case["evidence"]
        + "\n\nReturn exactly one read-only SQLite query answering the question."
    )
    assert case["question"] in user and case["evidence"] in user
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
