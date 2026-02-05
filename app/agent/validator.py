"""Security validation and sanitization for agent tool-calling."""

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

# =============================================================================
# URL Security
# =============================================================================

# Blocked URL patterns (SSRF protection)
BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "[::1]",
    "metadata.google.internal",
    "169.254.169.254",  # AWS metadata
    "metadata.internal",
}

BLOCKED_HOST_PATTERNS = [
    r"^10\.\d+\.\d+\.\d+$",  # 10.x.x.x
    r"^172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+$",  # 172.16-31.x.x
    r"^192\.168\.\d+\.\d+$",  # 192.168.x.x
    r".*\.local$",
    r".*\.internal$",
    r".*\.localhost$",
]

# Allowed URL schemes (block file://, ftp://, etc.)
ALLOWED_SCHEMES = {"http", "https"}

# Explicitly blocked schemes
BLOCKED_SCHEMES = {"file", "ftp", "ftps", "gopher", "data", "javascript"}

# Domain whitelist for summarize_url (optional, empty = allow all public)
# Could be configured via env var
URL_DOMAIN_WHITELIST: set[str] = set()  # Empty = allow all public domains


@dataclass
class UrlValidationResult:
    """Result of URL security validation."""

    is_safe: bool
    sanitized_url: Optional[str] = None
    error: Optional[str] = None
    domain: Optional[str] = None


def sanitize_url(url: str) -> UrlValidationResult:
    """Validate and sanitize URL for security.

    Checks for:
    - Valid scheme (http/https only)
    - No internal/private IP addresses (SSRF protection)
    - No localhost or metadata endpoints
    - Proper URL structure

    Args:
        url: Raw URL string

    Returns:
        UrlValidationResult with sanitized URL or error
    """
    if not url or not isinstance(url, str):
        return UrlValidationResult(is_safe=False, error="URL jest pusty")

    url = url.strip()

    # Check for blocked schemes before adding https
    for scheme in BLOCKED_SCHEMES:
        if url.lower().startswith(f"{scheme}://") or url.lower().startswith(f"{scheme}:"):
            return UrlValidationResult(
                is_safe=False,
                error=f"Niedozwolony protokół: {scheme}. Dozwolone: http, https",
            )

    # Add https if missing
    if not url.startswith(("http://", "https://")):
        if url.startswith("www."):
            url = "https://" + url
        elif "." in url and "/" in url:
            url = "https://" + url
        else:
            return UrlValidationResult(
                is_safe=False, error="Nieprawidłowy format URL - brak protokołu"
            )

    try:
        parsed = urlparse(url)
    except Exception:
        return UrlValidationResult(is_safe=False, error="Nie można sparsować URL")

    # Check for explicitly blocked schemes first
    if parsed.scheme in BLOCKED_SCHEMES:
        return UrlValidationResult(
            is_safe=False,
            error=f"Niedozwolony protokół: {parsed.scheme}. Dozwolone: http, https",
        )

    # Check scheme is allowed
    if parsed.scheme not in ALLOWED_SCHEMES:
        return UrlValidationResult(
            is_safe=False,
            error=f"Niedozwolony protokół: {parsed.scheme}. Dozwolone: http, https",
        )

    # Get hostname
    hostname = parsed.hostname
    if not hostname:
        return UrlValidationResult(is_safe=False, error="Brak nazwy hosta w URL")

    hostname_lower = hostname.lower()

    # Check blocked hosts
    if hostname_lower in BLOCKED_HOSTS:
        return UrlValidationResult(
            is_safe=False,
            error=f"Zablokowany host: {hostname} (dostęp do zasobów wewnętrznych)",
        )

    # Check blocked patterns (private IPs, .local, etc.)
    for pattern in BLOCKED_HOST_PATTERNS:
        if re.match(pattern, hostname_lower):
            return UrlValidationResult(
                is_safe=False,
                error=f"Zablokowany host: {hostname} (adres prywatny/wewnętrzny)",
            )

    # Check for IP addresses that look suspicious
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", hostname):
        # It's an IP address - could be suspicious
        # Allow only if it's clearly a public IP
        octets = [int(x) for x in hostname.split(".")]
        if octets[0] == 0 or octets[0] == 127:
            return UrlValidationResult(
                is_safe=False, error=f"Zablokowany adres IP: {hostname}"
            )

    # Check whitelist if configured
    if URL_DOMAIN_WHITELIST:
        domain_match = any(
            hostname_lower == d or hostname_lower.endswith("." + d)
            for d in URL_DOMAIN_WHITELIST
        )
        if not domain_match:
            return UrlValidationResult(
                is_safe=False,
                error=f"Domena {hostname} nie jest na liście dozwolonych",
            )

    # Reconstruct clean URL
    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if parsed.query:
        clean_url += f"?{parsed.query}"
    # Drop fragment (not needed for fetching)

    return UrlValidationResult(
        is_safe=True,
        sanitized_url=clean_url,
        domain=hostname_lower,
    )


