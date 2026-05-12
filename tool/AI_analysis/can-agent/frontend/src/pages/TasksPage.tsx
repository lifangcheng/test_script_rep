import { useEffect, useMemo, useState } from "react";
import { Button, Card, Form, Input, Switch, Typography, message, Space, Upload, Tabs } from "antd";
import { PlayCircleOutlined, StopOutlined, ReloadOutlined, CloudDownloadOutlined, FolderOpenOutlined } from "@ant-design/icons";

import ProgressTracker from "../components/ProgressTracker";
import TaskHistory from "../components/TaskHistory";
import { getStatus, runTask, downloadOutput, type TaskStatus, uploadBlf, uploadDbc } from "../lib/api";
import { useAppStore } from "../store/appStore";
import "../App.css";

const { Dragger } = Upload;

export default function TasksPage() {
  const [form] = Form.useForm();
  const {
    currentTask,
    setCurrentTask,
    updateTaskStatus,
    addToHistory,
    setLoading,
    setError,
    isLoading
  } = useAppStore();

  const [polling, setPolling] = useState<boolean>(false);
  const [blfUploading, setBlfUploading] = useState(false);
  const [dbcUploading, setDbcUploading] = useState(false);

  const canPoll = useMemo(() => !!currentTask?.task_id && polling, [currentTask?.task_id, polling]);

  // 轮询状态更新
  useEffect(() => {
    if (!canPoll || !currentTask?.task_id) return;

    const t = window.setInterval(async () => {
      try {
        const s = await getStatus(currentTask.task_id);
        updateTaskStatus(currentTask.task_id, s);

        if (s.status === "success" || s.status === "failed") {
          setPolling(false);
          setLoading(false);

          if (s.status === "success") {
            message.success("任务执行成功！");
          } else {
            message.error("任务执行失败！");
          }
        }
      } catch (e: any) {
        setPolling(false);
        setLoading(false);
        setError(e?.message || "获取状态失败");
        message.error(e?.message || "获取状态失败");
      }
    }, 1000);

    return () => window.clearInterval(t);
  }, [canPoll, currentTask?.task_id, updateTaskStatus, setLoading, setError]);

  const handleUpload = async (file: File, type: "blf" | "dbc") => {
    try {
      type === "blf" ? setBlfUploading(true) : setDbcUploading(true);
      const res = type === "blf" ? await uploadBlf(file) : await uploadDbc(file);
      const field = type === "blf" ? "blf_path" : "dbc_path";
      form.setFieldsValue({ [field]: res.path });
      message.success(`${type.toUpperCase()} 上传成功`);
      return false; // 阻止 antd 自动上传
    } catch (e: any) {
      message.error(e?.message || "上传失败");
      return false;
    } finally {
      type === "blf" ? setBlfUploading(false) : setDbcUploading(false);
    }
  };

  // 处理表单提交
  const handleSubmit = async (values: any) => {
    try {
      setLoading(true);
      setError(null);

      const res = await runTask(values);
      const newTask: TaskStatus = {
        task_id: res.task_id,
        status: "pending",
        output_dir: values.output_dir,
      };

      setCurrentTask(newTask);
      addToHistory(newTask);
      setPolling(true);

      message.success(`任务已启动: ${res.task_id}`);
    } catch (e: any) {
      setLoading(false);
      setError(e?.message || "启动任务失败");
      message.error(e?.message || "启动任务失败");
    }
  };

  // 停止轮询
  const handleStopPolling = () => {
    setPolling(false);
    setLoading(false);
    message.info("已停止状态监控");
  };

  // 重新开始监控
  const handleRestartPolling = () => {
    if (currentTask?.task_id) {
      setPolling(true);
      setLoading(true);
      message.info("重新开始状态监控");
    }
  };

  // 清除当前任务
  const handleClearTask = () => {
    setCurrentTask(null);
    setPolling(false);
    setLoading(false);
    form.resetFields();
  };

  const handleDownload = async () => {
    if (!currentTask?.task_id) return;
    try {
      message.loading({ content: "正在打包并下载...", key: "dl" });
      const blob = await downloadOutput(currentTask.task_id);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${currentTask.task_id}.zip`;
      a.click();
      window.URL.revokeObjectURL(url);
      message.success({ content: "下载完成", key: "dl" });
    } catch (e: any) {
      message.error(e?.message || "下载失败");
    }
  };

  const uploaderProps = (type: "blf" | "dbc") => ({
    name: "file",
    multiple: false,
    showUploadList: false,
    beforeUpload: (file: File) => handleUpload(file, type),
    accept: type === "blf" ? ".blf" : ".dbc",
  });

  return (
    <div className="page-shell" style={{ gridTemplateColumns: "minmax(360px, 460px) 1fr" }}>
      <div style={{ display: "grid", gap: 16 }}>
        <Card className="card" title="任务配置" extra={
          currentTask && (
            <Button type="text" danger onClick={handleClearTask} size="small">清除</Button>
          )
        }>
          <Tabs
            defaultActiveKey="path"
            items={[
              {
                key: "path",
                label: "直接填写路径",
                children: (
                  <Form
                    form={form}
                    layout="vertical"
                    initialValues={{ enable_ai: false, output_dir: "outputs" }}
                    onFinish={handleSubmit}
                    disabled={isLoading}
                    className="form-grid"
                  >
                    <Form.Item
                      name="blf_path"
                      label="BLF 文件"
                      rules={[{ required: true, message: "请输入 BLF 文件路径" }]}
                      tooltip="支持本地绝对路径"
                    >
                      <Input placeholder="D:\\logs\\demo.blf" allowClear />
                    </Form.Item>

                    <Form.Item
                      name="dbc_path"
                      label="DBC 文件"
                      rules={[{ required: true, message: "请输入 DBC 文件路径" }]}
                    >
                      <Input placeholder="D:\\dbc\\spec.dbc" allowClear />
                    </Form.Item>

                    <Form.Item name="config_path" label="配置文件 (可选)">
                      <Input placeholder="D:\\config\\can.yaml" allowClear />
                    </Form.Item>

                    <Form.Item name="output_dir" label="输出目录">
                      <Input placeholder="outputs" allowClear />
                    </Form.Item>

                    <Form.Item name="enable_ai" label="启用 AI 分析" valuePropName="checked">
                      <Switch />
                    </Form.Item>

                    <Form.Item>
                      <Button
                        type="primary"
                        htmlType="submit"
                        loading={isLoading}
                        icon={<PlayCircleOutlined />}
                        block
                      >
                        {isLoading ? "运行中..." : "开始运行"}
                      </Button>
                    </Form.Item>
                  </Form>
                )
              },
              {
                key: "upload",
                label: "上传文件",
                children: (
                  <div className="form-grid">
                    <Dragger {...uploaderProps("blf")} disabled={blfUploading}>
                      <p className="ant-upload-drag-icon"><FolderOpenOutlined /></p>
                      <p className="ant-upload-text">点击或拖拽 BLF 文件</p>
                      <p className="ant-upload-hint">上传后自动填入路径</p>
                    </Dragger>
                    <Dragger {...uploaderProps("dbc")} disabled={dbcUploading}>
                      <p className="ant-upload-drag-icon"><FolderOpenOutlined /></p>
                      <p className="ant-upload-text">点击或拖拽 DBC 文件</p>
                      <p className="ant-upload-hint">上传后自动填入路径</p>
                    </Dragger>
                    <Button
                      type="primary"
                      icon={<PlayCircleOutlined />}
                      loading={isLoading}
                      block
                      style={{ marginTop: 8 }}
                      onClick={() => form.submit()}
                    >
                      {isLoading ? "运行中..." : "开始运行"}
                    </Button>
                  </div>
                )
              }
            ]}
          />
        </Card>

        <Card className="card" title="任务历史">
          <TaskHistory />
        </Card>
      </div>

      <div style={{ display: "grid", gap: 16 }}>
        <Card className="card" title="当前任务" extra={currentTask?.task_id ? <Typography.Text code>{currentTask.task_id}</Typography.Text> : null}>
          {currentTask ? (
            <div className="result-grid">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <Typography.Text type="secondary">任务 ID</Typography.Text>
                  <div><Typography.Text code>{currentTask.task_id}</Typography.Text></div>
                </div>
                <Space>
                  {polling ? (
                    <Button icon={<StopOutlined />} onClick={handleStopPolling}>停止监控</Button>
                  ) : (
                    <Button icon={<ReloadOutlined />} onClick={handleRestartPolling} disabled={!currentTask}>重新监控</Button>
                  )}
                  <Button icon={<CloudDownloadOutlined />} onClick={handleDownload} disabled={!currentTask}>
                    下载结果
                  </Button>
                </Space>
              </div>

              <ProgressTracker
                taskId={currentTask.task_id}
                status={currentTask.status}
                logs={currentTask.logs || []}
                error={currentTask.error}
                outputDir={currentTask.output_dir}
              />

              {currentTask.output_dir && (
                <div>
                  <Typography.Text type="secondary">输出目录</Typography.Text>
                  <div><Typography.Text>{currentTask.output_dir}</Typography.Text></div>
                </div>
              )}
            </div>
          ) : (
            <div style={{ textAlign: "center", color: "#8a94a6", padding: "48px 0" }}>
              <PlayCircleOutlined style={{ fontSize: 40, marginBottom: 12 }} />
              <Typography.Title level={4} type="secondary">暂无任务</Typography.Title>
              <Typography.Text type="secondary">在左侧填写或上传 BLF/DBC 后开始运行</Typography.Text>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
