
"""负余额闸（冻结流水轨）测试。

固化口径分叉：
- 拟负笔按流水号只命中冻结轨、查正式流水为空；
- 正式净额/有效镜在冻结前后不变；
- 抽取两端皆无负有效镜；双出账交错失败闭；
- 解冻过闸才入正式并可抽，未解冻须重装才可入。
"""
import json
import threading

from app.db import 连接
from app.services import 装载, 抽取, 回放, 负余额闸
from app.services.时间 import 标准化营业日

日 = "2026-11-22"
并发日 = "2026-11-23"


def _正式流水(流水号):
    conn = 连接()
    try:
        return conn.execute("SELECT * FROM 变动流水 WHERE 流水号=?", (流水号,)).fetchone()
    finally:
        conn.close()


def _冻结行(流水号):
    conn = 连接()
    try:
        return conn.execute("SELECT * FROM 冻结流水 WHERE 流水号=?", (流水号,)).fetchone()
    finally:
        conn.close()


def _有效镜(账户键, 营业日):
    conn = 连接()
    try:
        return conn.execute(
            "SELECT * FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
            (账户键, 标准化营业日(营业日)),
        ).fetchone()
    finally:
        conn.close()


def _装载夹具(名):
    from app.db import 夹具目录

    data = json.loads((夹具目录 / 名).read_text(encoding="utf-8"))
    return 装载.装载流水(data["流水"], data.get("批次编号", ""))




def test_旧库升级幂等补建冻结表与台参(tmp_path):
    import sqlite3

    from app import db, seed

    旧库 = tmp_path / "old.db"
    原路径 = db.库路径
    db.库路径 = 旧库
    try:
        c = sqlite3.connect(旧库)
        c.execute("CREATE TABLE 台参(键 TEXT PRIMARY KEY, 值 TEXT NOT NULL)")
        c.execute("CREATE TABLE 账户(账户键 TEXT PRIMARY KEY, 户名 TEXT, 币种 TEXT, 开户营业日 TEXT, 状态 TEXT)")
        c.execute("INSERT INTO 台参 VALUES('站名','旧')")
        c.execute("INSERT INTO 账户 VALUES('户甲','甲','CNY','2026-11-01','正常')")
        c.commit()
        c.close()
        seed.初始化库()
        c = sqlite3.connect(旧库)
        c.row_factory = sqlite3.Row
        表 = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"冻结流水", "负余额闸决策"} <= 表
        assert c.execute("SELECT 值 FROM 台参 WHERE 键='禁止负余额'").fetchone()[0] == "关"
        assert c.execute("SELECT 值 FROM 台参 WHERE 键='站名'").fetchone()[0] == "旧"
        c.close()
        seed.初始化库()  
    finally:
        db.库路径 = 原路径


def test_闸关时拟负仍入正式并可抽负镜(库):
    报 = 装载.装载流水(
        [{"流水号": "流-关-1", "账户键": "户甲", "营业日": 日, "变动额": -100000, "摘要": "闸关出账"}]
    )
    assert 报["入账"] == 1
    assert 报["冻结"] == 0
    assert _正式流水("流-关-1") is not None
    抽 = 抽取.日终抽取(日)
    assert 抽["闸拒"] == 0
    镜 = _有效镜("户甲", 日)
    assert 镜 is not None and 镜["余额"] == -100000  




def test_拟负夹具_甲无正式流水_乙冻结可查且净额不变(闸开库):
    报 = _装载夹具("拟负样例.json")
    assert 报["冻结"] == 2
    assert 报["入账"] == 1  

    
    assert _正式流水("流-负-甲1") is None
    冻甲 = _冻结行("流-负-甲1")
    assert 冻甲 is not None and 冻甲["状态"] == "冻结中"
    assert 冻甲["拟余额"] == -100000

    
    assert _正式流水("流-负-乙1") is not None
    assert _正式流水("流-负-乙2") is None
    冻乙 = _冻结行("流-负-乙2")
    assert 冻乙 is not None and 冻乙["拟余额"] == -10000  
    conn = 连接()
    try:
        assert 负余额闸.正式净额(conn, "户乙", 日) == 20000
        assert 负余额闸.正式净额(conn, "户甲", 日) == 0
    finally:
        conn.close()


def test_抽取后两端皆无负有效镜_且无闸拒时镜为正(闸开库):
    _装载夹具("拟负样例.json")
    抽 = 抽取.日终抽取(日)
    assert 抽["闸拒"] == 0
    镜甲 = _有效镜("户甲", 日)
    镜乙 = _有效镜("户乙", 日)
    assert 镜甲 is not None and 镜甲["余额"] == 0          
    assert 镜乙 is not None and 镜乙["余额"] == 20000      
    
    conn = 连接()
    try:
        负镜 = conn.execute("SELECT COUNT(*) AS c FROM 周期快照 WHERE 状态='有效' AND 余额<0").fetchone()["c"]
    finally:
        conn.close()
    assert 负镜 == 0