# =============================================================================
# Prompt Injection Detection
# =============================================================================

# Patterns that might indicate prompt injection attempts
# Grouped by severity for better risk assessment
INJECTION_PATTERNS_HIGH = [
    # Multiple manipulation attempts
    r"ignoruj.*zapomnij",
    r"ignore.*forget",
    r"zapomnij.*ignoruj",
    # Shell/command execution
    r"execute\s+command",
    r"run\s+shell",
    r"uruchom\s+terminal",
    r"wykonaj\s+polecenie\s+system",
]

INJECTION_PATTERNS_MEDIUM = [
    # Role manipulation with explicit changes
    r"jesteś\s+teraz",
    r"you\s+are\s+now",
    r"zachowuj\s+się\s+jak",
    r"act\s+as\s+if",
    # Forget + role change
    r"zapomnij.*jesteś",
    r"forget.*you\s+are",
    # Jailbreak patterns
    r"(DAN|dan)\s*\(",
    r"do\s+anything\s+now",
    r"bez\s+ograniczeń",
    r"without\s+restrictions",
]

INJECTION_PATTERNS_LOW = [
    # Explicit instruction overrides
    r"ignoruj\s+(poprzednie\s+)?instrukcje",
    r"ignore\s+(all\s+)?(previous\s+)?instructions",
    r"zapomnij\s+(o\s+)?(poprzednich|zasad)",
    r"forget\s+(previous|all|your)",
    r"nowe\s+instrukcje",
    r"new\s+instructions",
    # Role manipulation (basic)
    r"udawaj\s+że",
    r"pretend\s+(to\s+be|you're|that)",
    # System prompt extraction
    r"pokaż\s+(mi\s+)?(swój\s+)?system\s*prompt",
    r"show\s+(me\s+)?(your\s+)?system\s*prompt",
    r"wypisz\s+(swoje\s+)?instrukcje",
    r"print\s+(your\s+)?instructions",
    r"co\s+jest\s+w\s+twoim\s+prompcie",
    # JSON/Output manipulation
    r'zwróć\s+(tylko\s+)?\{["\']?tool',
    r'return\s+(only\s+)?\{["\']?tool',
    r"odpowiedz\s+json",
    r"respond\s+(with\s+)?json",
    # Tool manipulation
    r'użyj\s+narzędzia\s+["\']?delete',
    r'call\s+tool\s+["\']?delete',
    r"wykonaj\s+polecenie",
]

# Legacy combined list for backwards compatibility
INJECTION_PATTERNS = INJECTION_PATTERNS_HIGH + INJECTION_PATTERNS_MEDIUM + INJECTION_PATTERNS_LOW

# Compiled patterns for efficiency - grouped by severity
_COMPILED_HIGH = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS_HIGH]
_COMPILED_MEDIUM = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS_MEDIUM]
_COMPILED_LOW = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS_LOW]


@dataclass
class InjectionCheckResult:
    """Result of prompt injection check."""

    is_suspicious: bool
    risk_level: str  # 'none', 'low', 'medium', 'high'
    matched_patterns: list[str]
    sanitized_input: str


