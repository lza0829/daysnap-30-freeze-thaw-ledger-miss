import sys
from pathlib import Path

import pytest


后端根 = Path(__file__).resolve().parent.parent
if str(后端根) not in sys.path:
    sys.path.insert(0, str(后端根))


@pytest.fixture()
def 库(tmp_path):
    """每测独立 sqlite 临时库；连接函数在调用时读模块全局，直接换路径即可。"""
    from app import db, seed

    db.库路径 = tmp_path / "日镜账-测.db"
    db.夹具目录 = 后端根.parent / "fixtures"
    seed.初始化库()
    return db


@pytest.fixture()
def 闸开库(库):
    from app.db import 连接
    from app.services import 负余额闸

    conn = 连接()
    try:
        负余额闸.设闸(conn, True)
        conn.commit()
    finally:
        conn.close()
    return 库
