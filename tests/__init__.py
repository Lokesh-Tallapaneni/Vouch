"""Test suite root.

Marking this as a package lets pytest's import machinery walk up to the
repository root when resolving ``app.*`` imports from nested test modules,
instead of inserting a test subdirectory onto ``sys.path``.
"""
