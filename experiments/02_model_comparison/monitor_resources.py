"""Sample global memory conditions; these cannot be attributed solely to the model."""
import json
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def main():
    folder = Path((ROOT / 'LATEST_RESULT.txt').read_text().strip())
    deadline = time.monotonic() + 7200
    with (folder / 'system_memory_samples.jsonl').open('a') as output:
        while time.monotonic() < deadline:
            try:
                state = json.loads((folder / 'summary.json').read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                state = {}
            if state.get('complete'):
                break
            sample = {'utc': datetime.now(timezone.utc).isoformat()}
            try:
                sample['swap'] = subprocess.check_output(['sysctl','-n','vm.swapusage'],text=True).strip()
                sample['system_memory'] = subprocess.check_output(['memory_pressure','-Q'],text=True).splitlines()[-1]
                with urllib.request.urlopen('http://127.0.0.1:11434/api/ps', timeout=5) as response:
                    sample['loaded_models'] = json.load(response).get('models', [])
            except Exception as exc:
                sample['error'] = str(exc)
            output.write(json.dumps(sample, ensure_ascii=False) + '\n')
            output.flush()
            time.sleep(5)

if __name__ == '__main__':
    main()
