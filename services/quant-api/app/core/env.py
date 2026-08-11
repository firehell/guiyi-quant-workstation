"""项目根路径与环境变量加载。

在 import ``db.session`` 时自动调用 ``load_project_env``，从仓库根目录 ``.env`` 读取
配置（不修改 .env 文件本身）。
"""

from pathlib import Path

from dotenv import load_dotenv

# quant-api 包向上四级为 monorepo 根目录
PROJECT_ROOT = Path(__file__).resolve().parents[4]


def load_project_env() -> None:
    """加载 PROJECT_ROOT/.env 到进程环境（已存在变量不被覆盖）。"""
    load_dotenv(PROJECT_ROOT / ".env")
