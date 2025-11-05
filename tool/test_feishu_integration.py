#!/usr/bin/env python3
"""测试飞书API集成功能"""

import os
import sys
sys.path.append('.')

from test import fetch_feishu_document

def test_feishu_api():
    """测试飞书API功能"""
    # 设置测试凭证（如果有的话）
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")

    if not app_id or not app_secret:
        print("警告: 未设置FEISHU_APP_ID或FEISHU_APP_SECRET环境变量")
        print("将使用模拟测试")
        return

    # 测试文档ID
    test_doc_id = "your_test_doc_id_here"  # 替换为实际的测试文档ID

    print(f"测试获取飞书文档: {test_doc_id}")
    try:
        content = fetch_feishu_document(test_doc_id, app_id, app_secret, debug=True)
        if content.startswith("【飞书API错误】"):
            print(f"API调用失败: {content}")
        else:
            print("API调用成功!")
            print(f"内容长度: {len(content)}")
            print(f"内容预览: {content[:200]}...")
    except Exception as e:
        print(f"测试异常: {e}")

if __name__ == "__main__":
    test_feishu_api()