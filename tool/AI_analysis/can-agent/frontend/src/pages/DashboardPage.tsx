import { Alert, Card, Input, Space, Statistic, Typography, message, Row, Col, Button, Tag, Progress } from "antd";
import {
  ReloadOutlined,
  FileTextOutlined,
  BarChartOutlined,
  WarningOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined
} from "@ant-design/icons";
import ReactECharts from "echarts-for-react";
import { useMemo, useState } from "react";

import PageHeader from "../components/PageHeader";
import TaskHistory from "../components/TaskHistory";
import { getReport } from "../lib/api";
import { useAppStore } from "../store/appStore";

export default function DashboardPage() {
  const { currentTask, taskHistory } = useAppStore();
  const [taskId, setTaskId] = useState<string>("");
  const [report, setReport] = useState<any>(null);
  const [err, setErr] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const stats = report?.stats || {};
  const anomalies = report?.anomalies || [];

  // 异常分布图表
  const byKind = useMemo(() => {
    const m = new Map<string, number>();
    for (const a of anomalies) {
      const k = String(a.kind);
      m.set(k, (m.get(k) || 0) + 1);
    }
    return Array.from(m.entries()).map(([name, value]) => ({ name, value }));
  }, [anomalies]);

  const pieOption = useMemo(() => {
    return {
      tooltip: { trigger: "item" },
      legend: { top: "bottom" },
      series: [
        {
          name: "异常类型",
          type: "pie",
          radius: ["40%", "70%"],
          data: byKind,
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowOffsetX: 0,
              shadowColor: 'rgba(0, 0, 0, 0.5)'
            }
          }
        },
      ],
    };
  }, [byKind]);

  // 严重程度分布
  const bySeverity = useMemo(() => {
    const m = new Map<string, number>();
    for (const a of anomalies) {
      const k = String(a.severity);
      m.set(k, (m.get(k) || 0) + 1);
    }
    return Array.from(m.entries()).map(([name, value]) => ({ name, value }));
  }, [anomalies]);

  const barOption = useMemo(() => {
    return {
      tooltip: { trigger: "axis" },
      xAxis: {
        type: 'category',
        data: bySeverity.map(item => item.name)
      },
      yAxis: {
        type: 'value'
      },
      series: [{
        type: 'bar',
        data: bySeverity.map(item => item.value),
        itemStyle: {
          color: function(params: any) {
            const colorList = ['#ff4d4f', '#faad14', '#fa8c16', '#52c41a'];
            return colorList[params.dataIndex] || '#1890ff';
          }
        }
      }]
    };
  }, [bySeverity]);

  // 加载报告
  const handleLoadReport = async () => {
    if (!taskId.trim()) {
      message.warning("请输入任务ID");
      return;
    }

    setErr("");
    setLoading(true);
    
    try {
      const r = await getReport(taskId);
      setReport(r);
      message.success("报告加载成功");
    } catch (e: any) {
      setErr(e?.message || "加载报告失败");
      message.error(e?.message || "加载报告失败");
    } finally {
      setLoading(false);
    }
  };

  // 快速加载当前任务报告
  const handleLoadCurrentTask = async () => {
    if (currentTask?.task_id) {
      setTaskId(currentTask.task_id);
      try {
        const r = await getReport(currentTask.task_id);
        setReport(r);
        message.success("当前任务报告加载成功");
      } catch (e: any) {
        setErr(e?.message || "加载当前任务报告失败");
        message.error(e?.message || "加载当前任务报告失败");
      }
    }
  };

  // 获取最近任务状态概览
  const recentTasksSummary = useMemo(() => {
    const successCount = taskHistory.filter(t => t.status === 'success').length;
    const failedCount = taskHistory.filter(t => t.status === 'failed').length;
    const runningCount = taskHistory.filter(t => t.status === 'running').length;
    
    return { successCount, failedCount, runningCount };
  }, [taskHistory]);

  return (
    <div style={{ display: "grid", gap: 24 }}>
      <PageHeader 
        title="仪表板" 
        subtitle="高级异常统计和任务概览" 
      />

      {/* 顶部状态卡片 */}
      <Row gutter={16}>
        <Col span={6}>
          <Card>
            <Statistic
              title="总任务数"
              value={taskHistory.length}
              prefix={<FileTextOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="成功任务"
              value={recentTasksSummary.successCount}
              prefix={<CheckCircleOutlined />}
              valueStyle={{ color: '#3f8600' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="失败任务"
              value={recentTasksSummary.failedCount}
              prefix={<WarningOutlined />}
              valueStyle={{ color: '#cf1322' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="运行中"
              value={recentTasksSummary.runningCount}
              prefix={<ClockCircleOutlined />}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 当前任务状态 */}
      {currentTask && (
        <Card 
          title="当前任务状态"
          extra={
            <Button 
              type="primary" 
              icon={<ReloadOutlined />}
              onClick={handleLoadCurrentTask}
              size="small"
            >
              加载报告
            </Button>
          }
        >
          <Row gutter={16}>
            <Col span={12}>
              <div style={{ marginBottom: 16 }}>
                <Typography.Text strong>任务ID: </Typography.Text>
                <Typography.Text code>{currentTask.task_id}</Typography.Text>
              </div>
              <div style={{ marginBottom: 16 }}>
                <Typography.Text strong>状态: </Typography.Text>
                <Tag color={
                  currentTask.status === 'success' ? 'success' : 
                  currentTask.status === 'failed' ? 'error' : 
                  currentTask.status === 'running' ? 'processing' : 'default'
                }>
                  {currentTask.status === 'success' ? '成功' : 
                   currentTask.status === 'failed' ? '失败' : 
                   currentTask.status === 'running' ? '运行中' : '等待'}
                </Tag>
              </div>
              {currentTask.output_dir && (
                <div>
                  <Typography.Text strong>输出目录: </Typography.Text>
                  <Typography.Text>{currentTask.output_dir}</Typography.Text>
                </div>
              )}
            </Col>
            <Col span={12}>
              {currentTask.logs && currentTask.logs.length > 0 && (
                <div>
                  <Typography.Text strong>处理进度: </Typography.Text>
                  <Progress 
                    percent={Math.round((currentTask.logs.filter(l => l.status === 'success').length / 9) * 100)} 
                    size="small"
                    status={currentTask.status === 'failed' ? 'exception' : 'active'}
                  />
                </div>
              )}
            </Col>
          </Row>
        </Card>
      )}

      <Row gutter={24}>
        {/* 左侧：报告加载和统计 */}
        <Col span={16}>
          <div style={{ display: "grid", gap: 24 }}>
            {/* 报告加载 */}
            <Card title="加载报告数据">
              <Space.Compact style={{ width: "100%" }}>
                <Input 
                  value={taskId} 
                  onChange={(e) => setTaskId(e.target.value)} 
                  placeholder="输入任务ID加载报告" 
                  onPressEnter={handleLoadReport}
                />
                <Button 
                  type="primary" 
                  onClick={handleLoadReport}
                  loading={loading}
                >
                  加载
                </Button>
              </Space.Compact>
              {err && <Alert type="error" message={err} style={{ marginTop: 16 }} />}
            </Card>

            {/* 统计卡片 */}
            {report && (
              <>
                <Row gutter={16}>
                  <Col span={6}>
                    <Card>
                      <Statistic 
                        title="数据行数" 
                        value={stats.rows || 0} 
                        prefix={<BarChartOutlined />}
                      />
                    </Card>
                  </Col>
                  <Col span={6}>
                    <Card>
                      <Statistic 
                        title="信号数量" 
                        value={stats.signals || 0} 
                        prefix={<BarChartOutlined />}
                      />
                    </Card>
                  </Col>
                  <Col span={6}>
                    <Card>
                      <Statistic 
                        title="CAN帧数" 
                        value={stats.frames || 0} 
                        prefix={<BarChartOutlined />}
                      />
                    </Card>
                  </Col>
                  <Col span={6}>
                    <Card>
                      <Statistic 
                        title="异常数量" 
                        value={stats.anomalies || 0} 
                        prefix={<WarningOutlined />}
                        valueStyle={{ color: '#cf1322' }}
                      />
                    </Card>
                  </Col>
                </Row>

                {/* 图表 */}
                <Row gutter={24}>
                  <Col span={12}>
                    <Card title="异常类型分布">
                      <ReactECharts option={pieOption} style={{ height: 300 }} />
                    </Card>
                  </Col>
                  <Col span={12}>
                    <Card title="严重程度分布">
                      <ReactECharts option={barOption} style={{ height: 300 }} />
                    </Card>
                  </Col>
                </Row>
              </>
            )}
          </div>
        </Col>

        {/* 右侧：任务历史 */}
        <Col span={8}>
          <TaskHistory />
        </Col>
      </Row>
    </div>
  );
}