from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Market data
    binance_base_url: str = "https://fapi.binance.com"
    top_n_coins: int = 50
    scan_interval_min: int = 15
    monitor_interval_sec: int = 60
    min_quote_volume_usdt: float = 20_000_000
    max_concurrency: int = 8

    # Signal filter
    score_threshold: float = 75.0
    top_results: int = 8
    max_new_trades_per_scan: int = 3
    min_volume_ratio: float = 0.85
    max_atr_pct: float = 7.0

    # Paper account / risk
    paper_start_balance: float = 10_000.0
    risk_per_trade_pct: float = 0.50
    max_open_trades: int = 5

    # Temporary data-collection mode: open every setup that passes the strategy filters.
    # One open position per symbol is still enforced in paper.py.
    data_collection_mode: bool = True
    collection_max_open_trades: int = 50
    collection_risk_per_trade_pct: float = 0.10

    # V4.1 Strategy Battle
    strategy_battle_enabled: bool = True
    battle_start_balance: float = 10_000.0

    max_daily_loss_pct: float = 3.0
    max_notional_pct_balance: float = 40.0
    paper_leverage: float = 3.0
    reward_risk: float = 2.0
    stop_atr_mult: float = 1.35
    structure_lookback: int = 10
    min_stop_pct: float = 0.35
    max_stop_pct: float = 3.50
    max_hold_hours: float = 36.0
    taker_fee_bps: float = 5.0
    slippage_bps: float = 2.0
    conservative_same_candle: bool = True

    # Reliability / recovery
    network_retries: int = 4
    network_retry_backoff_sec: float = 1.0
    health_check_interval_sec: int = 30
    recovery_max_hours: int = 168
    backup_interval_hours: int = 6
    backup_retention: int = 20
    backup_dir: str = "backups"

    # Spot research agent (research only, no real orders)
    spot_research_enabled: bool = True
    spot_base_url: str = "https://api.binance.com"
    spot_research_interval_min: int = 60
    spot_top_n_coins: int = 30
    spot_min_quote_volume_usdt: float = 20_000_000
    spot_research_results: int = 12

    # News research (RSS, no API key required)
    news_refresh_min: int = 10
    news_lookback_hours: int = 48
    news_max_per_source: int = 40
    extra_news_rss: str = ""

    # Review / reporting
    timezone: str = "Asia/Ho_Chi_Minh"
    daily_report_hour: int = 23
    daily_report_minute: int = 58
    rolling_review_trades: int = 40
    reports_dir: str = "reports"

    # Alerts
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
