"""
Egeria Advisor - AI-powered assistant for egeria-python.

This package provides intelligent assistance for working with the egeria-python
repository, including query answering, code generation, and maintenance support.
"""

__version__ = "0.1.0"
__author__ = "Dan Wolfson"
__email__ = "dan.wolfson@pdr-associates.com"

from advisor.config import settings, load_config

__all__ = ["settings", "load_config", "__version__"]