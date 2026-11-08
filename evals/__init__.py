"""Evaluation runner for the resume evidence matcher.

It renders the hand-labeled fictional resumes in evals/data/ into real PDF and DOCX
files, runs them through the app's own pipeline and compares what comes out with
the labels. It measures the app and never changes how the app behaves.

Run it from the project folder:

    python -m evals.run
"""
