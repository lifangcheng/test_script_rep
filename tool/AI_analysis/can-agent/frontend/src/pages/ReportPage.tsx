import { Alert, Button, Card, Input, Space, Table, message } from "antd";
import { useMemo, useState } from "react";

import PageHeader from "../components/PageHeader";
import { getReport } from "../lib/api";

export default function ReportPage() {
  const [taskId, setTaskId] = useState<string>("");
  const [report, setReport] = useState<any>(null);
  const [err, setErr] = useState<string>("");

  const rows = useMemo(() => (report?.anomalies as any[] | undefined) || [], [report]);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <PageHeader title="Report" subtitle="Browse anomalies and diagnosis" />

      <Card title="Load report.json">
        <Space.Compact style={{ width: "100%" }}>
          <Input value={taskId} onChange={(e) => setTaskId(e.target.value)} placeholder="task_id" />
          <Button
            type="primary"
            onClick={async () => {
              setErr("");
              try {
                const r = await getReport(taskId);
                setReport(r);
              } catch (e: any) {
                setErr(e?.message || "Failed to load report");
                message.error(e?.message || "Failed to load report");
              }
            }}
          >
            Load
          </Button>
        </Space.Compact>
      </Card>

      {err ? <Alert type="error" message={err} /> : null}

      <Card title="Summary">
        <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(report?.stats || {}, null, 2)}</pre>
      </Card>

      <Card title="Anomalies">
        <Table
          rowKey={(r) => `${(r as any)?.kind || 'k'}-${(r as any)?.signal || 's'}-${(r as any)?.start || 't'}`}
          dataSource={rows}
          columns={[
            { title: "kind", dataIndex: "kind" },
            { title: "severity", dataIndex: "severity" },
            { title: "signal", dataIndex: "signal" },
            { title: "can_id", dataIndex: "can_id" },
            { title: "start", dataIndex: "start" },
            { title: "end", dataIndex: "end" },
            { title: "count", dataIndex: "count" },
          ]}
          pagination={{ pageSize: 10 }}
        />
      </Card>
    </div>
  );
}
