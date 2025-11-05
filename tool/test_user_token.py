#!/usr/bin/env python3
"""
测试飞书User Access Token功能
"""

import os
import sys
import json

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test import get_feishu_user_access_token

def test_user_token():
    """测试User Access Token获取"""
    print("=== 测试飞书User Access Token功能 ===\n")

    # 这里需要一个有效的授权码
    # 在实际使用中，这个授权码需要通过OAuth流程获取
    test_code = "test_authorization_code"

    # 使用测试凭证
    app_id = "cli_a85ffa34d3fad00c"
    app_secret = "MxD6ukGa9ZMJeGl5KicVSgNQLhnE1tcN"

    print(f"App ID: {app_id}")
    print(f"App Secret: {'*' * len(app_secret)}")
    print(f"Test Code: {test_code[:10]}...")
    print()

    try:
        print("正在获取User Access Token...")
        token = get_feishu_user_access_token(app_id, app_secret, test_code, debug=True)
        print(f"✅ 成功获取User Access Token: {token[:20]}...")
    except Exception as e:
        print(f"❌ 获取User Access Token失败: {e}")
        print("这可能是因为测试授权码无效，这是正常的。")
        print("在实际使用中，需要通过OAuth流程获取有效的授权码。")

if __name__ == "__main__":
    test_user_token()