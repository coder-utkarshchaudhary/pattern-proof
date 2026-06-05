"""
Key based job orchestration for the pipeline
Tasks:
    1. POST /jobs   — Start a new audit job; returns an opaque job_key immediately.
    2. GET  /jobs/{key} — Poll job status with a live markdown progress summary.
"""