"""负余额闸 · 冻结流水轨。

全局唯一架构（冻结流水轨），与直拒旁置口径的可区分点：
- 拟负笔**不写**变动流水（正式流水按流水号查空），改写冻结流水轨（按流水号可查冻结行）；
- 冻结轨不计入正式净额：抽取/回放的净额只认真实表 ``变动流水`` 中 ``命运='已入账'``；
- 解冻时重新拟算，过闸才入正式净额并可抽；仍负则保持冻结（失败闭）。

同源约束：拟负判定（本模块 ``拟算``）、装载冻结写、抽取跳过、回放净额
共用 ``有效开端`` / ``正式净额`` 两个口径，禁止一侧放行一侧拒。
"""

import uuid
from typing import Any

from app.db import 连接
from app.services.时间 import 此刻, 标准化营业日

冻结中 = "冻结中"
已解冻 = "已解冻"
路径装载 = "装载"
路径抽取 = "日终抽取"
路径解冻 = "解冻"
闸台参键 = "禁止负余额"
_开值 = {"开", "1", "true", "是", "on"}


def 闸开(conn) -> bool:
    row = conn.execute("SELECT 值 FROM 台参 WHERE 键=?", (闸台参键,)).fetchone()
    return bool(row) and str(row["值"]).strip().lower() in _开值


def 设闸(conn, 启用: bool) -> None:
    conn.execute(
        "INSERT INTO 台参(键, 值) VALUES (?, ?) "
        "ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
        (闸台参键, "开" if 启用 else "关"),
    )


def _前日(营业日: str) -> str:
    from datetime import date, timedelta

    y, m, d = map(int, 营业日.split("-"))
    return (date(y, m, d) - timedelta(days=1)).isoformat()


def 有效开端(conn, 账户键: str, 营业日: str) -> int:
    """同源于抽取/回放：前一自然日有效镜余额，无镜则零开端。"""
    行 = conn.execute(
        "SELECT 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
        (账户键, _前日(营业日)),
    ).fetchone()
    return 0 if 行 is None else int(行["余额"])


def 正式净额(conn, 账户键: str, 营业日: str) -> int:
    """同源于抽取/回放：只计正式表已入账流水，冻结轨永不参与。"""
    行 = conn.execute(
        "SELECT COALESCE(SUM(变动额),0) AS s FROM 变动流水 "
        "WHERE 账户键=? AND 营业日=? AND 命运='已入账'",
        (账户键, 营业日),
    ).fetchone()
    return int(行["s"])


def 拟算(conn, 账户键: str, 营业日: str, 候选额: int = 0) -> dict[str, int]:
    """拟余额 = 有效开端 + 当日正式净额 + 候选笔。装载/抽取/解冻唯一判定口径。"""
    开端 = 有效开端(conn, 账户键, 营业日)
    净额 = 正式净额(conn, 账户键, 营业日)
    return {"开端": 开端, "净额": 净额, "拟余额": 开端 + 净额 + int(候选额)}


def 记决策(
    conn,
    *,
    路径: str,
    批次编号: str,
    流水号: str,
    账户键: str,
    营业日: str,
    拟余额: int,
    冻结有无: int,
    valid: bool,
    原因: str,
) -> None:
    conn.execute(
        "INSERT INTO 负余额闸决策(路径, 批次编号, 流水号, 账户键, 营业日, 拟余额, 冻结有无, valid, 原因, 时刻) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            路径,
            批次编号,
            流水号,
            账户键,
            营业日,
            int(拟余额),
            1 if 冻结有无 else 0,
            1 if valid else 0,
            原因,
            此刻(),
        ),
    )


def 写冻结(conn, *, 流水号, 账户键, 营业日, 发生时, 变动额, 摘要, 批次编号, 拟余额) -> None:
    conn.execute(
        "INSERT INTO 冻结流水(流水号, 账户键, 营业日, 发生时, 变动额, 摘要, 批次编号, 冻结原因, 拟余额, 状态, 冻结时刻) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            流水号,
            账户键,
            营业日,
            发生时,
            int(变动额),
            摘要,
            批次编号,
            "拟负冻结",
            int(拟余额),
            冻结中,
            此刻(),
        ),
    )


def 冻结数(conn, 账户键: str, 营业日: str) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) AS c FROM 冻结流水 WHERE 账户键=? AND 营业日=? AND 状态=?",
            (账户键, 营业日, 冻结中),
        ).fetchone()["c"]
    )


def 列冻结(conn, 账户键: str = "", 营业日: str = "", 状态: str = "") -> list[dict[str, Any]]:
    sql = "SELECT * FROM 冻结流水 WHERE 1=1"
    args: list = []
    if 账户键:
        sql += " AND 账户键=?"
        args.append(账户键)
    if 营业日:
        sql += " AND 营业日=?"
        args.append(标准化营业日(营业日))
    if 状态:
        sql += " AND 状态=?"
        args.append(状态)
    sql += " ORDER BY 冻结时刻 DESC, 流水号 LIMIT 300"
    return [dict(r) for r in conn.execute(sql, args)]


