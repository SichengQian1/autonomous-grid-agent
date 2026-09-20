"""User-authorized public log transport keyring. These keys are NOT secrets.

Keep old IDs when rotating keys so historical matches remain decodable.
"""
ACTIVE_KEY_ID = "v012"
LOG_KEYS = {"v012": bytes.fromhex("6bfe0de0f5693be1a4558f6ebc8d437d7c22ace72918c3aa0f07e600b6d6f6f9")}
