#!/usr/bin/env python3
"""
飞书API配置测试脚本
"""

import os
import requests
import json

# 飞书API常量
FEISHU_BASE_API = "https://open.feishu.cn"
FEISHU_TOKEN_ENDPOINT = f"{FEISHU_BASE_API}/open-apis/auth/v3/tenant_access_token/internal"

def test_feishu_credentials():
    """测试飞书API凭证"""
    print("=== 飞书API凭证测试 ===\n")

    # 硬编码凭证
    app_id = "cli_a85ffa34d3fad00c"
    app_secret = "MxD6ukGa9ZMJeGl5KicVSgNQLhnE1tcN"

    print(f"App ID: {app_id}")
    print(f"App Secret: {'已设置' if app_secret else '未设置'}")

    if not app_id or not app_secret:
        print("\n❌ 错误：飞书API凭证未配置")
        print("\n请按照以下步骤配置：")
        print("1. 访问 https://open.feishu.cn/app")
        print("2. 创建企业自建应用")
        print("3. 获取 App ID 和 App Secret")
        print("4. 在应用权限管理中添加 docx:document 和 wiki:wiki 权限")
        print("5. 在Streamlit应用侧边栏输入凭证")
        return False

    # 测试token获取
    print("\n--- 测试Token获取 ---")
    try:
        payload = {"app_id": app_id, "app_secret": app_secret}
        response = requests.post(FEISHU_TOKEN_ENDPOINT, json=payload, timeout=10)

        print(f"HTTP状态码: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"API响应: {json.dumps(data, ensure_ascii=False, indent=2)}")

            if data.get("code") == 0:
                token = data.get("tenant_access_token")
                print(f"\n✅ Token获取成功: {token[:20]}...")
                return True
            else:
                print(f"\n❌ API错误: {data.get('msg')}")
                return False
        else:
            print(f"\n❌ HTTP错误: {response.status_code}")
            print(f"响应内容: {response.text}")
            return False

    except Exception as e:
        print(f"\n❌ 网络错误: {e}")
        return False

def test_wiki_access():
    """测试wiki文档访问"""
    print("\n=== Wiki文档访问测试 ===\n")

    # 硬编码凭证
    app_id = "cli_a85ffa34d3fad00c"
    app_secret = "MxD6ukGa9ZMJeGl5KicVSgNQLhnE1tcN"

    if not app_id or not app_secret:
        print("❌ 跳过wiki测试：凭证未配置")
        return

    # 测试URL
    test_url = "https://mi.feishu.cn/wiki/UCyVwffRsiTXgYk9TlHcV2lUn8c"
    print(f"测试URL: {test_url}")

    try:
        # 获取token
        payload = {"app_id": app_id, "app_secret": app_secret}
        resp = requests.post(FEISHU_TOKEN_ENDPOINT, json=payload, timeout=10)

        if resp.status_code != 200:
            print(f"❌ Token获取失败: {resp.status_code}")
            return

        data = resp.json()
        if data.get("code") != 0:
            print(f"❌ Token API错误: {data.get('msg')}")
            return

        token = data.get("tenant_access_token")
        headers = {"Authorization": f"Bearer {token}"}

        # 提取文档ID
        import re
        m = re.search(r"/wiki/([A-Za-z0-9]+)", test_url)
        if not m:
            print("❌ 无法提取文档ID")
            return

        wiki_token = m.group(1)
        print(f"Wiki Token: {wiki_token}")

        # 获取wiki节点信息
        wiki_url = f"{FEISHU_BASE_API}/open-apis/wiki/v2/spaces/get_node"
        wiki_payload = {"token": wiki_token, "obj_type": "doc"}

        print("正在获取wiki节点信息...")
        wiki_resp = requests.post(wiki_url, json=wiki_payload, headers=headers, timeout=10)

        print(f"Wiki API状态码: {wiki_resp.status_code}")

        if wiki_resp.status_code == 200:
            wiki_data = wiki_resp.json()
            print(f"Wiki API响应: {json.dumps(wiki_data, ensure_ascii=False, indent=2)}")

            if wiki_data.get("code") == 0:
                node_info = wiki_data.get("data", {}).get("node", {})
                doc_token = node_info.get("obj_token")

                if doc_token:
                    print(f"✅ 获取到文档Token: {doc_token}")
                    print("Wiki文档访问配置正确！")
                else:
                    print("❌ 无法获取文档Token")
            else:
                print(f"❌ Wiki API错误: {wiki_data.get('msg')}")
        else:
            print(f"❌ Wiki API HTTP错误: {wiki_resp.status_code}")
            print(f"响应内容: {wiki_resp.text}")

    except Exception as e:
        print(f"❌ 测试异常: {e}")

if __name__ == "__main__":
    success = test_feishu_credentials()
    if success:
        test_wiki_access()