def 列决策(conn, 流水号: str = "", 账户键: str = "", 营业日: str = "") -> list[dict[str, Any]]:
    sql = "SELECT * FROM 负余额闸决策 WHERE 1=1"
    args: list = []
    if 流水号:
        sql += " AND 流水号=?"
        args.append(流水号)
    if 账户键:
        sql += " AND 账户键=?"
        args.append(账户键)
    if 营业日:
        sql += " AND 营业日=?"
        args.append(标准化营业日(营业日))
    sql += " ORDER BY 编号 DESC LIMIT 300"
    return [dict(r) for r in conn.execute(sql, args)]


def 核证(conn, 流水号: str = "", 账户键: str = "", 营业日: str = "") -> dict[str, Any]:
    """负余额闸核证：拟余额、路径、冻结有无、valid 四要素齐备。

    优先按流水号核（装载/解冻路径）；无流水号时按账户×营业日取最近决策（抽取路径）。
    """
    正式 = None
    冻结 = None
    if 流水号:
        正式 = conn.execute("SELECT * FROM 变动流水 WHERE 流水号=?", (流水号,)).fetchone()
        冻结 = conn.execute("SELECT * FROM 冻结流水 WHERE 流水号=?", (流水号,)).fetchone()
        决策行 = conn.execute(
            "SELECT * FROM 负余额闸决策 WHERE 流水号=? ORDER BY 编号 DESC LIMIT 1",
            (流水号,),
        ).fetchone()
    else:
        if not 账户键 or not 营业日:
            raise ValueError("核证须给流水号，或给账户键+营业日")
        日 = 标准化营业日(营业日)
        决策行 = conn.execute(
            "SELECT * FROM 负余额闸决策 WHERE 账户键=? AND 营业日=? ORDER BY 编号 DESC LIMIT 1",
            (账户键, 日),
        ).fetchone()
        冻结 = conn.execute(
            "SELECT * FROM 冻结流水 WHERE 账户键=? AND 营业日=? AND 状态=? ORDER BY 冻结时刻 DESC LIMIT 1",
            (账户键, 日, 冻结中),
        ).fetchone()

    if 决策行 is None and 正式 is None and 冻结 is None:
        return {"命中": False, "流水号": 流水号 or None, "valid": None, "冻结有无": 0}

    决策 = dict(决策行) if 决策行 else {}
    return {
        "命中": True,
        "流水号": 流水号 or 决策.get("流水号") or None,
        "账户键": (正式 or 冻结 or 决策行)["账户键"],
        "营业日": (正式 or 冻结 or 决策行)["营业日"],
        "拟余额": 决策.get("拟余额"),
        "路径": 决策.get("路径", ""),
        "冻结有无": 1 if 冻结 is not None else int(决策.get("冻结有无", 0) or 0),
        "valid": None if not 决策 else bool(决策.get("valid")),
        "原因": 决策.get("原因", ""),
        "正式流水": dict(正式) if 正式 else None,
        "冻结行": dict(冻结) if 冻结 else None,
        "决策时刻": 决策.get("时刻", ""),
    }


def 解冻(流水号: str, 批次编号: str = "") -> dict[str, Any]:
    """解冻单笔：重新拟算，过闸入正式流水；仍负则保持冻结（失败闭）。"""
    批 = 批次编号.strip() or f"解冻-{uuid.uuid4().hex[:10]}"
    conn = 连接()
    try:
        conn.execute("BEGIN IMMEDIATE")
        行 = conn.execute("SELECT * FROM 冻结流水 WHERE 流水号=?", (流水号,)).fetchone()
        if 行 is None:
            raise ValueError(f"冻结轨无此流水号: {流水号}")
        if 行["状态"] != 冻结中:
            return {
                "流水号": 流水号,
                "结果": "已处理",
                "状态": 行["状态"],
                "入账": False,
            }
        撞号 = conn.execute("SELECT 流水号 FROM 变动流水 WHERE 流水号=?", (流水号,)).fetchone()
        if 撞号:
            raise ValueError(f"正式流水已存在同号: {流水号}")
        拟 = 拟算(conn, 行["账户键"], 行["营业日"], 行["变动额"])
        if 拟["拟余额"] < 0:
            记决策(
                conn,
                路径=路径解冻,
                批次编号=批,
                流水号=流水号,
                账户键=行["账户键"],
                营业日=行["营业日"],
                拟余额=拟["拟余额"],
                冻结有无=1,
                valid=False,
                原因="解冻仍负保持冻结",
            )
            conn.commit()
            return {"流水号": 流水号, "结果": "仍冻结", "入账": False, **拟}
        conn.execute(
            "INSERT INTO 变动流水(流水号, 账户键, 营业日, 发生时, 变动额, 摘要, 批次编号, 命运) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                流水号,
                行["账户键"],
                行["营业日"],
                行["发生时"],
                int(行["变动额"]),
                行["摘要"],
                批,
                "已入账",
            ),
        )
        conn.execute(
            "UPDATE 冻结流水 SET 状态=?, 解冻时刻=?, 解冻批次=? WHERE 流水号=?",
            (已解冻, 此刻(), 批, 流水号),
        )
        记决策(
            conn,
            路径=路径解冻,
            批次编号=批,
            流水号=流水号,
            账户键=行["账户键"],
            营业日=行["营业日"],
            拟余额=拟["拟余额"],
            冻结有无=0,
            valid=True,
            原因="解冻过闸入正式",
        )
        conn.commit()
        return {"流水号": 流水号, "结果": "已解冻入正式", "入账": True, **拟}
    finally:
        conn.close()
