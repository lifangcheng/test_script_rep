import requests
import sys

FEISHU_APP_ID = "cli_a85ffa34d3fad00c"
FEISHU_APP_SECRET = "MxD6ukGa9ZMJeGl5KicVSgNQLhnE1tcN"

def get_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
    resp = requests.post(url, json=payload)
    return resp.json().get("tenant_access_token")

def test_sheet(token, spreadsheet_token, sheet_id=None):
    print(f"Testing Sheet: {spreadsheet_token}, SheetID: {sheet_id}")
    
    # 1. Get Sheets Info
    url_meta = f"https://open.feishu.cn/open-apis/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url_meta, headers=headers)
    print("Meta Resp:", resp.json())
    
    sheets = resp.json().get("data", {}).get("sheets", [])
    if not sheets:
        print("No sheets found")
        return

    target_sheet_id = None
    if sheet_id:
        # Try to match by sheet_id (which might be the 'sheetId' or part of it)
        # The URL param ?sheet=HiQfbl usually corresponds to sheetId.
        for s in sheets:
            if s["sheet_id"] == sheet_id:
                target_sheet_id = s["sheet_id"]
                break
    
    if not target_sheet_id:
        target_sheet_id = sheets[0]["sheet_id"]
        print(f"Using first sheet: {target_sheet_id}")
    else:
        print(f"Found target sheet: {target_sheet_id}")
    
    # 2. Get Values
    # Range: sheetId!A1:Z100 (approx)
    range_str = f"{target_sheet_id}!A1:Z100"
    url_values = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values/{range_str}"
    resp_val = requests.get(url_values, headers=headers)
    data = resp_val.json()
    print("Values Resp Code:", data.get("code"))
    if data.get("code") == 0:
        values = data.get("data", {}).get("valueRange", {}).get("values", [])
        print(f"Got {len(values)} rows")
        for row in values[:5]:
            print(row)
    else:
        print("Error getting values:", data.get("msg"))

if __name__ == "__main__":
    token = get_token()
    if token:
        test_sheet(token, "RqJQsh6vkhnIdot65m8c6iQNnIg", "HiQfbl")
    else:
        print("Failed to get token")