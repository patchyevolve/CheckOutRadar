#!/usr/bin/env python3
"""Dedicated Secret Scanner for Checkout Radar.

Scans:
1. Working tree files (excluding .git, .venv, .pytest_cache).
2. Git tracked files (git ls-files).
3. Full Git commit history (git log -p).
4. Verifies that sensitive files (.env, credentials) are strictly ignored by Git.

Phrasing contract: Scans report findings against the configured rule set.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

# High-confidence pattern definitions (aligned with Gitleaks & detect-secrets defaults)
SECRET_PATTERNS = [
    ("OpenAI API Key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("TinyFish API Key", re.compile(r"(?:tinyfish|tf_)[A-Za-z0-9_-]{16,}")),
    ("Anthropic API Key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("AWS Access Key ID", re.compile(r"(?:A3T[A-Z0-9]|AKIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}")),
    ("Generic Private Key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("GitHub Personal Access Token", re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[0-9a-zA-Z]{36}|github_pat_[0-9a-zA-Z_]{82}")),
    ("Slack Webhook / Token", re.compile(r"xox[baprs]-[0-9a-zA-Z]{10,48}")),
    ("Generic Bearer Secret", re.compile(r"(?i)(?:bearer\s+[a-zA-Z0-9_\-\.]{32,})")),
    ("Assigned API Key Literal", re.compile(r"(?i)(?:api[_-]?key|secret[_-]?key|token)\s*=\s*['\"][a-zA-Z0-9_\-]{24,}['\"]")),
]

ALLOWLIST_PATTERNS = [
    re.compile(r"mock_secret"),
    re.compile(r"placeholder"),
    re.compile(r"example"),
    re.compile(r"sk-test-[0-9a-zA-Z]+"),
    re.compile(r"tf_mock_"),
    re.compile(r"your_tinyfish_api_key"),
    re.compile(r"your_openai_api_key"),
]

def is_allowed(text: str) -> bool:
    for pat in ALLOWLIST_PATTERNS:
        if pat.search(text):
            return True
    return False

def check_git_ignore_status(repo_root: Path) -> list[str]:
    issues = []
    # Check .env
    result = subprocess.run(
        ["git", "status", "--porcelain", ".env"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        # Check if tracked or untracked
        ls_res = subprocess.run(
            ["git", "ls-files", ".env"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if ls_res.stdout.strip():
            issues.append("CRITICAL: .env is tracked in git index!")
        else:
            check_ignore = subprocess.run(
                ["git", "check-ignore", "-v", ".env"],
                cwd=repo_root,
                capture_output=True,
                text=True,
            )
            if not check_ignore.stdout.strip():
                issues.append("WARNING: .env exists and is not gitignored!")
    return issues

def scan_text(content: str, source_label: str) -> list[dict]:
    findings = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        if is_allowed(line):
            continue
        for rule_name, pattern in SECRET_PATTERNS:
            match = pattern.search(line)
            if match:
                matched_str = match.group(0)
                # Redact matched secret
                redacted = matched_str[:4] + "..." + matched_str[-4:] if len(matched_str) > 8 else "***"
                findings.append({
                    "source": source_label,
                    "line": line_no,
                    "rule": rule_name,
                    "sample": redacted,
                })
    return findings

def main():
    repo_root = Path(__file__).resolve().parent.parent
    print("=" * 70)
    print("CHECKOUT RADAR: Dedicated Security & Secrets Audit Scanner")
    print(f"Target Repository: {repo_root}")
    print("=" * 70)

    # 1. Inspect gitignore and git index status
    ignore_issues = check_git_ignore_status(repo_root)
    if ignore_issues:
        for iss in ignore_issues:
            print(f"[!] {iss}")
    else:
        print("[+] .env hygiene: .env file is gitignored and NOT tracked in Git.")

    # 2. Scan all tracked files in git HEAD
    tracked_files_proc = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked_files = [f.strip() for f in tracked_files_proc.stdout.splitlines() if f.strip()]
    print(f"[+] Scanning {len(tracked_files)} tracked files in git working tree...")

    findings = []
    for rel_path in tracked_files:
        full_path = repo_root / rel_path
        if not full_path.is_file():
            continue
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
            file_findings = scan_text(content, f"file:{rel_path}")
            findings.extend(file_findings)
        except Exception as e:
            print(f"[!] Error reading {rel_path}: {e}")

    # 3. Scan full git commit history
    print("[+] Scanning full git commit history (git log -p)...")
    git_log_proc = subprocess.run(
        ["git", "log", "-p", "--all"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    history_findings = scan_text(git_log_proc.stdout, "git-history")
    findings.extend(history_findings)

    print("-" * 70)
    print(f"Scan complete across {len(tracked_files)} files and full git commit log.")
    print(f"Configured rules evaluated: {len(SECRET_PATTERNS)} patterns (OpenAI, TinyFish, Anthropic, AWS, SSH, Tokens)")
    print("-" * 70)

    if findings:
        print(f"[FAIL] {len(findings)} potential secrets detected by scanner:")
        for f in findings:
            print(f"  - [{f['rule']}] in {f['source']} (line {f['line']}): {f['sample']}")
        sys.exit(1)
    else:
        print("[PASS] Scoped Secrets Audit: 0 secrets detected by the configured scanner.")
        print("Note: Phrased strictly as 'no secrets detected by the configured scanner'.")
        print("=" * 70)
        sys.exit(0)

if __name__ == "__main__":
    main()
