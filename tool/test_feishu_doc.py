#!/usr/bin/env python3
"""
测试修改后的飞书文档获取功能
"""

from test import fetch_feishu_document

def test_feishu_document_access():
    """测试飞书文档访问"""
    print("=== 测试飞书文档访问 ===\n")

    test_url = "https://mi.feishu.cn/wiki/UCyVwffRsiTXgYk9TlHcV2lUn8c"
    print(f"测试URL: {test_url}")

    try:
        result = fetch_feishu_document(test_url, debug=True)
        print(f"\n最终结果:\n{repr(result)}")

        if result and not result.startswith("【飞书API错误】"):
            print("\n✅ 文档获取成功！")
            print(f"内容长度: {len(result)} 字符")
            print(f"内容预览: {result[:200]}...")
        else:
            print("\n❌ 文档获取失败")
            if result:
                print(f"错误信息: {result}")

    except Exception as e:
        print(f"\n❌ 异常: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_feishu_document_access()