"""Download the real freMTPL2 policy + claim-amount data (CASdatasets) into data/ as Parquet."""
import urllib.request

import pandas as pd
import rdata

from claimstream.config import settings

BASE = "https://raw.githubusercontent.com/dutangc/CASdatasets/master/data/"


def main() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    for name in ("freMTPL2freq", "freMTPL2sev"):
        out = settings.data_dir / f"{name}.parquet"
        if out.exists():
            print(f"{name}: already present")
            continue
        rda = settings.data_dir / f"{name}.rda"
        urllib.request.urlretrieve(BASE + f"{name}.rda", rda)
        df = next(iter(rdata.conversion.convert(rdata.parser.parse_file(rda)).values()))
        df["IDpol"] = pd.to_numeric(df["IDpol"].astype(str)).round().astype("int64")
        for col in df.columns:
            if isinstance(df[col].dtype, pd.CategoricalDtype):
                df[col] = df[col].astype(str)
            elif str(df[col].dtype).startswith("Int"):
                df[col] = df[col].astype("int64")
        df.to_parquet(out, index=False)
        rda.unlink()
        print(f"{name}: {len(df):,} rows")


if __name__ == "__main__":
    main()
