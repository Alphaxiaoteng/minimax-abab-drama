"""Ensure src/ is importable for core.* in all test files."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))