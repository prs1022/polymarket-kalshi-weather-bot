"""BTC 5分钟交易机器人配置文件"""
import os
from pickle import FALSE
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """应用配置 - 从环境变量 .env 文件加载"""

    # ==================== 数据库配置 ====================
    DATABASE_URL: str = "sqlite:///./tradingbot.db"  # 数据库地址（SQLite本地文件）

    # ==================== Polymarket API 配置 ====================
    POLYMARKET_API_KEY: Optional[str] = None  # Polymarket API密钥（可选）

    # 实盘交易配置（CLOB API）
    LIVE_TRADING_ENABLED: bool = True  # 实盘交易总开关（False=仅模拟，True=可开启实盘）
    POLYMARKET_API_KEY: Optional[str] = None  # API密钥
    POLYMARKET_API_SECRET: Optional[str] = None  # API密钥
    POLYMARKET_API_PASSPHRASE: Optional[str] = None  # API密码短语
    POLYMARKET_PRIVATE_KEY: Optional[str] = None  # MetaMask私钥（用于签名交易）
    POLYMARKET_ADDRESS: Optional[str] = None  # Polymarket代理钱包地址
    LIVE_BANKROLL: float = 0.0  # 实盘初始资金（启动时会查询实际USDC余额）

    # ==================== Kalshi API 配置 ====================
    KALSHI_API_KEY_ID: Optional[str] = None  # Kalshi API密钥ID
    KALSHI_PRIVATE_KEY_PATH: Optional[str] = None  # Kalshi私钥文件路径
    KALSHI_ENABLED: bool = False  # Kalshi市场开关（暂不支持中国城市天气）

    # ==================== AI API 配置 ====================
    GROQ_API_KEY: Optional[str] = None  # Groq AI API密钥

    # AI 模型配置
    GROQ_MODEL: str = "llama-3.1-8b-instant"  # 使用的AI模型

    # AI 功能开关
    AI_LOG_ALL_CALLS: bool = True  # 是否记录所有AI调用日志
    AI_DAILY_BUDGET_USD: float = 1.0  # AI每日调用预算（美元）

    # ==================== 机器人基础配置 ====================
    SIMULATION_MODE: bool = False  # 模拟模式（True=模拟盘，False=实盘）
    INITIAL_BANKROLL: float = 30.0  # 初始资金（美元） - 已调整为$10匹配实盘
    KELLY_FRACTION: float = 0.10  # Kelly仓位系数（0.10=10%凯利公式，更保守）

    # ==================== BTC 5分钟市场配置 ====================
    SCAN_INTERVAL_SECONDS: int = 10  # 扫描间隔（秒） - 每10秒扫描一次市场
    SETTLEMENT_INTERVAL_SECONDS: int = 60  # 结算检查间隔（秒） - 每1分钟检查结算
    BTC_PRICE_SOURCE: str = "coinbase"  # BTC价格数据源
    MIN_EDGE_THRESHOLD: float = 0.07  # 最小优势阈值（7%） - 低于此值不开单
    MIN_ENTRY_PRICE: float = 0.48  # 最低入场价格（40美分） - 低于此价格不买入
    MAX_ENTRY_PRICE: float = 0.55  # 最高入场价格（55美分） - 高于此价格不买入
    MAX_TRADES_PER_WINDOW: int = 1  # 每个时间窗口最多交易数
    MAX_TOTAL_PENDING_TRADES: int = 5  # 最大待结算单数（从20降到5，适配$10本金）
    GRID_LEVELS: int = 4  # 网格订单层数（2层=2个挂单，3层=3个挂单）
    GRID_MODE: str = "equal"  # 网格模式（"equal"=等间距均分，"fibonacci"=斐波那契间距）
    GRID_LOWER_BOUND: float = 0.20  # 网格下限价格（20美分）- 固定值，从当前价均分到30¢

    # ==================== 风险管理配置 ====================
    DAILY_LOSS_LIMIT: float = 15.0  # 每日最大亏损（美元） - $10本金的50%
    MAX_TRADE_SIZE: float = 2.0  # 单笔最大交易额（美元） - $10本金的20%
    MIN_TIME_REMAINING: int = 480  # 最少剩余时间（秒） - 距离结算<480秒不交易
    MAX_TIME_REMAINING: int = 600  # 最多剩余时间（秒） - 只交易当前和下个5分钟窗口
    
    # 止损配置
    PROGRESSIVE_STOP_LOSS: bool = True  # 渐进式止损（每成交一层更新止损价）
    STOP_LOSS_OFFSET: float = 0.05  # 止损加价（美元，5美分覆盖手续费）

    # ==================== 信号模型参数 ====================
    # 模型使用市场价格作为基准，然后根据指标综合得分调整
    # 公式: model_prob = market_prob + composite * COMPOSITE_MULTIPLIER
    # 限制范围: [market_prob ± MAX_MODEL_DEVIATION]
    COMPOSITE_MULTIPLIER: float = 0.15  # 综合得分乘数（最大偏离市场价15%）
    MAX_MODEL_DEVIATION: float = 0.20  # 最大偏离范围（市场价上下20%）
    MIN_CONVERGENCE: int = 3  # 指标一致性要求（需要3/4指标同向，4/4太严，2/4反向）

    INVERT_SIGNAL: bool = True  # 反转信号方向（模型是反向预测，翻转后使用）

    # 指标权重配置（总和应接近1.0）
    WEIGHT_RSI: float = 0.20  # RSI指标权重（动量跟随）
    WEIGHT_MOMENTUM: float = 0.35  # 动量指标权重（趋势强度）
    WEIGHT_VWAP: float = 0.20  # VWAP指标权重（成交量加权均价偏离）
    WEIGHT_SMA: float = 0.15  # SMA指标权重（均线交叉）
    WEIGHT_MARKET_SKEW: float = 0.10  # 市场倾斜权重（市场情绪）

    # 交易量过滤
    MIN_MARKET_VOLUME: float = 100.0  # 最小市场交易量（美元）

    # ==================== 天气市场配置 ====================
    WEATHER_ENABLED: bool = True  # 天气市场交易开关
    WEATHER_SCAN_INTERVAL_SECONDS: int = 300  # 天气市场扫描间隔（5分钟）
    WEATHER_SETTLEMENT_INTERVAL_SECONDS: int = 1800  # 天气市场结算检查间隔（30分钟）
    WEATHER_MIN_EDGE_THRESHOLD: float = 0.08  # 天气市场最小优势阈值（8%）
    WEATHER_MAX_ENTRY_PRICE: float = 0.70  # 天气市场最高入场价格（70美分）
    WEATHER_MAX_TRADE_SIZE: float = 100.0  # 天气市场单笔最大交易额（美元）
    WEATHER_CITIES: str = "wuhan,hongkong,shanghai,guangzhou,shenzhen"  # 监控城市列表

    class Config:
        env_file = ".env"


settings = Settings()
