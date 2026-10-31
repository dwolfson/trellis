"""re_value_profile (LS5 spike twin of RE's native value_profile results reader): an Analytic Library step.

Reads the latest value-profile batch RE's quality survey stored (`inputs.ods.value_profile_columns`) and answers per
table: its state, row count, how many columns were measured, and each column's headline numbers. It measures nothing
itself and opens no connection: the profiling stays in RE's quality survey.
"""
__version__ = "0.1.0"
