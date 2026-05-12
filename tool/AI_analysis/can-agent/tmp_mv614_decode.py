import sys
from pathlib import Path
import pandas as pd
from core.blf_reader import read_blf
from core.dbc_decoder import decode_with_dbc

def main():
    blf = r"D:\project\TestCase_auto_gen\tool\AI_analysis\can-agent\MV614_HXMQMLSUTMPVPPAT5_合并文件_20260331212041.blf"
    dbc = r"D:\project\TestCase_auto_gen\tool\AI_analysis\can-agent\MS12&MS13_EDCU_PTCANFD_251301.dbc"
    out = Path(r"outputs/run_mv614_edcu251301_manual")
    out.mkdir(parents=True, exist_ok=True)

    raw = read_blf(blf, chunk_size=200_000)
    res = decode_with_dbc(dbc, raw.value, allow_unknown_ids=True)
    print("decode ok", res.ok, "error", res.error if not res.ok else None)
    if not res.ok:
        sys.exit(1)
    df = res.value
    print("rows", len(df), "signals", df.signal.nunique(), "messages", df.message.nunique())
    print(df.head())

    # write via pickle to avoid parquet dependencies
    df.to_pickle(out / "decoded.pkl")
    df.head(200).to_csv(out / "decoded_head.csv", index=False)
    print("written", out / "decoded.pkl")

if __name__ == "__main__":
    main()
