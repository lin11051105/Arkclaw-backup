import sys
import uuid

import requests

if __name__ == "__main__":
    task_prompt = sys.argv[1]
    task_id = str(uuid.uuid4())

    response = requests.post(
        "http://127.0.0.1:8301/task", json={"prompt": task_prompt}
    )
    print(response.text)
