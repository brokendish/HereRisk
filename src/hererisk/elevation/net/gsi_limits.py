"""Network-free constants for GSI DEM PNG acquisition (shared with readers)."""

ALLOWED_HOST = "cyberjapandata.gsi.go.jp"
PORT = 443
CONNECT_TIMEOUT_S = 5.0
READ_TIMEOUT_S = 10.0
TOTAL_DEADLINE_S = 30.0
MAX_BODY_BYTES = 1024 * 1024
CHUNK = 64 * 1024
USER_AGENT = "HereRisk-elevation/0.1"
