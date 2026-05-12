import { Breadcrumb, Space, Typography } from "antd";

export default function PageHeader(props: { title: string; subtitle?: string; crumbs?: string[] }) {
  return (
    <Space direction="vertical" size={4} style={{ width: "100%" }}>
      {props.crumbs?.length ? (
        <Breadcrumb items={props.crumbs.map((c) => ({ title: c }))} />
      ) : null}
      <Typography.Title level={3} style={{ margin: 0 }}>
        {props.title}
      </Typography.Title>
      {props.subtitle ? <Typography.Text type="secondary">{props.subtitle}</Typography.Text> : null}
    </Space>
  );
}
