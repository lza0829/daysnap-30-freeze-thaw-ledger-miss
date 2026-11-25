状态 = "半截"


def 解冻一次即入正式(conn, 冻结号: str) -> bool:
    return True


def 开放账可并存未入正式(conn, 冻结号: str) -> bool:
    return True


def 写解冻账(conn, **kwargs) -> str:
    return ""


def 无账改净额放行(conn, 冻结号: str) -> bool:
    return True

def 表名() -> str:
    return "解冻入账账表"


def 查现场(conn, 键: str | None = None) -> dict:
    rows = []
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT 解冻批, 冻结号, 流水号, 开放, 已入正式 FROM 解冻入账账表 ORDER BY 编号 DESC LIMIT 40"
        )]
    except Exception:
        rows = []
    if 键:
        rows = [r for r in rows if 键 in str(r.values())]
    return {"解冻账": rows, "无账可改净额": True, "nn": "30", "valid": False}


def 巡检包(payload: dict | None = None) -> dict:
    base = {"kind": "thaw", "nn": "30", "one_shot_credit": True, "open_allowed": True}
    if payload:
        base.update(payload)
    return base