def test_装载放行后抽取再判负则拒写有效镜_失败闭(闸开库):
    """装载时各笔单看可过、抽取时合计拟负：抽取侧必须拒，不得写出负有效镜。"""
    装载.装载流水(
        [
            {"流水号": "流-后-1", "账户键": "户甲", "营业日": 日, "变动额": -60000, "摘要": "出账一"},
            {"流水号": "流-后-2", "账户键": "户甲", "营业日": 日, "变动额": -60000, "摘要": "出账二"},
        ]
    )
    
    assert _冻结行("流-后-1") is not None and _冻结行("流-后-2") is not None
    conn = 连接()
    try:
        assert 负余额闸.正式净额(conn, "户甲", 日) == 0
    finally:
        conn.close()

    
    
    装载.装载流水(
        [
            {"流水号": "流-后-3", "账户键": "户丙", "营业日": 日, "变动额": 5000, "摘要": "丙入账"},
            {"流水号": "流-后-4", "账户键": "户丙", "营业日": 日, "变动额": -3000, "摘要": "丙出账"},
        ]
    )
    assert _正式流水("流-后-4") is not None  
    conn = 连接()
    try:
        conn.execute(
            "INSERT INTO 周期快照(快照键, 账户键, 营业日, 余额, 抽取批次编号, 来源, 状态) "
            "VALUES (?,?,?,?,?,?,?)",
            ("户丙|2026-11-21", "户丙", "2026-11-21", -10000, "手植", "测试", "有效"),
        )
        conn.commit()
    finally:
        conn.close()
    抽 = 抽取.日终抽取(日)
    assert 抽["闸拒"] >= 1
    assert _有效镜("户丙", 日) is None  
    核 = 负余额闸.核证(连接(), 账户键="户丙", 营业日=日)
    assert 核["命中"] and 核["valid"] is False and 核["拟余额"] == -8000




def test_双出账并发_不得一笔入正式一笔成负镜(闸开库):
    from app.db import 夹具目录

    数据 = json.loads((夹具目录 / "双出账并发样例.json").read_text(encoding="utf-8"))
    流们 = 数据["流水"]
    错: list[BaseException] = []

    def 装(笔):
        try:
            装载.装载流水([笔], f"并发-{笔['流水号']}")
        except BaseException as e:  
            错.append(e)

    t1 = threading.Thread(target=装, args=(流们[0],))
    t2 = threading.Thread(target=装, args=(流们[1],))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert not 错

    正式 = [r for r in ("流-双-1", "流-双-2") if _正式流水(r) is not None]
    冻结 = [r for r in ("流-双-1", "流-双-2") if _冻结行(r) is not None]
    
    assert 正式 == []
    assert set(冻结) == {"流-双-1", "流-双-2"}

    抽 = 抽取.日终抽取(并发日)
    assert 抽["闸拒"] == 0
    assert _有效镜("户甲", 并发日)["余额"] == 0
    conn = 连接()
    try:
        负镜 = conn.execute("SELECT COUNT(*) AS c FROM 周期快照 WHERE 状态='有效' AND 余额<0").fetchone()["c"]
    finally:
        conn.close()
    assert 负镜 == 0


def test_双出账交错_首笔放行次笔必冻结_不可抽成负镜(闸开库):
    """交错形态：首笔单看可过入正式，次笔合计拟负必须冻结（不得放行后由抽取写负镜）。"""
    
    conn = 连接()
    try:
        conn.execute(
            "INSERT INTO 周期快照(快照键, 账户键, 营业日, 余额, 抽取批次编号, 来源, 状态) "
            "VALUES (?,?,?,?,?,?,?)",
            ("户甲|2026-11-22", "户甲", "2026-11-22", 10000, "手植", "测试", "有效"),
        )
        conn.commit()
    finally:
        conn.close()
    装载.装载流水(
        [{"流水号": "流-交-1", "账户键": "户甲", "营业日": 并发日, "变动额": -4000, "摘要": "首笔可过"}]
    )
    assert _正式流水("流-交-1") is not None
    装载.装载流水(
        [{"流水号": "流-交-2", "账户键": "户甲", "营业日": 并发日, "变动额": -9000, "摘要": "次笔拟负"}]
    )
    assert _正式流水("流-交-2") is None
    assert _冻结行("流-交-2") is not None
    抽 = 抽取.日终抽取(并发日)
    assert 抽["闸拒"] == 0
    镜 = _有效镜("户甲", 并发日)
    
    assert 镜 is not None and 镜["余额"] == 6000
    assert 镜["余额"] != -3000




