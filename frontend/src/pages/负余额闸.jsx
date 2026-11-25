import React, { useEffect, useState } from "react";
import { api } from "../api.js";

const 参 = (o = {}) => {
  const u = new URLSearchParams();
  Object.entries(o).forEach(([k, v]) => v && u.append(k, v));
  const s = u.toString();
  return s ? `?${s}` : "";
};

export default function 负余额闸页() {
  const [台参, set台参] = useState({});
  const [冻结, set冻结] = useState([]);
  const [决策, set决策] = useState([]);
  const [核号, set核号] = useState("");
  const [核证, set核证] = useState(null);
  const [讯, set讯] = useState("");

  const 刷新 = () =>
    Promise.all([api.台参(), api.闸冻结(), api.闸决策()]).then(([c, f, d]) => {
      set台参(c);
      set冻结(f);
      set决策(d);
    });

  useEffect(() => {
    刷新().catch((e) => set讯(String(e.message || e)));
  }, []);

  const 闸启 = 台参["禁止负余额"] === "开";

  return (
    <div>
      <h1 className="题">负余额闸（冻结流水轨）</h1>
      <p className="述">
        拟负笔不入正式流水，写入冻结轨：按流水号可查冻结行、正式净额不变；抽取同源拟算并跳过冻结轨，
        拟负拒写有效镜；解冻重新拟算，过闸才入正式净额并可抽，仍负保持冻结（失败闭）。
      </p>
      <div className="行">
        <span className={`徽章 ${闸启 ? "通" : "败"}`}>{闸启 ? "闸开 · 禁止负余额" : "闸关"}</span>
        <button onClick={() => api.闸开关(!闸启).then(刷新).then(() => set讯(`闸已${闸启 ? "关" : "开"}`)).catch((e) => set讯(String(e.message || e)))}>
          {闸启 ? "关闭闸" : "开启闸"}
        </button>
        <button className="次" onClick={() => 刷新().catch((e) => set讯(String(e.message || e)))}>刷新</button>
      </div>
      {讯 ? <p className="讯">{讯}</p> : null}

      <div className="段">
        <h2 className="段题">核证（拟余额 / 路径 / 冻结有无 / valid）</h2>
        <div className="行">
          <input value={核号} onChange={(e) => set核号(e.target.value)} placeholder="流水号" />
          <button
            onClick={() =>
              api
                .闸核证(参({ 流水号: 核号.trim() }))
                .then(set核证)
                .catch((e) => set讯(String(e.message || e)))
            }
          >
            核证
          </button>
        </div>
        {核证 ? (
          <table>
            <tbody>
              <tr><th>命中</th><td>{String(核证.命中)}</td></tr>
              <tr><th>流水号</th><td>{核证.流水号 || "—"}</td></tr>
              <tr><th>拟余额</th><td>{核证.拟余额 ?? "—"}</td></tr>
              <tr><th>路径</th><td>{核证.路径 || "—"}</td></tr>
              <tr><th>冻结有无</th><td>{核证.冻结有无}</td></tr>
              <tr><th>valid</th><td>{核证.valid === null ? "—" : String(核证.valid)}</td></tr>
              <tr><th>原因</th><td>{核证.原因 || "—"}</td></tr>
              <tr><th>正式流水</th><td>{核证.正式流水 ? "命中" : "空（按流水号查无正式行）"}</td></tr>
              <tr><th>冻结行</th><td>{核证.冻结行 ? `命中 · ${核证.冻结行.状态}` : "无"}</td></tr>
            </tbody>
          </table>
        ) : (
          <div className="空态">输入流水号核证</div>
        )}
      </div>

      <div className="段">
        <h2 className="段题">冻结流水轨</h2>
        {!冻结.length ? (
          <div className="空态">无冻结</div>
        ) : (
          <table>
            <thead>
              <tr><th>流水号</th><th>账户键</th><th>营业日</th><th>变动额</th><th>拟余额</th><th>状态</th><th>操作</th></tr>
            </thead>
            <tbody>
              {冻结.map((r) => (
                <tr key={r.流水号}>
                  <td>{r.流水号}</td>
                  <td>{r.账户键}</td>
                  <td>{r.营业日}</td>
                  <td>{r.变动额}</td>
                  <td>{r.拟余额}</td>
                  <td><span className={`徽章 ${r.状态 === "冻结中" ? "败" : "通"}`}>{r.状态}</span></td>
                  <td>
                    {r.状态 === "冻结中" ? (
                      <button
                        className="次"
                        onClick={() =>
                          api
                            .闸解冻(r.流水号)
                            .then((x) => set讯(`${r.流水号}：${x.result}${x.入账 ? "，已入正式" : "，仍冻结"}`))
                            .then(刷新)
                            .catch((e) => set讯(String(e.message || e)))
                        }
                      >
                        解冻
                      </button>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="段">
        <h2 className="段题">闸决策（装载 / 日终抽取 / 解冻 同源留痕）</h2>
        {!决策.length ? (
          <div className="空态">无决策</div>
        ) : (
          <table>
            <thead>
              <tr><th>时刻</th><th>路径</th><th>流水号</th><th>账户键</th><th>营业日</th><th>拟余额</th><th>冻结有无</th><th>valid</th><th>原因</th></tr>
            </thead>
            <tbody>
              {决策.map((r) => (
                <tr key={r.编号}>
                  <td>{r.时刻}</td>
                  <td>{r.路径}</td>
                  <td>{r.流水号 || "—"}</td>
                  <td>{r.账户键}</td>
                  <td>{r.营业日}</td>
                  <td>{r.拟余额}</td>
                  <td>{r.冻结有无}</td>
                  <td><span className={`徽章 ${r.valid ? "通" : "败"}`}>{String(!!r.valid)}</span></td>
                  <td>{r.原因}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
