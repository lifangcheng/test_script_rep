import { Alert, Card, Input, List, Space, message } from "antd";
import ReactECharts from "echarts-for-react";
import { useEffect, useMemo, useState } from "react";

import PageHeader from "../components/PageHeader";
import { getSignal, listSignals } from "../lib/api";

export default function SignalsPage() {
  const [taskId, setTaskId] = useState<string>("");
  const [idx, setIdx] = useState<any>(null);
  const [signal, setSignal] = useState<string>("");
  const [signalData, setSignalData] = useState<any>(null);
  const [err, setErr] = useState<string>("");

  useEffect(() => {
    setIdx(null);
    setSignal("");
    setSignalData(null);
  }, [taskId]);

  const option = useMemo(() => {
    if (!signalData) return { series: [] };

    const ts: number[] = signalData.series?.timestamp || [];
    const vs: any[] = signalData.series?.value || [];

    const marks = (signalData.anomalies || []).map((a: any) => ({
      name: `${a.kind}(${a.severity})`,
      xAxis: a.start,
    }));

    return {
      tooltip: { trigger: "axis" },
      xAxis: { type: "value", name: "t" },
      yAxis: { type: "value", name: signalData.unit || "" },
      series: [
        {
          type: "line",
          showSymbol: false,
          data: ts.map((t, i) => [t, vs[i]]),
          markPoint: { data: marks },
        },
      ],
    };
  }, [signalData]);

  return (
    <div style={{ display: "grid", gap: 16, gridTemplateColumns: "360px 1fr" }}>
      <div style={{ display: "grid", gap: 16 }}>
        <PageHeader title="Signals" subtitle="Search and visualize a single signal" />

        <Card title="Load signals index">
          <Space direction="vertical" style={{ width: "100%" }}>
            <Input value={taskId} onChange={(e) => setTaskId(e.target.value)} placeholder="task_id" />
            <a
              onClick={async () => {
                setErr("");
                try {
                  const r = await listSignals(taskId);
                  setIdx(r);
                } catch (e: any) {
                  setErr(e?.message || "Failed to load signals");
                  message.error(e?.message || "Failed to load signals");
                }
              }}
            >
              Load
            </a>
          </Space>
        </Card>

        {err ? <Alert type="error" message={err} /> : null}

        <Card title={`Signals (${idx?.total_signals || 0})`} bodyStyle={{ padding: 0 }}>
          <List
            size="small"
            dataSource={idx?.signals || []}
            renderItem={(item: any) => (
              <List.Item
                style={{ cursor: "pointer" }}
                onClick={async () => {
                  try {
                    setSignal(String(item.signal));
                    const d = await getSignal(taskId, String(item.signal));
                    setSignalData(d);
                  } catch (e: any) {
                    message.error(e?.message || "Failed to load signal data");
                  }
                }}
              >
                <div style={{ width: "100%" }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span>{item.signal}</span>
                    <span style={{ opacity: 0.7 }}>{item.anomaly_count}</span>
                  </div>
                </div>
              </List.Item>
            )}
          />
        </Card>
      </div>

      <div style={{ display: "grid", gap: 16 }}>
        <Card title={signal ? `Trend: ${signal}` : "Select a signal"}>
          <ReactECharts option={option} style={{ height: 520 }} />
        </Card>
        <Card title="Signal JSON">
          <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(signalData, null, 2)}</pre>
        </Card>
      </div>
    </div>
  );
}
