#!/bin/bash

# Replace with your 4 EC2 instance IDs
INSTANCE_IDS="i-0b96e4c108e5d3b8a,i-00283969519116462,i-0947fbb97472402b8"

# Replace with your AWS region
REGION="us-east-1"

# Run AWS SSM command to push and execute Python CPU spike on all 4 instances
aws ssm send-command \
  --targets "Key=instanceIds,Values=$INSTANCE_IDS" \
  --document-name "AWS-RunShellScript" \
  --comment "Run Python CPU spike on all 4 instances" \
  --parameters 'commands=[
"cat > /tmp/cpu_spike.py <<EOF
import time

def simulate_cpu_spike(duration=30, cpu_percent=80):
    print(f\"Simulating CPU spike at {cpu_percent}%...\")
    start_time = time.time()

    target_percent = cpu_percent / 100
    total_iterations = int(target_percent * 5_000_000)

    for _ in range(total_iterations):
        result = 0
        for i in range(1, 1001):
            result += i

    elapsed_time = time.time() - start_time
    remaining_time = max(0, duration - elapsed_time)
    time.sleep(remaining_time)

    print(\"CPU spike simulation completed.\")

if __name__ == '__main__':
    simulate_cpu_spike(duration=30, cpu_percent=80)
EOF",
"python3 /tmp/cpu_spike.py"
]' \
  --region $REGION
