import csv
import json
import sys
from io import StringIO
from typing import List, Dict

def parse_csv(csv_string: str) -> List[Dict]:
    """
    Parses a CSV string and returns a list of dictionaries.
    Each dictionary represents a row, with headers as keys.
    """
    f = StringIO(csv_string)
    reader = csv.DictReader(f)
    return list(reader)

if __name__ == "__main__":
    csv_input = sys.stdin.read()
    parsed_data = parse_csv(csv_input)
    json_output = json.dumps(parsed_data, indent=2)
    print(json_output)
