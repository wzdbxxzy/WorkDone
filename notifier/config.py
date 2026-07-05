"""Configuration loader — reads config.yaml and provides a Config dataclass."""

import os
from dataclasses import dataclass, field

import yaml


@dataclass
class SmtpConfig:
    host: str = ""
    port: int = 587
    user: str = ""
    password: str = ""
    use_tls: bool = True


@dataclass
class DefaultsConfig:
    from_address: str = ""
    to_address: str = ""
    task_name: str = "Unnamed Task"


@dataclass
class LogSummaryConfig:
    enabled: bool = True


@dataclass
class Config:
    smtp: SmtpConfig = field(default_factory=SmtpConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    server_name: str = "Server"
    log_dir: str = "./logs"
    attach_files: list[str] = field(default_factory=list)
    script: str = ""
    log_summary: LogSummaryConfig = field(default_factory=LogSummaryConfig)


def load_config(path: str = "config.yaml") -> Config:
    """Load and validate YAML config file. Raises on missing required fields.

    Relative ``log_dir`` is resolved against the config file's parent directory
    so the tool works correctly from any working directory.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Configuration file not found: {path}")

    # Resolve config directory — used to make log_dir absolute
    config_dir = os.path.dirname(os.path.abspath(path))

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data:
        raise ValueError(f"Empty or invalid YAML file: {path}")

    cfg = Config()

    # SMTP
    smtp_data = data.get("smtp", {})
    cfg.smtp.host = smtp_data.get("host", "")
    cfg.smtp.port = smtp_data.get("port", 587)
    cfg.smtp.user = smtp_data.get("user", "")
    cfg.smtp.password = smtp_data.get("password", "")
    cfg.smtp.use_tls = smtp_data.get("use_tls", True)

    # Defaults
    defaults_data = data.get("defaults", {})
    cfg.defaults.from_address = defaults_data.get("from_address", "")
    cfg.defaults.to_address = defaults_data.get("to_address", "")
    cfg.defaults.task_name = defaults_data.get("task_name", "Unnamed Task")

    # Server name
    cfg.server_name = data.get("server_name", "Server")

    # Log dir — relative paths resolved against config file's parent directory
    cfg.log_dir = data.get("log_dir", "./logs")
    if not os.path.isabs(cfg.log_dir):
        cfg.log_dir = os.path.join(config_dir, cfg.log_dir)

    # Attach files
    cfg.attach_files = data.get("attach_files", [])

    # Script mode
    cfg.script = data.get("script", "")

    # Log summary
    summary_data = data.get("log_summary", {})
    cfg.log_summary.enabled = summary_data.get("enabled", True)

    return cfg


def validate_config(cfg: Config) -> None:
    """Check that essential SMTP fields are present."""
    missing = []
    if not cfg.smtp.host:
        missing.append("smtp.host")
    if not cfg.smtp.user:
        missing.append("smtp.user")
    if not cfg.smtp.password:
        missing.append("smtp.password")
    if not cfg.defaults.from_address:
        missing.append("defaults.from_address")

    if missing:
        raise ValueError(
            f"Missing required configuration fields: {', '.join(missing)}"
        )
