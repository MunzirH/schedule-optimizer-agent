import pandas as pd


def load_schedule(file_path):
    df = pd.read_csv(file_path)
    df["predecessors"] = df["predecessors"].fillna("")
    return df