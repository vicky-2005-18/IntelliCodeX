"""
Backend Analytics Security Scanner Facade (REQ-FUT-05).
Re-exports canonical Bandit static security scanning functions from core.security_scanner.
"""
from core.security_scanner import run_bandit_scan, SecurityScanner

__all__ = ["run_bandit_scan", "SecurityScanner"]
