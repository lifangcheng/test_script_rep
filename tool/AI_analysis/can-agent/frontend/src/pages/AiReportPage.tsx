import { Alert, Button, Card, Input, Space, message } from "antd";
import { useState } from "react";

import PageHeader from "../components/PageHeader";
import { getAiReport } from "../lib/api";

export default function AiReportPage() {
  const [taskId, setTaskId] = useState<string>("");
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string>("");

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <PageHeader title="AI Report" subtitle="Root cause analysis and suggestions" />

      <Card title="Load ai_report.json">
        <Space.Compact style={{ width: "100%" }}>
          <Input value={taskId} onChange={(e) => setTaskId(e.target.value)} placeholder="task_id" />
          <Button
            type="primary"
            onClick={async () => {
              setErr("");
              try {
                const r = await getAiReport(taskId);
                setData(r);
              } catch (e: any) {
                setErr(e?.message || "Failed to load AI report");
                message.error(e?.message || "Failed to load AI report");
              }
            }}
          >
            Load
          </Button>
        </Space.Compact>
      </Card>

      {err ? <Alert type="error" message={err} /> : null}

      <Card title="AI Report JSON">
        <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(data, null, 2)}</pre>
      </Card>
    </div>
  );
}