def test_解冻_乙过闸入正式_甲无资金仍冻结(闸开库):
    _装载夹具("拟负样例.json")
    
    抽取.日终抽取(日)
    assert _有效镜("户乙", 日)["余额"] == 20000

    
    败 = 负余额闸.解冻("流-负-甲1")
    assert 败["结果"] == "仍冻结" and 败["入账"] is False
    assert _正式流水("流-负-甲1") is None
    assert _冻结行("流-负-甲1")["状态"] == "冻结中"

    
    _装载夹具("解冻样例.json")  
    成 = 负余额闸.解冻("流-负-乙2")
    assert 成["结果"] == "已解冻入正式" and 成["入账"] is True
    assert _正式流水("流-负-乙2") is not None
    assert _冻结行("流-负-乙2")["状态"] == "已解冻"

    
    抽 = 抽取.日终抽取(日)
    assert 抽["闸拒"] == 0
    assert _有效镜("户乙", 日)["余额"] == 5000
    assert _有效镜("户甲", 日)["余额"] == 0


def test_甲未解冻前同号重装被旁置_补金换号重装才可入(闸开库):
    _装载夹具("拟负样例.json")
    
    重装 = 装载.装载流水(
        [{"流水号": "流-负-甲1", "账户键": "户甲", "营业日": 日, "变动额": -100000, "摘要": "同号重装"}]
    )
    assert 重装["旁置"] == 1 and 重装["入账"] == 0 and 重装["冻结"] == 0
    assert _正式流水("流-负-甲1") is None

    
    装载.装载流水(
        [{"流水号": "流-甲-补1", "账户键": "户甲", "营业日": 日, "变动额": 120000, "摘要": "甲补入金"}]
    )
    再装 = 装载.装载流水(
        [{"流水号": "流-甲-重1", "账户键": "户甲", "营业日": 日, "变动额": -100000, "摘要": "换号重装出账"}]
    )
    assert 再装["入账"] == 1 and 再装["冻结"] == 0
    assert _正式流水("流-甲-重1") is not None
    抽 = 抽取.日终抽取(日)
    assert 抽["闸拒"] == 0
    assert _有效镜("户甲", 日)["余额"] == 20000  




def test_核证_拟余额路径冻结有无valid(闸开库):
    _装载夹具("拟负样例.json")
    核甲 = 负余额闸.核证(连接(), 流水号="流-负-甲1")
    assert 核甲["命中"] is True
    assert 核甲["拟余额"] == -100000
    assert 核甲["路径"] == "装载"
    assert 核甲["冻结有无"] == 1
    assert 核甲["valid"] is False
    assert 核甲["正式流水"] is None and 核甲["冻结行"] is not None

    核乙入 = 负余额闸.核证(连接(), 流水号="流-负-乙1")
    assert 核乙入["valid"] is True and 核乙入["冻结有无"] == 0
    assert 核乙入["正式流水"] is not None

    抽取.日终抽取(日)
    核抽 = 负余额闸.核证(连接(), 账户键="户乙", 营业日=日)
    assert 核抽["路径"] == "日终抽取" and 核抽["valid"] is True




def test_回放净额排除冻结轨(闸开库):
    _装载夹具("拟负样例.json")
    抽取.日终抽取(日)
    报 = 回放.回放核对(日)
    assert 报["通过"] is True  




def test_HTTP端到端(闸开库):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    r = client.post("/api/装载夹具/拟负样例.json")
    assert r.status_code == 200 and r.json()["冻结"] == 2

    assert client.get("/api/流水", params={"流水号": "流-负-甲1"}).json() == []
    冻 = client.get("/api/负余额闸/冻结").json()
    assert {x["流水号"] for x in 冻} >= {"流-负-甲1", "流-负-乙2"}

    核 = client.get("/api/负余额闸/核证", params={"流水号": "流-负-乙2"}).json()
    assert 核["冻结有无"] == 1 and 核["valid"] is False

    抽 = client.post("/api/抽取", json={"营业日": 日}).json()
    assert 抽["闸拒"] == 0
    assert all(s["余额"] >= 0 for s in client.get("/api/快照").json())

    client.post("/api/装载夹具/解冻样例.json")
    解 = client.post("/api/负余额闸/解冻", json={"流水号": "流-负-乙2"}).json()
    assert 解["结果"] == "已解冻入正式"
    client.post("/api/抽取", json={"营业日": 日})
    assert client.get("/api/快照", params={"账户键": "户乙", "营业日": 日}).json()[0]["余额"] == 5000