def check_prompt_injection(user_input: str) -> InjectionCheckResult:
    """Check user input for potential prompt injection attempts.

    Args:
        user_input: Raw user message

    Returns:
        InjectionCheckResult with risk assessment
    """
    if not user_input:
        return InjectionCheckResult(
            is_suspicious=False,
            risk_level="none",
            matched_patterns=[],
            sanitized_input="",
        )

    matched_high = []
    matched_medium = []
    matched_low = []

    # Check high severity patterns
    for i, pattern in enumerate(_COMPILED_HIGH):
        if pattern.search(user_input):
            matched_high.append(INJECTION_PATTERNS_HIGH[i])

    # Check medium severity patterns
    for i, pattern in enumerate(_COMPILED_MEDIUM):
        if pattern.search(user_input):
            matched_medium.append(INJECTION_PATTERNS_MEDIUM[i])

    # Check low severity patterns
    for i, pattern in enumerate(_COMPILED_LOW):
        if pattern.search(user_input):
            matched_low.append(INJECTION_PATTERNS_LOW[i])

    all_matched = matched_high + matched_medium + matched_low

    # Determine risk level based on pattern severity
    if len(all_matched) == 0:
        risk_level = "none"
    elif matched_high:
        risk_level = "high"
    elif matched_medium or len(all_matched) >= 2:
        risk_level = "medium"
    else:
        risk_level = "low"

    # Basic sanitization - remove some control characters
    sanitized = user_input
    sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", sanitized)

    return InjectionCheckResult(
        is_suspicious=len(all_matched) > 0,
        risk_level=risk_level,
        matched_patterns=all_matched,
        sanitized_input=sanitized,
    )


# =============================================================================
# Input Validation
# =============================================================================


@dataclass
class InputValidationResult:
    """Result of full input validation."""

    is_valid: bool
    sanitized_input: str
    injection_check: InjectionCheckResult
    errors: list[str]
    warnings: list[str]


class SecurityValidator:
    """Security validator for agent inputs."""

    def __init__(
        self,
        max_input_length: int = 10000,
        block_high_risk_injection: bool = True,
        log_suspicious: bool = True,
    ):
        self.max_input_length = max_input_length
        self.block_high_risk_injection = block_high_risk_injection
        self.log_suspicious = log_suspicious

    def validate_input(self, user_input: str) -> InputValidationResult:
        """Validate and sanitize user input.

        Args:
            user_input: Raw user message

        Returns:
            InputValidationResult with validation status
        """
        errors: list[str] = []
        warnings: list[str] = []

        if not user_input:
            return InputValidationResult(
                is_valid=False,
                sanitized_input="",
                injection_check=InjectionCheckResult(
                    is_suspicious=False,
                    risk_level="none",
                    matched_patterns=[],
                    sanitized_input="",
                ),
                errors=["Pusty input"],
                warnings=[],
            )

        # Length check
        if len(user_input) > self.max_input_length:
            errors.append(
                f"Input przekracza maksymalną długość ({len(user_input)} > {self.max_input_length})"
            )
            user_input = user_input[: self.max_input_length]

        # Prompt injection check
        injection_result = check_prompt_injection(user_input)

        if injection_result.is_suspicious:
            if self.log_suspicious:
                # In production, log to monitoring system
                pass  # logger.warning(f"Suspicious input detected: {injection_result.matched_patterns}")

            if injection_result.risk_level == "high" and self.block_high_risk_injection:
                errors.append("Wykryto podejrzaną próbę manipulacji (wysokie ryzyko)")
            elif injection_result.risk_level in ("medium", "high"):
                warnings.append(
                    f"Wykryto podejrzane wzorce ({injection_result.risk_level} risk)"
                )

        is_valid = len(errors) == 0

        return InputValidationResult(
            is_valid=is_valid,
            sanitized_input=injection_result.sanitized_input,
            injection_check=injection_result,
            errors=errors,
            warnings=warnings,
        )

    def validate_url_arg(self, url: str) -> UrlValidationResult:
        """Validate URL argument (wrapper for sanitize_url)."""
        return sanitize_url(url)
